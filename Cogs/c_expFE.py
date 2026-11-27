# coding: utf-8
import asyncio
import discord
from discord.ext import commands, tasks
from datetime import datetime as dt
from typing import Annotated
from Library import exp_level, lib_cog_scope, lib_cog_tone, lib_bot_lifecycle, lib_channel_check, lib_exp_channel_notify, lib_member_label
from DB import db_exp, db_setting, db_tone

_BTN_RANK_PREV_DEFAULT = db_tone.render_default_message('expFE_ranking_btn_prev')
_BTN_RANK_NEXT_DEFAULT = db_tone.render_default_message('expFE_ranking_btn_next')
_RANK_VIEW_TIMEOUT = 300


class _VoiceSession:
    __slots__ = ('last_tick', 'task')

    def __init__(self, last_tick: dt, task: asyncio.Task):
        self.last_tick = last_tick
        self.task = task


class _ExpRankingView(discord.ui.View):
    def __init__(
        self,
        cog: 'expFE',
        *,
        guild: discord.Guild,
        ranking_data: list,
        page: int,
        total_pages: int,
        yesterday: bool,
        sort_by_increase: bool,
        requester_id: int,
    ):
        super().__init__(timeout=_RANK_VIEW_TIMEOUT)
        self.cog = cog
        self.guild = guild
        self.guild_id = guild.id
        self.ranking_data = ranking_data
        self.page = page
        self.total_pages = total_pages
        self.yesterday = yesterday
        self.sort_by_increase = sort_by_increase
        self.requester_id = requester_id
        self.prev_button.label = cog._t(self.guild_id, 'expFE_ranking_btn_prev')
        self.next_button.label = cog._t(self.guild_id, 'expFE_ranking_btn_next')
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self.total_pages

    async def _check_requester(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            self.cog._t(self.guild_id, 'expFE_ranking_btn_denied'),
            ephemeral=True,
        )
        return False

    async def _goto(self, interaction: discord.Interaction, page: int) -> None:
        if not await self._check_requester(interaction):
            return
        await interaction.response.defer()
        self.page = page
        self._sync_buttons()
        content = await self.cog._build_ranking_content(
            self.guild,
            self.ranking_data,
            page=self.page,
            total_pages=self.total_pages,
            yesterday=self.yesterday,
            sort_by_increase=self.sort_by_increase,
        )
        await interaction.edit_original_response(content=content, view=self)

    async def on_timeout(self) -> None:
        self.disable_all_items()
        target = self.parent or self.message
        if target is None:
            return
        try:
            await target.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    @discord.ui.button(label=_BTN_RANK_PREV_DEFAULT, style=discord.ButtonStyle.secondary)
    async def prev_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._goto(interaction, self.page - 1)

    @discord.ui.button(label=_BTN_RANK_NEXT_DEFAULT, style=discord.ButtonStyle.primary)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._goto(interaction, self.page + 1)


