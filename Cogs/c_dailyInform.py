# coding: utf-8
import asyncio
import re
from datetime import datetime as dt
from datetime import timedelta as td
from datetime import timezone as tz
from typing import Annotated

import discord
from discord.ext import commands, tasks

from DB import db_dailyInform, db_setting, db_tone
from Library.lib_schedule import KST, Schedule, parse_schedule
from Library import lib_cog_scope, lib_autocomplete, lib_bot_admin, lib_bot_lifecycle, lib_member_label

# "시간"(duration)과 구분: "10시 31분" / "15시 반" / "20시 정각" / "23시" 허용.
# "2시간 30분"은 매칭하지 않음.
_CLOCK_SI_BUN_RE = re.compile(r'^(\d+)\s*시(?!간)\s*(\d+)\s*분$')
_CLOCK_SI_HALF_RE = re.compile(r'^(\d+)\s*시(?!간)\s*반$')
_CLOCK_SI_OCLOCK_RE = re.compile(r'^(\d+)\s*시(?!간)\s*정각$')
_CLOCK_SI_ONLY_RE = re.compile(r'^(\d+)\s*시(?!간)$')
_CLOCK_COLON_RE = re.compile(r'^(\d+)\s*:\s*(\d+)$')
_TIME_INPUT_MAX_LEN = 16
_PERIOD_CHOICES = [
    discord.OptionChoice(
        name=db_tone.render_default_message(f'dailyInform_period_choice_{value}'), value=value,
    )
    for value in ('daily', 'weekly', 'monthly', 'yearly', 'once')
]


def _autocomplete_guild(ctx: discord.AutocompleteContext) -> discord.Guild | None:
    return lib_autocomplete.autocomplete_guild(ctx)


async def _daily_inform_manage_autocomplete(ctx: discord.AutocompleteContext):
    guild = _autocomplete_guild(ctx)
    if guild is None:
        return []
    cog = ctx.bot.get_cog('dailyInform')
    if cog is None:
        return []
    return await cog.daily_inform_autocomplete_choices(ctx)


class _DailyInformListView(discord.ui.View):
    def __init__(self, cog, *, guild_id, rows, page, requester_id):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.rows = rows
        self.page = page
        self.total_pages = (len(rows) + cog._ALERTS_PER_PAGE - 1) // cog._ALERTS_PER_PAGE
        self.requester_id = requester_id
        self.prev_button.label = cog._t(guild_id, 'dailyInform_list_btn_prev')
        self.next_button.label = cog._t(guild_id, 'dailyInform_list_btn_next')
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self.total_pages

    async def _goto(self, interaction, page):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                self.cog._t(self.guild_id, 'dailyInform_list_btn_denied'), ephemeral=True,
            )
            return
        self.page = max(1, min(page, self.total_pages))
        self._sync_buttons()
        await interaction.response.edit_message(
            **self.cog._build_list_page(self.guild_id, self.rows, self.page), view=self,
        )

    async def on_timeout(self):
        target = self.parent or self.message
        if target is None:
            return
        try:
            await target.edit(view=None)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    @discord.ui.button(label=db_tone.render_default_message('dailyInform_list_btn_prev'),
                       style=discord.ButtonStyle.secondary)
    async def prev_button(self, button, interaction):
        await self._goto(interaction, self.page - 1)

    @discord.ui.button(label=db_tone.render_default_message('dailyInform_list_btn_next'),
                       style=discord.ButtonStyle.primary)
    async def next_button(self, button, interaction):
        await self._goto(interaction, self.page + 1)


