# coding: utf-8
import asyncio
import discord
from discord.ext import commands, tasks
from datetime import datetime as dt
from typing import Annotated
import lib_channel_check
import db_exp
import db_setting
import db_tone
import lib_exp_channel_notify
import lib_member_label

class _VoiceSession:
    __slots__ = ('last_tick', 'task')

    def __init__(self, last_tick: dt, task: asyncio.Task):
        self.last_tick = last_tick
        self.task = task

class expFE(commands.Cog):
    def __init__(self, bot):
        self.bot : discord.Bot = bot
        self.bot.ame_color = 0xa57bdb
        self._voice_sessions: dict[tuple[int, int], _VoiceSession] = {}
        try:
            db_exp.ensure_schema()
        except Exception as e:
            print(f'expFE: schema init failed: {e}')
        self.daily_init_exp.start()

    def _t(self, guild_id: int, message_key: str, **kwargs) -> str:
        return db_tone.render_message(guild_id, message_key, **kwargs)

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

    def _is_in_voice(self, guild_id: int, user_id: int) -> bool:
        return (guild_id, user_id) in self._voice_sessions

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
        task = asyncio.create_task(self._voice_tick_loop(member.guild.id, member.id))
        # last_tick: 마지막으로 voice_count를 올린 시각 (입장 직후, 첫 주기/퇴장 반영 전)
        self._voice_sessions[key] = _VoiceSession(now, task)

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
        amount = db_exp.voiceLeaveRemainder(session.last_tick, self._now_kst())
        if amount > 0:
            db_exp.voiceCallAdd(guild_id, user_id, amount)

    async def _recover_voice_sessions(self):
        active_keys: set[tuple[int, int]] = set()
        for guild in self.bot.guilds:
            for channel in (*guild.voice_channels, *guild.stage_channels):
                for member in channel.members:
                    active_keys.add((guild.id, member.id))
                    await self._start_voice_session(member)
        for guild_id, user_id in list(self._voice_sessions.keys()):
            if (guild_id, user_id) not in active_keys:
                await self._stop_voice_session(guild_id, user_id)

    def cog_unload(self):
        for guild_id, user_id in list(self._voice_sessions.keys()):
            session = self._voice_sessions.pop((guild_id, user_id))
            session.task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.daily_init_exp_count = self.daily_init_exp.current_loop
        self.bot.daily_init_exp_next = self.daily_init_exp.next_iteration.astimezone(tz=db_exp.EXP_TZ) if self.daily_init_exp.next_iteration is not None else self.daily_init_exp.next_iteration
        await self._recover_voice_sessions()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        was_in_voice = before.channel is not None
        is_in_voice = after.channel is not None
        if not was_in_voice and is_in_voice:
            await self._start_voice_session(member)
        elif was_in_voice and not is_in_voice:
            await self._stop_voice_session(member.guild.id, member.id)

    @tasks.loop(time=db_exp.daily_init_utc_time(), reconnect=False)
    async def daily_init_exp(self):
        db_exp.dailyDBInit()
        self.bot.daily_init_exp_count = self.daily_init_exp.current_loop+1
        self.bot.daily_init_exp_next = self.daily_init_exp.next_iteration.astimezone(tz=db_exp.EXP_TZ) if self.daily_init_exp.next_iteration is not None else self.daily_init_exp.next_iteration
        dbgChannel = await self.bot.fetch_channel(self.bot.dbgChannel)
        await dbgChannel.send(f'exp daily_init_exp {self.bot.daily_init_exp_count}번째 작동, 다음은 {self.bot.daily_init_exp_next}')

    @commands.Cog.listener()
    async def on_message(self, message:discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not db_setting.get_setting(message.guild.id, 'exp_enable'):
            return
        if not isinstance(message.author, discord.Member):
            return
        if not self._exp_member_ok(message.author):
            return
        try:
            in_voice = self._is_in_voice(message.guild.id, message.author.id)
            d_arg = db_exp.chatCallCalc(
                message.guild.id,
                message.author.id,
                db_exp.getNow(),
                in_voice=in_voice,
            )
        except Exception as e:
            raise e
        else:
            if not d_arg:
                return

            guild_id = message.guild.id
            day_count = db_exp.getData(guild_id, message.author.id, 'day_count') or 0
            tone_kwargs = {
                'author': lib_member_label.format_user_label(message.author),
                'author_id': message.author.id,
                'd_arg': d_arg,
                'day_count': day_count,
            }

            if d_arg == -1:
                e_title = self._t(guild_id, 'expFE_res_error_title', **tone_kwargs)
                e_desc = self._t(guild_id, 'expFE_res_error_desc', **tone_kwargs)
            else:
                e_title, e_desc = self._resolve_daily_lines(
                    guild_id,
                    **tone_kwargs,
                )

            exp_channel_id = db_setting.get_setting(guild_id, 'exp_channel')
            if not exp_channel_id:
                return

            exp_issue = lib_channel_check.exp_channel_issue(
                self.bot,
                message.guild,
                exp_channel_id,
            )
            if exp_issue:
                await lib_exp_channel_notify.maybe_warn_exp_channel(
                    self.bot,
                    message.guild,
                    exp_channel_id,
                )
                return

            channel = self.bot.get_channel(exp_channel_id)
            silentStatus = db_exp.getData(guild_id, message.author.id, 'silent')
            if silentStatus:
                await channel.send(f'{e_title}\n{e_desc}')
            else:
                await channel.send(
                    f'<@{message.author.id}> {e_title}\n{e_desc}',
                )

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
        embed = discord.Embed(
            title=self._t(
                guild_id,
                'expFE_status_embed_title',
                author=lib_member_label.format_user_label(ctx.author),
                exp=exp_point,
                exp_incr=exp_increase,
            ),
            color=self.bot.ame_color,
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

    def _format_voice_duration(self, guild_id: int, voice_count) -> str:
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
                    'expFE_voice_unit_second_frac',
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
                       todayOrder:Annotated[int, discord.Option(int,description=db_tone.render_default_message('expFE_ranking_option1_desc'),name=db_tone.render_default_message('expFE_ranking_option1_name'),choices=[discord.OptionChoice(name=db_tone.render_default_message('expFE_ranking_option1_choice0'),value=0),discord.OptionChoice(name=db_tone.render_default_message('expFE_ranking_option1_choice1'),value=1),discord.OptionChoice(name=db_tone.render_default_message('expFE_ranking_option1_choice2'),value=2)],default=0)]=0,
                       page:Annotated[int, discord.Option(int,description=db_tone.render_default_message('expFE_ranking_option2_desc'), name=db_tone.render_default_message('expFE_ranking_option2_name'), min_value=1, default=1, required=False)]=1):
        guild_id = ctx.guild.id
        respondMessage = await ctx.respond(self._t(guild_id, 'expFE_ranking_waiting'))
        yesterday = todayOrder == 2
        sort_by_increase = todayOrder != 0
        if yesterday:
            ranking_data = db_exp.getYesterdayData(guild_id, sort_by_increase)
        else:
            ranking_data = db_exp.getAllData(guild_id, sort_by_increase)
        total_pages = max(1, (len(ranking_data) + self._RANK_PER_PAGE - 1) // self._RANK_PER_PAGE)
        page = min(page, total_pages)
        since = (page - 1) * self._RANK_PER_PAGE + 1
        until = min(page * self._RANK_PER_PAGE, len(ranking_data))
        kind = self._rank_kind_label(guild_id, yesterday, sort_by_increase)
        header = self._t(
            guild_id,
            'expFE_ranking_result_header',
            guild_name=ctx.guild.name,
            kind=kind,
            page=page,
            total_pages=total_pages,
        )
        body = await self.__format_ranking_lines(guild_id, ctx.guild, ranking_data, since, until)
        respond = f'{header}\n{body}'
        try:
            await respondMessage.edit_original_response(content=respond)
        except discord.errors.NotFound:
            channel = self.bot.get_channel(ctx.channel.id)
            await channel.send(
                respond
                + '\n'
                + self._t(guild_id, 'expFE_ranking_interaction_closed', id=ctx.author.id)
            )
        except Exception as e:
            raise e

    async def __format_ranking_lines(
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
            except Exception as e:
                raise e
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
                return self._t(guild_id, 'expFE_mention_error_bool')
            case -2:
                return self._t(guild_id, 'expFE_mention_error_none')
            case _:
                return self._t(guild_id, 'expFE_mention_error_undef', result=result)

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
        await ctx.respond(self._mention_response(guild_id, result))

def setup(bot):
    bot.add_cog(expFE(bot))