class expFE(lib_cog_tone.ToneAwareCog, commands.Cog):
    def __init__(self, bot):
        self.bot : discord.Bot = bot
        # 통화 시간 집계 중. 봇을 제외한 인원이 2명 이상일 때만 연다.
        # 이 세션이 있을 때만 채팅 경험치를 막는다.
        self._voice_sessions: dict[tuple[int, int], _VoiceSession] = {}
        # 통화방 입장 여부. 혼자 있어도 등록은 유지하고, 채팅 경험치는 막지 않는다.
        self._voice_present: set[tuple[int, int]] = set()
        try:
            db_exp.ensure_schema()
        except Exception as e:
            print(f'expFE: schema init failed: {e}')
        self.daily_init_exp.start()

    def _resolve_daily_lines(self, guild_id: int, **kwargs) -> tuple[str, str]:
        d_arg = kwargs.get('d_arg')
        if d_arg is None:
            return '', ''

        rows = db_tone.get_template(guild_id, 'expFE_res_daily')
        if not isinstance(rows, list) or not rows:
            return str(d_arg), ''

        selected = rows[-1]
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            threshold = row[0]
            if threshold is not None and threshold >= d_arg:
                selected = row
                break

        title = db_tone.format_template(str(selected[1]), **kwargs)
        desc = db_tone.format_template(str(selected[2]), **kwargs)
        return title, desc

    @staticmethod
    def _now_kst() -> dt:
        return db_exp.getNow()

    def _owns_global_daily_init(self) -> bool:
        '''core 봇만 dailyDBInit을 돌린다. addon 프로세스가 같이 돌리면 yesterday_incr가 0이 된다.'''
        return lib_cog_scope.owns_global_daily_init(self.bot)

    def _is_in_voice(self, guild_id: int, user_id: int) -> bool:
        '''다른 사람과 같이 있는 동안만 채팅 경험치를 막는다.'''
        return (guild_id, user_id) in self._voice_sessions

    @staticmethod
    def _voice_humans(channel: discord.VoiceChannel | discord.StageChannel | None) -> list[discord.Member]:
        '''봇을 뺀 통화방 인원. 없으면 빈 리스트.'''
        if channel is None:
            return []
        return [member for member in channel.members if not member.bot]

    @staticmethod
    def _voice_channel_earns(channel: discord.VoiceChannel | discord.StageChannel | None) -> bool:
        '''봇을 제외하고 2명 이상일 때만 통화 시간을 쌓는다.'''
        return len(expFE._voice_humans(channel)) >= 2

    async def _register_voice_member_if_new(self, member: discord.Member) -> None:
        '''혼자 입장해도 회원가입·환영은 유지한다. voice_count는 올리지 않는다.'''
        if member.bot or not self._exp_member_ok(member):
            return
        if db_exp.ifUserExist(member.guild.id, member.id):
            return
        db_exp.touchLastApiCall(member.guild.id, member.id, self._now_kst())
        await self._send_welcome_embed(member.guild, member)

    async def _mark_voice_present(self, member: discord.Member) -> None:
        if member.bot:
            return
        key = (member.guild.id, member.id)
        if key in self._voice_present:
            return
        self._voice_present.add(key)
        await self._register_voice_member_if_new(member)

    async def _drop_voice_member(self, guild_id: int, user_id: int) -> None:
        '''통화방을 완전히 나감. 남은 시간은 정산하고 통화 중 표시를 지운다.'''
        self._voice_present.discard((guild_id, user_id))
        await self._stop_voice_session(guild_id, user_id)
        db_exp.clearVoicePresence(guild_id, user_id)

    async def _sync_voice_channel(self, channel: discord.VoiceChannel | discord.StageChannel) -> None:
        '''이 방의 사람 수에 맞춰 세션을 열거나 닫는다. 이미 열린 세션은 유지한다.'''
        humans = self._voice_humans(channel)
        earns = self._voice_channel_earns(channel)
        for human in humans:
            await self._mark_voice_present(human)
            if earns:
                await self._start_voice_session(human)
            else:
                await self._stop_voice_session(human.guild.id, human.id)
                # 혼자(또는 봇과만) 있으면 채팅 경험치를 막지 않는다.
                db_exp.clearVoicePresence(human.guild.id, human.id)

    def _exp_member_ok(self, member: discord.Member) -> bool:
        try:
            if not db_setting.get_setting(member.guild.id, 'exp_enable'):
                return False
            exp_role_id = db_setting.get_setting(member.guild.id, 'exp_role')
            if exp_role_id is None:
                return True
            exp_role = member.guild.get_role(exp_role_id)
            if exp_role is None:
                return True
            if exp_role in member.roles:
                return True
            if member.id == member.guild.owner_id:
                return True
            bot_admin_role_id = db_setting.get_setting(member.guild.id, 'bot_admin_role')
            if bot_admin_role_id:
                bot_admin_role = member.guild.get_role(bot_admin_role_id)
                if bot_admin_role is not None and bot_admin_role in member.roles:
                    return True
            return False
        except Exception:
            return False

    def _apply_voice_tick(self, guild_id: int, user_id: int, session: _VoiceSession) -> None:
        '''15초 주기: voice_count +150. last_tick은 voice_count를 반영한 시각.'''
        if db_exp.voiceCallAdd(guild_id, user_id, db_exp.voiceTickAmount) is not None:
            session.last_tick = self._now_kst()

    def _apply_voice_remainder(self, guild_id: int, user_id: int, session: _VoiceSession) -> None:
        '''마지막 tick 이후 ~ 퇴장(또는 종료) 시각까지 voice_count 반영. cog_unload 등 sync 경로용.'''
        amount = db_exp.voiceLeaveRemainder(session.last_tick, self._now_kst())
        if amount > 0:
            db_exp.voiceCallAdd(guild_id, user_id, amount)

    async def _voice_tick_loop(self, guild_id: int, user_id: int):
        try:
            while True:
                await asyncio.sleep(db_exp.voiceTickInterval)
                key = (guild_id, user_id)
                session = self._voice_sessions.get(key)
                if session is None:
                    break
                self._apply_voice_tick(guild_id, user_id, session)
        except asyncio.CancelledError:
            pass

    async def _start_voice_session(self, member: discord.Member):
        if member.bot:
            return
        key = (member.guild.id, member.id)
        if key in self._voice_sessions:
            return
        if not self._exp_member_ok(member):
            return
        now = self._now_kst()
        was_new = not db_exp.ifUserExist(member.guild.id, member.id)
        db_exp.touchLastApiCall(member.guild.id, member.id, now)
        task = asyncio.create_task(self._voice_tick_loop(member.guild.id, member.id))
        # last_tick: 마지막으로 voice_count를 올린 시각 (같이 있기 시작한 시각, 첫 주기 반영 전)
        self._voice_sessions[key] = _VoiceSession(now, task)
        if was_new:
            await self._send_welcome_embed(member.guild, member)

    async def _stop_voice_session(self, guild_id: int, user_id: int):
        key = (guild_id, user_id)
        session = self._voice_sessions.pop(key, None)
        if session is None:
            return
        session.task.cancel()
        try:
            await session.task
        except asyncio.CancelledError:
            pass
        db_exp.touchLastApiCall(guild_id, user_id, self._now_kst())
        self._apply_voice_remainder(guild_id, user_id, session)

    async def _recover_voice_sessions(self):
        seen_present: set[tuple[int, int]] = set()
        earning: set[tuple[int, int]] = set()
        for guild in self.bot.guilds:
            if not self._is_allowed_guild(guild.id):
                continue
            for channel in (*guild.voice_channels, *guild.stage_channels):
                humans = self._voice_humans(channel)
                earns = self._voice_channel_earns(channel)
                for member in humans:
                    key = (guild.id, member.id)
                    seen_present.add(key)
                    await self._mark_voice_present(member)
                    if earns:
                        earning.add(key)
                        await self._start_voice_session(member)
                    else:
                        await self._stop_voice_session(guild.id, member.id)
                        db_exp.clearVoicePresence(guild.id, member.id)
        for guild_id, user_id in list(self._voice_present):
            if (guild_id, user_id) not in seen_present:
                await self._drop_voice_member(guild_id, user_id)
        for guild_id, user_id in list(self._voice_sessions.keys()):
            if (guild_id, user_id) not in earning:
                await self._stop_voice_session(guild_id, user_id)
                db_exp.clearVoicePresence(guild_id, user_id)

    def cog_unload(self):
        if self.daily_init_exp.is_running():
            self.daily_init_exp.cancel()
        for guild_id, user_id in list(self._voice_sessions.keys()):
            session = self._voice_sessions.pop((guild_id, user_id))
            session.task.cancel()
            self._apply_voice_remainder(guild_id, user_id, session)

    @commands.Cog.listener()
    async def on_ready(self):
        lib_bot_lifecycle.ensure_loop_running(self.daily_init_exp)
        if self._owns_global_daily_init():
            self.bot.daily_init_exp_count = self.daily_init_exp.current_loop
            self.bot.daily_init_exp_next = self.daily_init_exp.next_iteration.astimezone(tz=db_exp.EXP_TZ) if self.daily_init_exp.next_iteration is not None else self.daily_init_exp.next_iteration
        await self._recover_voice_sessions()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not self._is_allowed_guild(member.guild.id):
            return
        if member.bot:
            return
        # 음소거·송출 변경은 인원이 그대로다.
        if before.channel == after.channel:
            return

        if after.channel is None:
            await self._drop_voice_member(member.guild.id, member.id)

        # 나간 방·들어온 방의 남은 사람을 바로 다시 판정한다.
        # 15초 틱을 기다리지 않으므로, 같이 있기 시작한 시각부터 시간이 쌓인다.
        if before.channel is not None:
            await self._sync_voice_channel(before.channel)
        if after.channel is not None:
            await self._sync_voice_channel(after.channel)

    @tasks.loop(time=db_exp.daily_init_utc_time(), reconnect=False)
    async def daily_init_exp(self):
        await lib_bot_lifecycle.run_isolated(
            'expFE: daily_init_exp iteration failed',
            self._daily_init_exp_once,
        )

    async def _daily_init_exp_once(self):
        if not self._owns_global_daily_init():
            await self._archive_exp_logs()
            return
        try:
            ran = db_exp.dailyDBInit()
        finally:
            await self._archive_exp_logs()
        if not ran:
            print('expFE: dailyDBInit skipped (already ran this exp day)')
            return
        await self._refresh_discord_profiles()
        self.bot.daily_init_exp_count = self.daily_init_exp.current_loop+1
        self.bot.daily_init_exp_next = self.daily_init_exp.next_iteration.astimezone(tz=db_exp.EXP_TZ) if self.daily_init_exp.next_iteration is not None else self.daily_init_exp.next_iteration
        db_exp.logDailyInitExp(self.bot.daily_init_exp_count, self.bot.daily_init_exp_next)

    @daily_init_exp.before_loop
    async def _before_daily_init_exp(self):
        await self.bot.wait_until_ready()
        await self._archive_exp_logs()

    async def _archive_exp_logs(self):
        try:
            await asyncio.to_thread(db_exp.archive_exp_logs)
        except Exception as exc:
            lib_bot_lifecycle.log_loop_error('expFE: archive EXP logs', exc)

    async def _refresh_discord_profiles(self) -> None:
        '''경험치 유저의 Discord 닉네임/아바타를 DB에 캐시 (웹 순위표용).'''
        uids = db_exp.listProfileCandidateUids()
        if not uids:
            return
        ok = 0
        fail = 0
        for uid in uids:
            fetched = False
            try:
                user = self.bot.get_user(uid)
                if user is None:
                    user = await self.bot.fetch_user(uid)
                    fetched = True
                avatar_hash = user.avatar.key if user.avatar is not None else None
                db_exp.upsertUserProfile(
                    uid,
                    username=user.name,
                    global_name=getattr(user, 'global_name', None),
                    avatar_hash=avatar_hash,
                )
                ok += 1
            except Exception as e:
                fail += 1
                print(f'expFE: profile refresh failed uid={uid}: {e}')
            if fetched:
                await asyncio.sleep(0.05)
        print(f'expFE: profile refresh done ok={ok} fail={fail} total={len(uids)}')

    @daily_init_exp.error
    async def daily_init_exp_error(self, error):
        lib_bot_lifecycle.log_loop_error('expFE: daily_init_exp', error)

    @commands.Cog.listener()
    async def on_message(self, message:discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not self._is_allowed_guild(message.guild.id):
            return
        if not db_setting.get_setting(message.guild.id, 'exp_enable'):
            return
        if not isinstance(message.author, discord.Member):
            return
        if not self._exp_member_ok(message.author):
            return
        was_new = not db_exp.ifUserExist(message.guild.id, message.author.id)
        in_voice = self._is_in_voice(message.guild.id, message.author.id)
        d_arg = db_exp.chatCallCalc(
            message.guild.id,
            message.author.id,
            db_exp.getNow(),
            in_voice=in_voice,
        )
        if was_new:
            await self._send_welcome_embed(message.guild, message.author)
            return
        if d_arg <= 0:
            return

        await self._send_daily_attend_embed(
            message.guild,
            message.author,
            d_arg=d_arg,
        )

    async def _build_daily_attend_embed(
        self,
        guild: discord.Guild,
        member: discord.abc.User,
        *,
        d_arg: int,
    ) -> discord.Embed:
        guild_id = guild.id
        day_count = db_exp.getData(guild_id, member.id, 'day_count') or 0
        e_title, e_desc = self._resolve_daily_lines(
            guild_id,
            author=lib_member_label.format_user_label(member),
            author_id=member.id,
            d_arg=d_arg,
            day_count=day_count,
        )
        embed = discord.Embed(
            color=db_setting.get_embed_color(guild_id),
            title=e_title,
            description=e_desc,
        )
        embed.set_footer(text=db_tone.render_embed_footer(guild_id, self.bot.ame_ver))
        return embed

    async def _build_welcome_embed(
        self,
        guild: discord.Guild,
        member: discord.abc.User,
    ) -> discord.Embed:
        guild_id = guild.id
        author = lib_member_label.format_user_label(member)
        bot_name = db_tone.render_name(guild_id)
        embed = discord.Embed(
            color=db_setting.get_embed_color(guild_id),
            title=self._t(
                guild_id,
                'expFE_res_welcome_title',
                author=author,
                bot_name=bot_name,
            ),
            description=self._t(
                guild_id,
                'expFE_res_welcome_desc',
                author=author,
                bot_name=bot_name,
            ),
        )
        embed.set_footer(text=db_tone.render_embed_footer(guild_id, self.bot.ame_ver))
        return embed

    async def _send_exp_channel_embed(
        self,
        guild: discord.Guild,
        member: discord.abc.User,
        embed: discord.Embed,
    ) -> bool:
        '''임베드를 exp_channel에 전송. 전송했으면 True.'''
        guild_id = guild.id
        exp_channel_id = db_setting.get_setting(guild_id, 'exp_channel')
        if not exp_channel_id:
            return False

        exp_issue = await lib_channel_check.exp_channel_issue(
            self.bot,
            guild,
            exp_channel_id,
        )
        if exp_issue:
            await lib_exp_channel_notify.maybe_warn_exp_channel(
                self.bot,
                guild,
                exp_channel_id,
            )
            return False

        channel = await lib_channel_check.resolve_text_channel(self.bot, exp_channel_id)
        if channel is None:
            return False

        silent_status = db_exp.getData(guild_id, member.id, 'silent')
        if silent_status:
            await channel.send(embed=embed)
        else:
            await channel.send(f'<@{member.id}>', embed=embed)
        return True

    async def _send_daily_attend_embed(
        self,
        guild: discord.Guild,
        member: discord.abc.User,
        *,
        d_arg: int,
    ) -> bool:
        '''출석 임베드를 exp_channel에 전송. 전송했으면 True.'''
        embed = await self._build_daily_attend_embed(guild, member, d_arg=d_arg)
        return await self._send_exp_channel_embed(guild, member, embed)

    async def _send_welcome_embed(
        self,
        guild: discord.Guild,
        member: discord.abc.User,
    ) -> bool:
        '''회원가입 환영 임베드를 exp_channel에 전송. 전송했으면 True.'''
        embed = await self._build_welcome_embed(guild, member)
        return await self._send_exp_channel_embed(guild, member, embed)

    @commands.slash_command(
        name='출석',
        description=db_tone.render_default_message('expFE_attend_desc'),
    )
    async def exp_attend(self, ctx: discord.ApplicationContext):
        guild_id = ctx.guild_id
        if not self._is_allowed_guild(guild_id) or ctx.guild is None:
            await ctx.respond(
                self._t(guild_id or 0, 'expFE_attend_unavailable'),
                ephemeral=True,
            )
            return
        if not db_setting.get_setting(guild_id, 'exp_enable'):
            await ctx.respond(
                self._t(guild_id, 'expFE_attend_unavailable'),
                ephemeral=True,
            )
            return
        if not isinstance(ctx.author, discord.Member) or not self._exp_member_ok(ctx.author):
            await ctx.respond(
                self._t(guild_id, 'expFE_attend_unavailable'),
                ephemeral=True,
            )
            return

        was_new = not db_exp.ifUserExist(guild_id, ctx.author.id)
        d_arg = db_exp.manualAttend(guild_id, ctx.author.id, db_exp.getNow())
        if was_new:
            embed = await self._build_welcome_embed(ctx.guild, ctx.author)
            await self._send_exp_channel_embed(ctx.guild, ctx.author, embed)
            await ctx.respond(embed=embed)
            return
        if d_arg <= 0:
            await ctx.respond(
                self._t(guild_id, 'expFE_attend_already'),
                ephemeral=True,
            )
            return

        embed = await self._build_daily_attend_embed(
            ctx.guild,
            ctx.author,
            d_arg=d_arg,
        )
        await ctx.respond(embed=embed)

    exp_commands = discord.SlashCommandGroup(
        name='경험치',
        description=db_tone.render_default_message('expFE_group_name'),
    )

    @exp_commands.command(name='현황', description=db_tone.render_default_message('expFE_status_desc'))
    async def exp_FrontEnd(self, ctx):
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        exp_point = db_exp.getData(guild_id, user_id, 'exp') or 0
        exp_increase = db_exp.getData(guild_id, user_id, 'increase') or 0
        level = exp_level.level_progress(exp_point, profile='server')
        display = lib_member_label.resolve_display_name(ctx.author)
        username = ctx.author.name
        embed = discord.Embed(
            title=self._t(
                guild_id,
                'expFE_status_embed_title',
                author=lib_member_label.format_user_label(ctx.author),
                display=display,
                username=username,
                exp=exp_point,
                exp_incr=exp_increase,
            ),
            description=self._t(
                guild_id,
                'expFE_status_embed_field_level_value',
                level=level.level,
                pct=f'{level.ratio * 100:.1f}',
                into=level.into_level,
                span=level.level_span,
                need=level.exp_to_next,
            ),
            color=db_setting.get_embed_color(guild_id),
        )
        embed.add_field(
            name=self._t(guild_id, 'expFE_status_embed_field1'),
            value=self._format_first_call(guild_id, db_exp.getData(guild_id, user_id, 'first_call')),
            inline=False,
        )
        day_count = db_exp.getData(guild_id, user_id, 'day_count') or 0
        embed.add_field(
            name=self._t(guild_id, 'expFE_status_embed_field2'),
            value=self._t(guild_id, 'expFE_status_embed_field2_value', day_count=day_count),
            inline=True,
        )
        embed.add_field(
            name=self._t(guild_id, 'expFE_status_embed_field3'),
            value=self._format_voice_duration(
                guild_id,
                db_exp.getData(guild_id, user_id, 'voice_count'),
            ),
            inline=True,
        )
        embed.add_field(
            name=self._t(guild_id, 'expFE_status_embed_field4'),
            value=self._format_chat_stats(
                guild_id,
                db_exp.getData(guild_id, user_id, 'total_chat'),
                db_exp.getData(guild_id, user_id, 'chat_count'),
            ),
            inline=True,
        )
        embed.set_footer(text=db_tone.render_embed_footer(guild_id, self.bot.ame_ver))
        await ctx.respond(embed=embed)
    
    _RANK_PER_PAGE = 20

    def _format_first_call(self, guild_id: int, ts) -> str:
        if ts is None:
            return self._t(guild_id, 'expFE_status_embed_field1_nodata')
        dt_val = db_exp.fromTimeStamp(int(ts))
        return self._t(
            guild_id,
            'expFE_status_embed_field1_value',
            year=dt_val.year,
            month=dt_val.month,
            day=dt_val.day,
            hour=dt_val.hour,
            minute=dt_val.minute,
            second=dt_val.second,
        )

    def _format_voice_duration_colon(self, voice_count) -> str:
        total_tenths = int(voice_count or 0)
        secs_whole = total_tenths // 10
        tenths = total_tenths % 10
        hours = secs_whole // 3600
        minutes = (secs_whole % 3600) // 60
        seconds = secs_whole % 60
        return f'{hours}:{minutes:02d}:{seconds}.{tenths}'

    def _format_voice_duration(self, guild_id: int, voice_count) -> str:
        form = db_tone.get_template(guild_id, 'expFE_voice_duration_form')
        if form is not None and not bool(form):
            return self._format_voice_duration_colon(voice_count)
        if not voice_count:
            return self._t(guild_id, 'expFE_voice_duration_zero')
        total_tenths = int(voice_count)
        secs_whole = total_tenths // 10
        tenths = total_tenths % 10
        hours = secs_whole // 3600
        minutes = (secs_whole % 3600) // 60
        seconds = secs_whole % 60
        parts = []
        if hours:
            parts.append(self._t(guild_id, 'expFE_voice_unit_hour', value=hours))
        if minutes:
            parts.append(self._t(guild_id, 'expFE_voice_unit_minute', value=minutes))
        if tenths:
            parts.append(
                self._t(
                    guild_id,
                    'expFE_voice_unit_second',
                    value=f'{seconds}.{tenths}',
                )
            )
        elif seconds or not parts:
            parts.append(self._t(guild_id, 'expFE_voice_unit_second', value=seconds))
        return ' '.join(parts)

    def _format_chat_stats(self, guild_id: int, total_chat, chat_count) -> str:
        total = 0 if total_chat is None else total_chat
        counted = 0 if chat_count is None else chat_count
        return self._t(guild_id, 'expFE_status_embed_field4_value', total=total, count=counted)

    def _rank_kind_label(self, guild_id: int, yesterday: bool, sort_by_increase: bool) -> str:
        if yesterday:
            key = 'expFE_ranking_option1_choice2'
        elif sort_by_increase:
            key = 'expFE_ranking_option1_choice1'
        else:
            key = 'expFE_ranking_option1_choice0'
        label = self._t(guild_id, key)
        if label.endswith(' 순위'):
            return label[:-3]
        return label

    @exp_commands.command(
        name='랭킹',
        description=db_tone.render_default_message('expFE_ranking_desc'),
    )
    async def exp_rank(self,ctx,
                       today_order:Annotated[int, discord.Option(int,description=db_tone.render_default_message('expFE_ranking_option1_desc'),name=db_tone.render_default_message('expFE_ranking_option1_name'),choices=[discord.OptionChoice(name=db_tone.render_default_message('expFE_ranking_option1_choice0'),value=0),discord.OptionChoice(name=db_tone.render_default_message('expFE_ranking_option1_choice1'),value=1),discord.OptionChoice(name=db_tone.render_default_message('expFE_ranking_option1_choice2'),value=2)],default=0)]=0,
                       page:Annotated[int, discord.Option(int,description=db_tone.render_default_message('expFE_ranking_option2_desc'), name=db_tone.render_default_message('expFE_ranking_option2_name'), min_value=1, default=1, required=False)]=1):
        guild_id = ctx.guild.id
        url = lib_cog_scope.ranking_url(self.bot, guild_id)
        if url is not None:
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(
                label=self._t(guild_id, 'expFE_ranking_web_button'),
                style=discord.ButtonStyle.link,
                url=url,
            ))
            await ctx.respond(self._t(guild_id, 'expFE_ranking_web_notice'), view=view)
            return
        respondMessage = await ctx.respond(self._t(guild_id, 'expFE_ranking_waiting'))
        yesterday = today_order == 2
        sort_by_increase = today_order != 0
        if yesterday:
            ranking_data = await asyncio.to_thread(db_exp.getYesterdayData, guild_id, sort_by_increase)
        else:
            ranking_data = await asyncio.to_thread(db_exp.getAllData, guild_id, sort_by_increase)
        total_pages = max(1, (len(ranking_data) + self._RANK_PER_PAGE - 1) // self._RANK_PER_PAGE)
        page = min(page, total_pages)
        respond = await self._build_ranking_content(
            ctx.guild,
            ranking_data,
            page=page,
            total_pages=total_pages,
            yesterday=yesterday,
            sort_by_increase=sort_by_increase,
        )
        view = None
        if total_pages > 1:
            view = _ExpRankingView(
                self,
                guild=ctx.guild,
                ranking_data=ranking_data,
                page=page,
                total_pages=total_pages,
                yesterday=yesterday,
                sort_by_increase=sort_by_increase,
                requester_id=ctx.author.id,
            )
        try:
            await respondMessage.edit_original_response(content=respond, view=view)
            if view is not None:
                view.message = await respondMessage.original_response()
        except discord.errors.NotFound:
            channel = self.bot.get_channel(ctx.channel.id)
            await channel.send(
                respond
                + '\n'
                + self._t(guild_id, 'expFE_ranking_interaction_closed', id=ctx.author.id)
            )

    async def _build_ranking_content(
        self,
        guild: discord.Guild,
        ranking_data: list,
        *,
        page: int,
        total_pages: int,
        yesterday: bool,
        sort_by_increase: bool,
    ) -> str:
        guild_id = guild.id
        since = (page - 1) * self._RANK_PER_PAGE + 1
        until = min(page * self._RANK_PER_PAGE, len(ranking_data))
        kind = self._rank_kind_label(guild_id, yesterday, sort_by_increase)
        header = self._t(
            guild_id,
            'expFE_ranking_result_header',
            guild_name=guild.name,
            kind=kind,
            page=page,
            total_pages=total_pages,
        )
        body = await self._format_ranking_lines(guild_id, guild, ranking_data, since, until)
        return f'{header}\n{body}'

    async def _format_ranking_lines(
        self,
        guild_id: int,
        guild: discord.Guild,
        data: list,
        since: int,
        until: int,
    ) -> str:
        if not data or since > len(data) or since > until:
            return self._t(guild_id, 'expFE_ranking_result_nomember')

        def resolve_display(user) -> str:
            return (
                getattr(user, 'display_name', None)
                or getattr(user, 'global_name', None)
                or user.name
            )

        leaved_suffix = self._t(guild_id, 'expFE_ranking_result_leaved')
        lines = []
        for i in range(since - 1, until):
            uid, score, delta = data[i][0], data[i][1], data[i][2]
            rank = i + 1
            try:
                user = await guild.fetch_member(uid)
                display = resolve_display(user)
                username = user.name
            except discord.NotFound:
                user = await self.bot.get_or_fetch_user(uid)
                display = resolve_display(user) + leaved_suffix
                username = user.name
            display = display.replace('_', '\\_')
            username = username.replace('_', '\\_')
            lines.append(
                self._t(
                    guild_id,
                    'expFE_ranking_result_line',
                    rank=rank,
                    display=display,
                    username=username,
                    score=score,
                    delta=delta,
                )
            )
        return '\n'.join(lines)

    def _mention_response(self, guild_id: int, result: int) -> str:
        match result:
            case 0:
                return self._t(guild_id, 'expFE_mention_on')
            case 1:
                return self._t(guild_id, 'expFE_mention_off')
            case -1:
                return self._t(guild_id, 'expFE_mention_error')

    @exp_commands.command(
        name='멘션',
        description=db_tone.render_default_message('expFE_mention_desc'),
    )
    async def exp_mention(
        self,
        ctx,
        enabled: Annotated[
            int,
            discord.Option(
                int,
                name=db_tone.render_default_message('expFE_mention_option_name'),
                description=db_tone.render_default_message('expFE_mention_option_desc'),
                choices=[
                    discord.OptionChoice(
                        name=db_tone.render_default_message('expFE_mention_option_choice_on'),
                        value=1,
                    ),
                    discord.OptionChoice(
                        name=db_tone.render_default_message('expFE_mention_option_choice_off'),
                        value=0,
                    ),
                ],
            ),
        ],
    ):
        guild_id = ctx.guild.id
        result = db_exp.changeSilentStatus(guild_id, ctx.author.id, not enabled)
        await ctx.respond(self._mention_response(guild_id, result), ephemeral=True)

def setup(bot):
    bot.add_cog(expFE(bot))