class _DailyInformFormModal(discord.ui.DesignerModal):
    def __init__(
        self,
        cog: 'dailyInform',
        *,
        mode: str,
        guild_id: int,
        requester_id: int,
        channel_id: int | None = None,
        row: db_dailyInform.DailyInformRow | None = None,
        period: str | None = None,
    ):
        self.cog = cog
        self.mode = mode
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.channel_id = channel_id
        self.row_id = row.id if row is not None else None
        self.author_id = row.author if row is not None else requester_id
        self.period = period or (row.schedule.kind if row is not None else 'daily')
        initial_schedule = row.schedule if row is not None and row.schedule.kind == self.period else Schedule()

        time_value = ''
        message_value = ''
        if row is not None:
            time_value = f'{(row.time_min // 60):02d}{(row.time_min % 60):02d}'
            message_value = row.message

        self.time_input = discord.ui.InputText(
            custom_id='dailyInform:time',
            placeholder=cog._t(guild_id, 'dailyInform_modal_field_time_placeholder'),
            required=True,
            max_length=_TIME_INPUT_MAX_LEN,
            value=time_value[:_TIME_INPUT_MAX_LEN],
        )
        self.message_input = discord.ui.InputText(
            custom_id='dailyInform:message',
            placeholder=cog._t(guild_id, 'dailyInform_modal_field_message_placeholder'),
            required=True,
            max_length=db_dailyInform.MESSAGE_MAX_LEN,
            value=message_value[:db_dailyInform.MESSAGE_MAX_LEN],
            style=discord.InputTextStyle.long,
        )
        self.channel_select: discord.ui.ChannelSelect | None = None
        modal_items: list[discord.ui.Item] = [
            discord.ui.Label(
                cog._t(guild_id, 'dailyInform_modal_field_time_label'),
                item=self.time_input,
            ),
        ]
        self.weekday_input = None
        self.date_input = None
        if self.period == 'weekly':
            self.weekday_input = discord.ui.CheckboxGroup(
                custom_id='dailyInform:weekdays', min_values=1, max_values=7,
                options=[
                    discord.CheckboxGroupOption(
                        label=cog._t(guild_id, f'dailyInform_weekday_{weekday}'),
                        value=str(weekday),
                        default=bool(initial_schedule.weekdays & (1 << weekday)),
                    )
                    for weekday in range(7)
                ],
            )
            modal_items.append(discord.ui.Label(
                cog._t(guild_id, 'dailyInform_weekdays_label'), item=self.weekday_input,
            ))
        elif self.period in ('monthly', 'yearly', 'once'):
            self.date_input = discord.ui.InputText(
                custom_id='dailyInform:date', required=True, max_length=32,
                placeholder=cog._t(guild_id, f'dailyInform_date_placeholder_{self.period}'),
                value=initial_schedule.date_input(),
            )
            modal_items.insert(0, discord.ui.Label(
                cog._t(guild_id, f'dailyInform_date_label_{self.period}'), item=self.date_input,
            ))
        if mode == 'edit' and row is not None:
            self.channel_select = discord.ui.ChannelSelect(
                custom_id='dailyInform:channel',
                placeholder=cog._t(guild_id, 'dailyInform_modal_field_channel_placeholder'),
                channel_types=[
                    discord.ChannelType.text,
                    discord.ChannelType.news,
                    discord.ChannelType.public_thread,
                    discord.ChannelType.private_thread,
                ],
                min_values=1,
                max_values=1,
                default_values=[
                    discord.SelectDefaultValue(
                        id=row.channel,
                        type=discord.SelectDefaultValueType.channel,
                    )
                ],
            )
            modal_items.append(
                discord.ui.Label(
                    cog._t(guild_id, 'dailyInform_modal_field_channel_label'),
                    item=self.channel_select,
                )
            )
        modal_items.append(
            discord.ui.Label(
                cog._t(guild_id, 'dailyInform_modal_field_message_label'),
                item=self.message_input,
            )
        )
        title_key = (
            'dailyInform_modal_title'
            if mode == 'add'
            else 'dailyInform_modal_edit_title'
        )
        super().__init__(
            *modal_items,
            title=cog._t(guild_id, title_key),
        )

    async def callback(self, interaction: discord.Interaction):
        if (interaction.guild_id != self.guild_id or interaction.user.id != self.requester_id
                or not self.cog._is_allowed_guild(self.guild_id)):
            await interaction.response.send_message(
                self.cog._t(self.guild_id, 'dailyInform_not_found'), ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await self.cog._prepare_tone(self.guild_id)
        if self.mode == 'add':
            await self.cog._handle_add_modal_submit(interaction, self)
            return
        await self.cog._handle_edit_modal_submit(interaction, self)


class _DailyInformDeleteModal(discord.ui.DesignerModal):
    def __init__(
        self,
        cog: 'dailyInform',
        *,
        guild_id: int,
        requester_id: int,
        row: db_dailyInform.DailyInformRow,
    ):
        self.cog = cog
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.row_id = row.id
        self.author_id = row.author
        self.row_message = row.message
        super().__init__(
            discord.ui.TextDisplay(
                cog._t(
                    guild_id,
                    'dailyInform_delete_confirm',
                    time=cog._format_schedule(guild_id, row.schedule, row.time_min),
                    message=row.message,
                )
            ),
            title=cog._t(guild_id, 'dailyInform_modal_delete_title'),
        )

    async def callback(self, interaction: discord.Interaction):
        if (interaction.guild_id != self.guild_id or interaction.user.id != self.requester_id
                or not self.cog._is_allowed_guild(self.guild_id)):
            await interaction.response.send_message(
                self.cog._t(self.guild_id, 'dailyInform_not_found'), ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await self.cog._prepare_tone(self.guild_id)
        await self.cog._handle_delete_modal_submit(interaction, self)


class dailyInform(commands.Cog):
    _ALERTS_PER_PAGE = 5
    _RESTART_CATCHUP_MINUTES = 15
    _MAX_ATTEMPTS_PER_SOURCE = 50
    _QUERY_BATCH_SIZE = 7

    def __init__(self, bot):
        self.bot: discord.Bot = bot
        self._last_sent_key = None
        self._scheduler_scope: str | None = None
        self._alerted = {}
        self._alert_cooldown = td(hours=1)
        self._sent_once_pending_cleanup = {}
        self._recurring_pending_cleanup = {}
        self._tone_profiles = {}
        self.daily_inform.start()

    def _is_allowed_guild(self, guild_id: int | None) -> bool:
        return lib_cog_scope.is_cog_allowed_guild(self.bot, self, guild_id)

    def _t(self, guild_id: int, message_key: str, **kwargs) -> str:
        profile = self._tone_profiles.get(guild_id, db_tone.DEFAULT_PROFILE)
        return db_tone.render_message_for_profile(guild_id, message_key, profile, **kwargs)

    async def _prepare_tone(self, guild_id: int):
        self._tone_profiles[guild_id] = await asyncio.to_thread(db_tone.get_profile_key, guild_id)

    async def _respond(self, interaction: discord.Interaction, content: str, *, ephemeral: bool = True):
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)

    def _fail_reason_label(self, guild_id: int, reason: str) -> str:
        key = f'dailyInform_fail_reason_{reason}'
        label = self._t(guild_id, key)
        return reason if label == key else label

    async def _load_scheduler_state(self) -> None:
        if self.bot.user is None:
            return
        self._scheduler_scope = str(self.bot.user.id)
        try:
            key = await asyncio.to_thread(db_dailyInform.get_scheduler_state, self._scheduler_scope)
        except Exception as e:
            print(f'dailyInform: scheduler state load failed: {e}')
            return
        if key is not None:
            self._last_sent_key = key

    @commands.Cog.listener()
    async def on_ready(self):
        lib_bot_lifecycle.ensure_loop_running(self.daily_inform)
        self.bot.daily_inform_count = self.daily_inform.current_loop
        self.bot.daily_inform_next = (
            self.daily_inform.next_iteration.astimezone(tz=tz(td(hours=9)))
            if self.daily_inform.next_iteration is not None
            else None
        )

    @tasks.loop(seconds=1.0)
    async def daily_inform(self):
        await lib_bot_lifecycle.run_isolated(
            'dailyInform: daily_inform iteration failed',
            self._daily_inform_once,
        )

    async def _daily_inform_once(self):
        now = dt.now(tz=tz(td(hours=9)))
        current_minute = now.replace(second=0, microsecond=0)
        current_key = self._make_key(current_minute)
        if self._last_sent_key == current_key:
            return

        if self._last_sent_key is None:
            send_minute = current_minute
        else:
            last_dt = self._key_to_dt(self._last_sent_key)
            if current_minute <= last_dt:
                return
            send_minute = last_dt + td(minutes=1)
            earliest = current_minute - td(minutes=self._RESTART_CATCHUP_MINUTES)
            if send_minute < earliest:
                send_minute = earliest

        send_counts = {}
        scope = self._scheduler_scope or 'default'

        while send_minute <= current_minute:
            minute_of_day = send_minute.hour * 60 + send_minute.minute
            try:
                rows = await asyncio.to_thread(db_dailyInform.get_due_recurring_messages, send_minute)
                rows = [row for row in rows if self._is_allowed_guild(row.guild)]
                await asyncio.to_thread(db_dailyInform.enqueue_recurring_messages, scope, send_minute, rows)
            except Exception as e:
                print(f'dailyInform: DB error: {e}')
                break

            self._last_sent_key = (send_minute.year, send_minute.month, send_minute.day, minute_of_day)
            send_minute += td(minutes=1)

        await self._send_pending_recurring_messages(scope, now, send_counts)
        await self._send_due_once_messages(now, send_counts)
        self._update_task_meta()

    @daily_inform.error
    async def daily_inform_error(self, error):
        lib_bot_lifecycle.log_loop_error('dailyInform: daily_inform', error)

    def _update_task_meta(self):
        self.bot.daily_inform_count = self.daily_inform.current_loop + 1
        self.bot.daily_inform_next = (
            self.daily_inform.next_iteration.astimezone(tz=tz(td(hours=9)))
            if self.daily_inform.next_iteration is not None
            else None
        )

    def _should_alert(self, guild_id: int, channel_id: int, reason: str, now: dt) -> bool:
        key = (guild_id, channel_id, reason)
        last = self._alerted.get(key)
        if last and (now - last) < self._alert_cooldown:
            return False
        self._alerted[key] = now
        return True

    async def _get_guild_owner_user(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except Exception:
                return None
        owner_id = getattr(guild, 'owner_id', None)
        if owner_id is None:
            return None
        user = self.bot.get_user(owner_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(owner_id)
            except Exception:
                return None
        return user

    async def _notify_send_failure(self, guild_id: int, channel_id: int, reason: str, detail: str = None):
        # 스케줄러 while 루프에서 await되므로, 여기서 예외가 나가면
        # 해당 분의 _last_sent_key 갱신이 건너뛰어져 이미 보낸 알림이 재전송될 수 있다.
        try:
            await self._notify_send_failure_inner(guild_id, channel_id, reason, detail)
        except Exception as e:
            print(f'dailyInform: send failure notify failed: {e}')

    async def _notify_send_failure_inner(
        self, guild_id: int, channel_id: int, reason: str, detail: str = None
    ):
        now = dt.now(tz=tz(td(hours=9)))
        if not self._should_alert(guild_id, channel_id, reason, now):
            return
        await self._prepare_tone(guild_id)
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except Exception:
                guild = None
        if guild is not None and getattr(guild, 'name', None):
            guild_name = guild.name
        else:
            # _t(guild_id, ..., guild_id=...) 는 positional/keyword 충돌로 TypeError.
            guild_name = self._t(guild_id, 'dailyInform_guild_unknown', unknown_id=guild_id)
        msg = self._t(
            guild_id,
            'dailyInform_send_failure',
            guild_name=guild_name,
            channel_id=channel_id,
            reason=self._fail_reason_label(guild_id, reason),
        )
        if detail:
            msg += self._t(guild_id, 'dailyInform_send_failure_detail', detail=detail)

        dm_sent = False
        owner = await self._get_guild_owner_user(guild_id)
        if owner is not None:
            try:
                await owner.send(msg)
                dm_sent = True
            except Exception:
                dm_sent = False

        if dm_sent:
            return

        try:
            log_channel_id = await asyncio.to_thread(db_setting.get_setting, guild_id, 'bot_log_channel')
        except Exception:
            return
        if not log_channel_id:
            return
        channel = self.bot.get_channel(log_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(log_channel_id)
            except Exception:
                return
        try:
            await channel.send(msg)
        except Exception:
            return

    def _parse_clock_hm(self, hour: int, minute: int) -> int | None:
        if hour > 23 or minute > 59:
            return None
        return hour * 60 + minute

    def _parse_hhmm_int(self, time_value: int) -> int | None:
        if time_value < 0 or time_value > 2359:
            return None
        return self._parse_clock_hm(time_value // 100, time_value % 100)

    def _parse_time_min(self, time_value: str | int) -> int | None:
        if isinstance(time_value, int):
            return self._parse_hhmm_int(time_value)

        raw = (time_value or '').strip()
        if not raw:
            return None

        si_bun = _CLOCK_SI_BUN_RE.fullmatch(raw)
        if si_bun is not None:
            return self._parse_clock_hm(int(si_bun.group(1)), int(si_bun.group(2)))

        si_half = _CLOCK_SI_HALF_RE.fullmatch(raw)
        if si_half is not None:
            return self._parse_clock_hm(int(si_half.group(1)), 30)

        si_oclock = _CLOCK_SI_OCLOCK_RE.fullmatch(raw)
        if si_oclock is not None:
            return self._parse_clock_hm(int(si_oclock.group(1)), 0)

        si_only = _CLOCK_SI_ONLY_RE.fullmatch(raw)
        if si_only is not None:
            return self._parse_clock_hm(int(si_only.group(1)), 0)

        colon = _CLOCK_COLON_RE.fullmatch(raw)
        if colon is not None:
            return self._parse_clock_hm(int(colon.group(1)), int(colon.group(2)))

        if raw.isdigit():
            return self._parse_hhmm_int(int(raw))
        return None

    def _format_time_text(self, guild_id: int, time_min: int) -> str:
        return self._t(
            guild_id,
            'dailyInform_time_text',
            hour=time_min // 60,
            minute=time_min % 60,
        )

    def _format_time_clock(self, time_min: int) -> str:
        return f'{time_min // 60:02d}:{time_min % 60:02d}'

    def _format_schedule(self, guild_id: int, schedule: Schedule, time_min: int) -> str:
        days = ', '.join(
            self._t(guild_id, f'dailyInform_weekday_{weekday}')
            for weekday in range(7) if schedule.weekdays & (1 << weekday)
        )
        return self._t(
            guild_id, f'dailyInform_schedule_{schedule.kind}',
            weekdays=days, month=schedule.month, day=schedule.day, year=schedule.year,
            time=self._format_time_clock(time_min),
        )

    def _format_channel_label(self, guild_id: int, channel_id: int) -> str:
        guild = self.bot.get_guild(guild_id)
        if guild is not None:
            channel = guild.get_channel(channel_id)
            if channel is None:
                channel = guild.get_thread(channel_id)
            if channel is not None and hasattr(channel, 'mention'):
                return channel.mention
        return f'<#{channel_id}>'

    async def _guild_only(self, ctx) -> bool:
        if ctx.guild is None or not self._is_allowed_guild(ctx.guild.id):
            return False
        await self._prepare_tone(ctx.guild.id)
        return True

    async def _is_bot_admin(self, member: discord.Member) -> bool:
        # 예약메세지 수정·삭제는 작성자 또는 bot_admin_role/서버 소유자만 가능.
        # 봇 소유자(include_bot_owner) 우회는 의도적으로 제외 — 다른 Cog(설정/인증)와 다른 정책.
        return await asyncio.to_thread(lib_bot_admin.is_bot_admin, member, include_bot_owner=False)

    async def _can_manage_row(self, user, author_id: int) -> bool:
        if author_id and user.id == author_id:
            return True
        if isinstance(user, discord.Member):
            return await self._is_bot_admin(user)
        return False

    async def _author_label(self, guild: discord.Guild, author_id: int) -> str:
        guild_id = guild.id if guild is not None else 0
        if not author_id:
            return self._t(guild_id, 'dailyInform_author_unknown')
        member = None
        if guild is not None:
            member = guild.get_member(author_id)
            if member is None:
                try:
                    member = await guild.fetch_member(author_id)
                except Exception:
                    member = None
        user = member or self.bot.get_user(author_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(author_id)
            except Exception:
                user = None
        if user is None:
            return self._t(guild_id, 'dailyInform_author_id', author_id=author_id)

        return lib_member_label.format_user_label(user)

    def _user_mention(self, guild_id: int, user_id: int) -> str:
        if not user_id:
            return self._t(guild_id, 'dailyInform_author_unknown')
        return f'<@{user_id}>'

    def _format_list_authors(
        self,
        guild_id: int,
        row: db_dailyInform.DailyInformRow,
    ) -> str:
        author = self._user_mention(guild_id, row.author)
        if not row.last_editor:
            return self._t(guild_id, 'dailyInform_list_authors_only', author=author)
        editor = self._user_mention(guild_id, row.last_editor)
        return self._t(
            guild_id,
            'dailyInform_list_authors_with_editor',
            author=author,
            editor=editor,
        )

    def _format_list_line(
        self,
        guild_id: int,
        order: int,
        row: db_dailyInform.DailyInformRow,
    ) -> str:
        return self._t(
            guild_id,
            'dailyInform_list_line',
            order=order,
            id=row.id,
            message=row.message,
            time=self._format_schedule(guild_id, row.schedule, row.time_min),
            authors=self._format_list_authors(guild_id, row),
        )

    async def _respond_missing_guild(self, ctx):
        guild_id = ctx.guild.id if ctx.guild else 0
        await ctx.respond(
            await asyncio.to_thread(db_tone.render_validation_error, guild_id, '서버 전용 명령어가 DM에서 사용됨'),
            ephemeral=True,
        )

    async def _respond_invalid_time(self, ctx):
        guild_id = ctx.guild.id if ctx.guild else 0
        await ctx.respond(self._t(guild_id, 'dailyInform_invalid_time'), ephemeral=True)

    async def _get_manage_target(self, ctx, row_id: int, verb: str):
        if not await self._guild_only(ctx):
            await self._respond_missing_guild(ctx)
            return None

        guild_id = ctx.guild.id
        row = await asyncio.to_thread(db_dailyInform.get_message_by_id, guild_id, row_id)
        if row is None:
            await ctx.respond(self._t(guild_id, 'dailyInform_not_found'), ephemeral=True)
            return None

        if not await self._can_manage_row(ctx.author, row.author):
            owner = await self._author_label(ctx.guild, row.author)
            await ctx.respond(
                self._t(guild_id, 'dailyInform_perm_denied', owner=owner, verb=verb),
                ephemeral=True,
            )
            return None
        return row

    def _autocomplete_choice_label(self, row: db_dailyInform.DailyInformRow) -> str:
        message_preview = row.message.replace('\n', ' ')
        label = f'{self._format_schedule(row.guild, row.schedule, row.time_min)} · {message_preview}'
        return label[:100]

    async def _ordered_manage_rows(
        self,
        guild: discord.Guild,
        user: discord.User | discord.Member,
    ) -> list[db_dailyInform.DailyInformRow]:
        rows = await asyncio.to_thread(db_dailyInform.get_messages_by_guild, guild.id)
        own_rows = [row for row in rows if row.author == user.id]
        if isinstance(user, discord.Member) and await self._is_bot_admin(user):
            other_rows = [row for row in rows if row.author != user.id]
            return own_rows + other_rows
        return own_rows

    async def daily_inform_autocomplete_choices(
        self,
        ctx: discord.AutocompleteContext,
    ) -> list[discord.OptionChoice]:
        guild = _autocomplete_guild(ctx)
        if guild is None or ctx.interaction.user is None:
            return []
        await self._prepare_tone(guild.id)
        rows = await self._ordered_manage_rows(guild, ctx.interaction.user)
        current = (ctx.value or '').strip().lower()
        choices: list[discord.OptionChoice] = []
        for row in rows:
            label = self._autocomplete_choice_label(row)
            if current and current not in label.lower() and current not in str(row.id):
                continue
            choices.append(discord.OptionChoice(name=label, value=str(row.id)))
            if len(choices) >= 25:
                break
        return choices

    async def _parse_modal_values(
        self,
        interaction: discord.Interaction,
        modal: _DailyInformFormModal,
    ) -> tuple[int, str, int, Schedule] | None:
        guild_id = modal.guild_id
        time_raw = (modal.time_input.value or '').strip()
        time_min = self._parse_time_min(time_raw)
        if time_min is None:
            await self._respond(interaction,
                self._t(guild_id, 'dailyInform_invalid_time'),
                ephemeral=True,
            )
            return None

        try:
            schedule = parse_schedule(
                modal.period,
                modal.date_input.value or '' if modal.date_input is not None else '',
                modal.weekday_input.values if modal.weekday_input is not None else None,
            )
        except (ValueError, TypeError):
            await self._respond(interaction,
                self._t(guild_id, f'dailyInform_invalid_schedule_{modal.period}'), ephemeral=True,
            )
            return None
        if schedule.kind == 'once' and schedule.once_at(time_min) <= dt.now(KST):
            await self._respond(interaction,
                self._t(guild_id, 'dailyInform_once_past'), ephemeral=True,
            )
            return None

        message = (modal.message_input.value or '').strip()
        if not message:
            await self._respond(interaction,
                await asyncio.to_thread(db_tone.render_validation_error, guild_id, '메세지가 비어있음'),
                ephemeral=True,
            )
            return None
        try:
            db_dailyInform.validate_message(message)
        except db_dailyInform.DailyInformValidationError:
            await self._respond(interaction,
                await asyncio.to_thread(db_tone.render_validation_error, guild_id, '메세지가 너무 긺'),
                ephemeral=True,
            )
            return None

        if modal.mode == 'add':
            if modal.channel_id is None:
                await self._respond(interaction,
                    await asyncio.to_thread(db_tone.render_validation_error, guild_id, '알림 채널이 비어있음'),
                    ephemeral=True,
                )
                return None
            return time_min, message, modal.channel_id, schedule

        if modal.channel_select is None or not modal.channel_select.values:
            await self._respond(interaction,
                await asyncio.to_thread(db_tone.render_validation_error, guild_id, '알림 채널이 비어있음'),
                ephemeral=True,
            )
            return None
        selected_channel = modal.channel_select.values[0]
        if interaction.guild is not None and selected_channel.guild.id != interaction.guild.id:
            await self._respond(interaction,
                await asyncio.to_thread(db_tone.render_validation_error, guild_id, '다른 서버의 채널이 선택됨'),
                ephemeral=True,
            )
            return None
        return time_min, message, selected_channel.id, schedule

    async def _handle_add_modal_submit(
        self,
        interaction: discord.Interaction,
        modal: _DailyInformFormModal,
    ):
        parsed = await self._parse_modal_values(interaction, modal)
        if parsed is None:
            return
        time_min, message, channel_id, schedule = parsed
        try:
            await asyncio.to_thread(db_dailyInform.add_message,
                modal.guild_id,
                time_min,
                channel_id,
                modal.requester_id,
                message,
                schedule=schedule,
            )
        except db_dailyInform.DailyInformValidationError:
            await self._respond(interaction,
                await asyncio.to_thread(db_tone.render_validation_error, modal.guild_id, '메세지가 너무 긺'),
                ephemeral=True,
            )
            return

        await self._respond(interaction,
            self._t(
                modal.guild_id,
                'dailyInform_add_success',
                time=self._format_schedule(modal.guild_id, schedule, time_min),
                message=message,
            ),
            ephemeral=True,
        )

    async def _handle_edit_modal_submit(
        self,
        interaction: discord.Interaction,
        modal: _DailyInformFormModal,
    ):
        if modal.row_id is None:
            await self._respond(interaction,
                self._t(modal.guild_id, 'dailyInform_not_found'),
                ephemeral=True,
            )
            return

        parsed = await self._parse_modal_values(interaction, modal)
        if parsed is None:
            return
        time_min, message, channel_id, schedule = parsed

        row = await asyncio.to_thread(db_dailyInform.get_message_by_id, modal.guild_id, modal.row_id)
        if row is None:
            await self._respond(interaction,
                self._t(modal.guild_id, 'dailyInform_confirm_already_deleted'),
                ephemeral=True,
            )
            return
        if not await self._can_manage_row(interaction.user, row.author):
            owner = await self._author_label(interaction.guild, row.author)
            await self._respond(interaction,
                self._t(
                    modal.guild_id,
                    'dailyInform_perm_denied',
                    owner=owner,
                    verb=self._t(modal.guild_id, 'dailyInform_btn_edit'),
                ),
                ephemeral=True,
            )
            return

        last_editor = 0 if modal.requester_id == row.author else modal.requester_id
        try:
            updated = await asyncio.to_thread(db_dailyInform.update_scheduled_message,
                modal.guild_id, modal.row_id, time_min, channel_id, message,
                schedule=schedule, last_editor=last_editor,
            )
            if not updated:
                await self._respond(interaction,
                    self._t(modal.guild_id, 'dailyInform_confirm_already_deleted'), ephemeral=True,
                )
                return
        except db_dailyInform.DailyInformValidationError:
            await self._respond(interaction,
                await asyncio.to_thread(db_tone.render_validation_error, modal.guild_id, '메세지가 너무 긺'),
                ephemeral=True,
            )
            return

        await self._respond(interaction,
            self._t(
                modal.guild_id,
                'dailyInform_edit_success',
                time=self._format_schedule(modal.guild_id, schedule, time_min),
                channel=self._format_channel_label(modal.guild_id, channel_id),
                message=message,
            ),
            ephemeral=True,
        )

    async def _handle_delete_modal_submit(
        self,
        interaction: discord.Interaction,
        modal: _DailyInformDeleteModal,
    ):
        row = await asyncio.to_thread(db_dailyInform.get_message_by_id, modal.guild_id, modal.row_id)
        if row is None:
            await self._respond(interaction,
                self._t(modal.guild_id, 'dailyInform_confirm_already_deleted'),
                ephemeral=True,
            )
            return
        if not await self._can_manage_row(interaction.user, row.author):
            owner = await self._author_label(interaction.guild, row.author)
            await self._respond(interaction,
                self._t(
                    modal.guild_id,
                    'dailyInform_perm_denied',
                    owner=owner,
                    verb=self._t(modal.guild_id, 'dailyInform_btn_delete'),
                ),
                ephemeral=True,
            )
            return

        await asyncio.to_thread(db_dailyInform.delete_message_by_id, modal.guild_id, modal.row_id)
        await self._respond(interaction,
            self._t(
                modal.guild_id,
                'dailyInform_delete_success',
                message=modal.row_message,
            ),
            ephemeral=True,
        )

    async def _resolve_manage_row_from_option(
        self,
        ctx,
        row_id: str,
        verb: str,
    ) -> db_dailyInform.DailyInformRow | None:
        if not await self._guild_only(ctx):
            await self._respond_missing_guild(ctx)
            return None

        try:
            parsed_id = int(row_id)
        except (TypeError, ValueError):
            await ctx.respond(self._t(ctx.guild.id, 'dailyInform_not_found'), ephemeral=True)
            return None

        return await self._get_manage_target(ctx, parsed_id, verb)

    daily_inform_commands = discord.SlashCommandGroup(
        name='알림',
        description=db_tone.render_default_message('dailyInform_group_desc'),
    )

    @daily_inform_commands.command(
        name='등록',
        description=db_tone.render_default_message('dailyInform_add_desc'),
    )
    async def add_daily_inform(
        self, ctx,
        period: str = discord.Option(
            str,
            name=db_tone.render_default_message('dailyInform_period_option_name'),
            description=db_tone.render_default_message('dailyInform_add_period_desc'),
            choices=_PERIOD_CHOICES,
        ),
    ):
        if not await self._guild_only(ctx):
            await self._respond_missing_guild(ctx)
            return

        await ctx.send_modal(
            _DailyInformFormModal(
                self,
                mode='add',
                guild_id=ctx.guild.id,
                requester_id=ctx.author.id,
                channel_id=ctx.channel.id,
                period=period,
            )
        )

    @daily_inform_commands.command(
        name='조회',
        description=db_tone.render_default_message('dailyInform_list_desc'),
    )
    async def list_daily_inform(
        self,
        ctx,
        page: Annotated[
            int,
            discord.Option(
                int,
                name=db_tone.render_default_message('dailyInform_list_option1_name'),
                description=db_tone.render_default_message('dailyInform_list_option1_desc'),
                min_value=1,
                default=1,
            ),
        ] = 1,
    ):
        if not await self._guild_only(ctx):
            await self._respond_missing_guild(ctx)
            return

        guild_id = ctx.guild.id
        rows = await asyncio.to_thread(db_dailyInform.get_messages_by_guild, guild_id)
        total = len(rows)
        if total == 0:
            await ctx.respond(self._t(guild_id, 'dailyInform_list_empty'), ephemeral=True)
            return

        total_pages = (total + self._ALERTS_PER_PAGE - 1) // self._ALERTS_PER_PAGE
        page = max(1, min(page, total_pages))
        view = None
        if total_pages > 1:
            view = _DailyInformListView(
                self, guild_id=guild_id, rows=rows, page=page, requester_id=ctx.author.id,
            )
        response = await ctx.respond(
            **self._build_list_page(guild_id, rows, page), view=view, ephemeral=True,
        )
        if view is not None:
            view.message = await response.original_response()

    def _build_list_page(self, guild_id, rows, page):
        total = len(rows)
        total_pages = (total + self._ALERTS_PER_PAGE - 1) // self._ALERTS_PER_PAGE
        start = (page - 1) * self._ALERTS_PER_PAGE
        end = min(start + self._ALERTS_PER_PAGE, total)
        paginator = commands.Paginator(prefix=None, suffix=None, max_size=2000)
        paginator.add_line(self._t(
            guild_id, 'dailyInform_list_header', total=total, start=start + 1, end=end,
            page=page, total_pages=total_pages,
        ))
        for index, row in enumerate(rows[start:end], start=start + 1):
            paginator.add_line(self._format_list_line(guild_id, index, row))
        pages = paginator.pages
        if len(pages) == 1:
            return {'content': pages[0], 'embeds': []}
        # Keep long results in the same message so all five entries change together.
        return {'content': None, 'embeds': [discord.Embed(description=text) for text in pages]}

    @daily_inform_commands.command(
        name='수정',
        description=db_tone.render_default_message('dailyInform_edit_desc'),
    )
    async def update_daily_inform(
        self,
        ctx,
        row_id: str = discord.Option(
            str,
            name=db_tone.render_default_message('dailyInform_edit_option_name'),
            description=db_tone.render_default_message('dailyInform_edit_option_desc'),
            autocomplete=_daily_inform_manage_autocomplete,
        ),
        period: str = discord.Option(
            str,
            name=db_tone.render_default_message('dailyInform_period_option_name'),
            description=db_tone.render_default_message('dailyInform_edit_period_desc'),
            choices=_PERIOD_CHOICES, default=None,
        ),
    ):
        if not await self._guild_only(ctx):
            await self._respond_missing_guild(ctx)
            return
        guild_id = ctx.guild.id
        row = await self._resolve_manage_row_from_option(
            ctx,
            row_id,
            self._t(guild_id, 'dailyInform_btn_edit'),
        )
        if row is None:
            return

        await ctx.send_modal(
            _DailyInformFormModal(
                self,
                mode='edit',
                guild_id=guild_id,
                requester_id=ctx.author.id,
                row=row,
                period=period,
            )
        )

    @daily_inform_commands.command(
        name='삭제',
        description=db_tone.render_default_message('dailyInform_delete_desc'),
    )
    async def delete_daily_inform(
        self,
        ctx,
        row_id: str = discord.Option(
            str,
            name=db_tone.render_default_message('dailyInform_delete_option_name'),
            description=db_tone.render_default_message('dailyInform_delete_option_desc'),
            autocomplete=_daily_inform_manage_autocomplete,
        ),
    ):
        if not await self._guild_only(ctx):
            await self._respond_missing_guild(ctx)
            return
        guild_id = ctx.guild.id
        row = await self._resolve_manage_row_from_option(
            ctx,
            row_id,
            self._t(guild_id, 'dailyInform_btn_delete'),
        )
        if row is None:
            return

        await ctx.send_modal(
            _DailyInformDeleteModal(
                self,
                guild_id=guild_id,
                requester_id=ctx.author.id,
                row=row,
            )
        )

    async def _send_message(self, row: db_dailyInform.DailyInformRow) -> bool:
        if not row.message:
            return False
        channel = self.bot.get_channel(row.channel)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(row.channel)
            except discord.Forbidden as exc:
                await self._notify_send_failure(row.guild, row.channel, 'fetch_forbidden', str(exc))
                return False
            except discord.NotFound as exc:
                await self._notify_send_failure(row.guild, row.channel, 'channel_not_found', str(exc))
                return False
            except Exception as exc:
                print(f'dailyInform: channel fetch failed: {exc}')
                return False
        guild = getattr(channel, 'guild', None)
        if guild is None or guild.id != row.guild:
            return False
        try:
            await channel.send(row.message)
            return True
        except discord.Forbidden as exc:
            await self._notify_send_failure(row.guild, row.channel, 'send_forbidden', str(exc))
        except discord.NotFound as exc:
            await self._notify_send_failure(row.guild, row.channel, 'channel_not_found', str(exc))
        except Exception as exc:
            print(f'dailyInform: send failed: {exc}')
        return False

    async def _delivery_candidates(self, query, args, attempt_counts: dict):
        allowed = tuple(
            guild.id for guild in self.bot.guilds
            if self._is_allowed_guild(guild.id)
        )
        if not allowed:
            return
        scanned = 0
        excluded = set()
        while scanned < self._MAX_ATTEMPTS_PER_SOURCE:
            excluded.update(guild for guild, count in attempt_counts.items() if count >= 7)
            try:
                rows = await asyncio.to_thread(
                    query, *args, limit=min(self._QUERY_BATCH_SIZE, self._MAX_ATTEMPTS_PER_SOURCE - scanned),
                    excluded_guilds=tuple(excluded), guild_ids=allowed,
                )
            except Exception as exc:
                print(f'dailyInform: delivery query failed: {exc}')
                return
            if not rows:
                return
            for item in rows:
                scanned += 1
                row = item[0] if isinstance(item, tuple) and not isinstance(item, db_dailyInform.DailyInformRow) else item
                if not self._is_allowed_guild(row.guild):
                    excluded.add(row.guild)
                    continue
                yield item

    async def _send_pending_recurring_messages(self, scope: str, now: dt, send_counts: dict):
        cleanup = self._recurring_pending_cleanup
        for key, row in list(cleanup.items())[:self._MAX_ATTEMPTS_PER_SOURCE]:
            try:
                await asyncio.to_thread(db_dailyInform.finish_recurring_message, scope, row, key[0])
                del cleanup[key]
            except Exception as exc:
                print(f'dailyInform: recurring cleanup failed: {exc}')
        async for row, scheduled_at in self._delivery_candidates(
            db_dailyInform.get_pending_recurring_messages, (scope, now), send_counts,
        ):
            key = (scheduled_at, row.id, row.revision)
            if key in cleanup or not self._is_allowed_guild(row.guild):
                continue
            if send_counts.get(row.guild, 0) >= 7:
                continue
            try:
                if not await asyncio.to_thread(db_dailyInform.claim_recurring_message, scope, row, scheduled_at, now):
                    continue
            except Exception as exc:
                print(f'dailyInform: recurring claim failed: {exc}')
                continue
            send_counts[row.guild] = send_counts.get(row.guild, 0) + 1
            await self._send_message(row)
            # Preserve the existing failure notification behavior for recurring sends.
            cleanup[key] = row
            try:
                await asyncio.to_thread(db_dailyInform.finish_recurring_message, scope, row, scheduled_at)
                del cleanup[key]
            except Exception as exc:
                print(f'dailyInform: recurring cleanup failed: {exc}')

    async def _send_due_once_messages(self, now: dt, send_counts: dict):
        # Keep successful sends in memory until DB cleanup succeeds.
        for key, row in list(self._sent_once_pending_cleanup.items())[:self._MAX_ATTEMPTS_PER_SOURCE]:
            try:
                await asyncio.to_thread(db_dailyInform.delete_sent_once_message, row)
                del self._sent_once_pending_cleanup[key]
            except Exception as exc:
                print(f'dailyInform: once cleanup failed: {exc}')
        async for row in self._delivery_candidates(
            db_dailyInform.get_due_once_messages, (now,), send_counts,
        ):
            key = (row.id, row.revision)
            if key in self._sent_once_pending_cleanup:
                continue
            if not self._is_allowed_guild(row.guild) or send_counts.get(row.guild, 0) >= 7:
                continue
            try:
                if not await asyncio.to_thread(db_dailyInform.claim_once_message, row, now, now + td(minutes=5)):
                    continue
            except Exception as exc:
                print(f'dailyInform: once claim failed: {exc}')
                continue
            send_counts[row.guild] = send_counts.get(row.guild, 0) + 1
            if await self._send_message(row):
                self._sent_once_pending_cleanup[key] = row
                try:
                    await asyncio.to_thread(db_dailyInform.delete_sent_once_message, row)
                    del self._sent_once_pending_cleanup[key]
                except Exception as exc:
                    print(f'dailyInform: once cleanup failed: {exc}')

    def _make_key(self, when: dt):
        minute_of_day = when.hour * 60 + when.minute
        return (when.year, when.month, when.day, minute_of_day)

    def _key_to_dt(self, key):
        year, month, day, minute_of_day = key
        hour = minute_of_day // 60
        minute = minute_of_day % 60
        return dt(year, month, day, hour, minute, tzinfo=tz(td(hours=9)))

    @daily_inform.before_loop
    async def _before_daily_inform(self):
        await self.bot.wait_until_ready()
        await asyncio.to_thread(db_dailyInform.ensure_schema)
        await self._load_scheduler_state()


def setup(bot):
    bot.add_cog(dailyInform(bot))
