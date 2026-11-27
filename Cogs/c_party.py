# coding: utf-8
from __future__ import annotations

import asyncio
import re

import discord
from discord.ext import commands, tasks

from DB import db_recruit, db_setting, db_tone
from Library import (
    lib_cog_scope,
    lib_cog_tone,
    lib_interaction_defer,
    lib_premium,
)

_JOIN_CUSTOM_ID = 'party_join'
_LEAVE_CUSTOM_ID = 'party_leave'
_BTN_JOIN_DEFAULT = db_tone.render_default_message('party_btn_join')
_BTN_LEAVE_DEFAULT = db_tone.render_default_message('party_btn_leave')
_THREAD_CREATE_VALUE = 'create'
_THREAD_SKIP_VALUE = 'skip'
_TITLE_MAX_LEN = 100
_MIN_SLOTS = 2
_MAX_SLOTS = 50
_MIN_DURATION_MIN = 1
_MAX_DURATION_MIN = 24 * 60
_EXPIRY_CHECK_SEC = 30

_HOUR_RE = re.compile(r'(\d+)\s*(?:시간|hour|hours|h)(?![가-힣a-zA-Z])', re.IGNORECASE)
_HOUR_HALF_RE = re.compile(r'(\d+)\s*시간\s*반')
_MINUTE_RE = re.compile(r'(\d+)\s*(?:분|minute|minutes|min|m)(?![가-힣a-zA-Z])', re.IGNORECASE)
_COLON_RE = re.compile(r'^(\d+)\s*:\s*(\d+)$')


def _autocomplete_guild(ctx: discord.AutocompleteContext) -> discord.Guild | None:
    guild = ctx.interaction.guild
    if guild is not None:
        return guild
    guild_id = ctx.interaction.guild_id
    if guild_id is None:
        return None
    return ctx.bot.get_guild(guild_id)


async def _party_host_autocomplete(ctx: discord.AutocompleteContext):
    guild = _autocomplete_guild(ctx)
    if guild is None:
        return []
    rows = db_recruit.list_active_by_host(guild.id, ctx.interaction.user.id)
    current = (ctx.value or '').strip().lower()
    choices: list[discord.OptionChoice] = []
    for row in rows[:25]:
        label = f'{row.title} ({len(row.participant_ids)}/{row.max_slots})'
        if current and current not in label.lower():
            continue
        choices.append(discord.OptionChoice(name=label[:100], value=str(row.id)))
    return choices


def _party_thread_channel_enabled(guild_id: int) -> bool:
    return bool(db_setting.get_setting(guild_id, 'recruit_thread_channel'))


def _format_remaining_duration(
    cog: 'party',
    guild_id: int,
    ends_at: int,
    *,
    now: int | None = None,
) -> str:
    remaining_sec = max(1, ends_at - (now if now is not None else db_recruit.now_sec()))
    total_min = max(1, (remaining_sec + 59) // 60)
    hours, minutes = divmod(total_min, 60)
    parts: list[str] = []
    if hours:
        parts.append(cog._t(guild_id, 'party_duration_part_hour', hours=hours))
    if minutes or not hours:
        parts.append(cog._t(guild_id, 'party_duration_part_minute', minutes=minutes))
    return ' '.join(parts)


def parse_duration_minutes(text: str) -> int | None:
    raw = (text or '').strip()
    if not raw:
        return None
    hours = 0
    minutes = 0
    hour_half_match = _HOUR_HALF_RE.search(raw)
    hour_match = _HOUR_RE.search(raw)
    minute_match = _MINUTE_RE.search(raw)
    if hour_half_match:
        hours = int(hour_half_match.group(1))
        minutes = 30
    elif hour_match:
        hours = int(hour_match.group(1))
    if minute_match:
        minutes = int(minute_match.group(1))
    if not hour_half_match and not hour_match and not minute_match:
        if raw.isdigit():
            minutes = int(raw)
        else:
            colon_match = _COLON_RE.fullmatch(raw)
            if colon_match is None:
                return None
            hours = int(colon_match.group(1))
            minutes = int(colon_match.group(2))
            if minutes >= 60:
                return None
    total = hours * 60 + minutes
    if total < _MIN_DURATION_MIN or total > _MAX_DURATION_MIN:
        return None
    return total


def parse_thread_choice_value(value: str | None) -> bool | None:
    if value == _THREAD_CREATE_VALUE:
        return True
    if value == _THREAD_SKIP_VALUE:
        return False
    return None


class _PartyFormModal(discord.ui.DesignerModal):
    def __init__(
        self,
        cog: 'party',
        *,
        mode: str,
        guild_id: int,
        host_id: int,
        channel_id: int | None = None,
        recruit_id: int | None = None,
        session: db_recruit.RecruitSession | None = None,
    ):
        self.cog = cog
        self.mode = mode
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.host_id = host_id
        self.recruit_id = recruit_id
        self.show_thread_select = _party_thread_channel_enabled(guild_id)
        self.initial_create_thread: bool | None = (
            session.create_thread if session is not None else None
        )

        title_value = ''
        slots_value = ''
        duration_value = ''
        thread_description = cog._t(guild_id, 'party_modal_field_thread_description')
        if session is not None:
            title_value = session.title
            slots_value = str(session.max_slots)
            duration_value = _format_remaining_duration(cog, guild_id, session.ends_at)
            if session.create_thread:
                thread_description = cog._t(
                    guild_id,
                    'party_modal_field_thread_current_create',
                )
            else:
                thread_description = cog._t(
                    guild_id,
                    'party_modal_field_thread_current_skip',
                )

        self.title_input = discord.ui.InputText(
            custom_id='party:recruit:title',
            placeholder=cog._t(guild_id, 'party_modal_field_title_placeholder'),
            required=True,
            max_length=_TITLE_MAX_LEN,
            value=title_value[:_TITLE_MAX_LEN],
        )
        self.slots_input = discord.ui.InputText(
            custom_id='party:recruit:slots',
            placeholder=cog._t(guild_id, 'party_modal_field_slots_placeholder'),
            required=True,
            max_length=3,
            value=slots_value[:3],
        )
        self.duration_input = discord.ui.InputText(
            custom_id='party:recruit:duration',
            placeholder=cog._t(guild_id, 'party_modal_field_duration_placeholder'),
            required=True,
            max_length=32,
            value=duration_value[:32],
        )
        self.thread_select: discord.ui.Select | None = None
        modal_items: list[discord.ui.Item] = [
            discord.ui.Label(
                cog._t(guild_id, 'party_modal_field_title_label'),
                item=self.title_input,
            ),
            discord.ui.Label(
                cog._t(guild_id, 'party_modal_field_slots_label'),
                item=self.slots_input,
            ),
            discord.ui.Label(
                cog._t(guild_id, 'party_modal_field_duration_label'),
                item=self.duration_input,
            ),
        ]
        if self.show_thread_select:
            thread_required = mode != 'edit'
            self.thread_select = discord.ui.Select(
                custom_id='party:recruit:thread',
                placeholder=cog._t(guild_id, 'party_modal_field_thread_placeholder'),
                min_values=1 if thread_required else 0,
                max_values=1,
                required=thread_required,
                options=[
                    discord.SelectOption(
                        label=cog._t(guild_id, 'party_thread_choice_create'),
                        value=_THREAD_CREATE_VALUE,
                    ),
                    discord.SelectOption(
                        label=cog._t(guild_id, 'party_thread_choice_skip'),
                        value=_THREAD_SKIP_VALUE,
                    ),
                ],
            )
            modal_items.append(
                discord.ui.Label(
                    cog._t(guild_id, 'party_modal_field_thread_label'),
                    item=self.thread_select,
                    description=thread_description,
                )
            )

        title_key = (
            'party_modal_title'
            if mode == 'start'
            else 'party_modal_edit_title'
        )
        super().__init__(
            *modal_items,
            title=cog._t(guild_id, title_key),
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    self.guild_id,
                    '명령어 실행자와 모달 제출자가 다름',
                ),
                ephemeral=True,
            )
            return
        if self.mode == 'start':
            await self.cog._handle_start_modal_submit(interaction, self)
            return
        await self.cog._handle_edit_modal_submit(interaction, self)


class _PartyPanelView(discord.ui.View):
    def __init__(self, cog: 'party', guild_id: int | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.join_button.label = (
            cog._t(guild_id, 'party_btn_join') if guild_id is not None else _BTN_JOIN_DEFAULT
        )
        self.leave_button.label = (
            cog._t(guild_id, 'party_btn_leave') if guild_id is not None else _BTN_LEAVE_DEFAULT
        )

    @discord.ui.button(
        label=_BTN_JOIN_DEFAULT,
        style=discord.ButtonStyle.success,
        custom_id=_JOIN_CUSTOM_ID,
    )
    async def join_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog._handle_join(interaction)

    @discord.ui.button(
        label=_BTN_LEAVE_DEFAULT,
        style=discord.ButtonStyle.secondary,
        custom_id=_LEAVE_CUSTOM_ID,
    )
    async def leave_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog._handle_leave(interaction)


class party(lib_cog_tone.ToneAwareCog, commands.Cog):
    party_commands = discord.SlashCommandGroup(
        name='파티',
        description=db_tone.render_default_message('party_group_desc'),
    )

    def __init__(self, bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}
        self._persistent_views_registered = False
        try:
            db_recruit.ensure_schema()
        except Exception as exc:
            print(f'c_party: schema init failed: {exc}')

    def _t(self, guild_id: int, message_key: str, **kwargs) -> str:
        if guild_id:
            extra = lib_cog_scope.render_party_addon_tone(
                self.bot,
                guild_id,
                message_key,
                **kwargs,
            )
            if extra is not None:
                return extra
        return super()._t(guild_id, message_key, **kwargs)

    def _is_recruit_entitled(self, guild_id: int) -> bool:
        return lib_premium.is_recruit_entitled(self.bot, guild_id)

    def _apply_feature_guard(self, guild_id: int) -> tuple[bool, str | None]:
        if not self._is_allowed_guild(guild_id):
            return False, None
        if not self._is_recruit_entitled(guild_id):
            return False, self._t(guild_id, 'party_premium_denied')
        if not lib_cog_scope.is_extension_enabled_for_guild(
            self.bot,
            lib_cog_scope.PARTY_COG_MODULE,
            guild_id,
        ):
            return False, self._t(guild_id, 'party_premium_denied')
        return True, None

    def cog_unload(self):
        if self.recruit_expiry_check.is_running():
            self.recruit_expiry_check.cancel()

    def _lock_for(self, recruit_id: int) -> asyncio.Lock:
        lock = self._locks.get(recruit_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[recruit_id] = lock
        return lock

    def _panel_view_for(self, guild_id: int) -> _PartyPanelView:
        return _PartyPanelView(self, guild_id=guild_id)

    def _register_persistent_views(self) -> None:
        if self._persistent_views_registered:
            return
        self.bot.add_view(_PartyPanelView(self))
        self._persistent_views_registered = True

    def _participant_lines(self, guild_id: int, session: db_recruit.RecruitSession) -> str:
        lines: list[str] = []
        for index, user_id in enumerate(session.participant_ids, start=1):
            suffix = ''
            if user_id == session.host_id:
                suffix = self._t(guild_id, 'party_host_suffix')
            lines.append(
                self._t(
                    guild_id,
                    'party_participant_line',
                    index=index,
                    member_id=user_id,
                    suffix=suffix,
                )
            )
        if not lines:
            return self._t(guild_id, 'party_participant_empty')
        return '\n'.join(lines)

    def _build_embed(
        self,
        guild_id: int,
        session: db_recruit.RecruitSession,
        *,
        ended: bool = False,
    ) -> discord.Embed:
        count = len(session.participant_ids)
        if ended or session.status == 'ended':
            description = self._t(
                guild_id,
                'party_embed_desc_ended',
                current=count,
                max_slots=session.max_slots,
            )
        else:
            description = self._t(
                guild_id,
                'party_embed_desc_active',
                current=count,
                max_slots=session.max_slots,
            )
        embed = discord.Embed(
            title=session.title,
            description=description,
            color=db_setting.get_embed_color(guild_id),
        )
        embed.add_field(
            name=self._t(guild_id, 'party_field_participants'),
            value=self._participant_lines(guild_id, session),
            inline=False,
        )
        embed.set_footer(text=db_tone.render_embed_footer(guild_id, self.bot.ame_ver))
        return embed

    async def _resolve_post_channel(
        self,
        guild: discord.Guild,
        channel_id: int,
    ) -> discord.TextChannel | discord.Thread | None:
        channel = guild.get_channel(channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            return channel
        try:
            fetched = await guild.fetch_channel(channel_id)
        except Exception:
            return None
        if isinstance(fetched, (discord.TextChannel, discord.Thread)):
            return fetched
        return None

    async def _create_recruit_post(
        self,
        interaction: discord.Interaction,
        *,
        guild_id: int,
        channel_id: int,
        host_id: int,
        title: str,
        max_members: int,
        duration_min: int,
        create_thread: bool,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return
        if not await lib_interaction_defer.defer_component(interaction, ephemeral=True):
            return

        channel = await self._resolve_post_channel(interaction.guild, channel_id)
        if channel is None:
            await interaction.followup.send(
                self._t(guild_id, 'party_channel_invalid'),
                ephemeral=True,
            )
            return

        ends_at = db_recruit.now_sec() + duration_min * 60
        preview = db_recruit.RecruitSession(
            id=0,
            guild=guild_id,
            host_id=host_id,
            channel_id=channel_id,
            message_id=0,
            title=title,
            max_slots=max_members,
            ends_at=ends_at,
            create_thread=create_thread,
            status='active',
            thread_id=None,
            created_at=db_recruit.now_sec(),
            participant_ids=(host_id,),
        )
        message = await channel.send(
            embed=self._build_embed(guild_id, preview),
            view=self._panel_view_for(guild_id),
        )
        try:
            session = db_recruit.create_recruit(
                guild=guild_id,
                host_id=host_id,
                channel_id=channel_id,
                message_id=message.id,
                title=title,
                max_slots=max_members,
                ends_at=ends_at,
                create_thread=create_thread,
            )
        except Exception:
            try:
                await message.delete()
            except Exception:
                pass
            await interaction.followup.send(
                self._t(guild_id, 'party_start_failed'),
                ephemeral=True,
            )
            return
        try:
            await message.edit(
                embed=self._build_embed(guild_id, session),
                view=self._panel_view_for(guild_id),
            )
        except Exception:
            pass
        await interaction.followup.send(
            self._t(guild_id, 'party_start_success', title=title),
            ephemeral=True,
        )

    async def _parse_form_modal_values(
        self,
        interaction: discord.Interaction,
        modal: _PartyFormModal,
    ) -> tuple[str, int, int, bool] | None:
        guild_id = modal.guild_id
        cleaned_title = (modal.title_input.value or '').strip()
        if not cleaned_title:
            await interaction.response.send_message(
                db_tone.render_validation_error(guild_id, '제목이 비어있음'),
                ephemeral=True,
            )
            return None

        slots_raw = (modal.slots_input.value or '').strip()
        try:
            max_members = int(slots_raw)
        except (TypeError, ValueError):
            max_members = -1
        if not (_MIN_SLOTS <= max_members <= _MAX_SLOTS):
            await interaction.response.send_message(
                self._t(
                    guild_id,
                    'party_invalid_slots',
                    min_slots=_MIN_SLOTS,
                    max_slots=_MAX_SLOTS,
                ),
                ephemeral=True,
            )
            return None

        duration_min = parse_duration_minutes(modal.duration_input.value or '')
        if duration_min is None:
            await interaction.response.send_message(
                self._t(guild_id, 'party_invalid_duration'),
                ephemeral=True,
            )
            return None

        if modal.show_thread_select and modal.thread_select is not None:
            selected_value = (
                modal.thread_select.values[0] if modal.thread_select.values else None
            )
            thread_choice = parse_thread_choice_value(selected_value)
            if thread_choice is None and modal.mode == 'edit' and modal.initial_create_thread is not None:
                thread_choice = modal.initial_create_thread
            if thread_choice is None:
                await interaction.response.send_message(
                    db_tone.render_validation_error(guild_id, '비공개 스레드 옵션이 유효하지 않음'),
                    ephemeral=True,
                )
                return None
            if thread_choice and not _party_thread_channel_enabled(guild_id):
                await interaction.response.send_message(
                    self._t(guild_id, 'party_thread_channel_not_set'),
                    ephemeral=True,
                )
                return None
        else:
            thread_choice = False

        return cleaned_title, max_members, duration_min, thread_choice

    async def _handle_start_modal_submit(self, interaction: discord.Interaction, modal: _PartyFormModal) -> None:
        parsed = await self._parse_form_modal_values(interaction, modal)
        if parsed is None:
            return
        cleaned_title, max_members, duration_min, thread_choice = parsed
        if modal.channel_id is None:
            await interaction.response.send_message(
                self._t(modal.guild_id, 'party_channel_invalid'),
                ephemeral=True,
            )
            return
        await self._create_recruit_post(
            interaction,
            guild_id=modal.guild_id,
            channel_id=modal.channel_id,
            host_id=modal.host_id,
            title=cleaned_title,
            max_members=max_members,
            duration_min=duration_min,
            create_thread=thread_choice,
        )

    async def _handle_edit_modal_submit(self, interaction: discord.Interaction, modal: _PartyFormModal) -> None:
        if modal.recruit_id is None or interaction.guild is None:
            await interaction.response.send_message(
                self._t(modal.guild_id, 'party_not_found'),
                ephemeral=True,
            )
            return
        parsed = await self._parse_form_modal_values(interaction, modal)
        if parsed is None:
            return
        cleaned_title, max_members, duration_min, thread_choice = parsed

        session = db_recruit.get_by_id(modal.recruit_id)
        if (
            session is None
            or session.guild != modal.guild_id
            or session.host_id != modal.host_id
            or session.status != 'active'
        ):
            await interaction.response.send_message(
                self._t(modal.guild_id, 'party_not_found'),
                ephemeral=True,
            )
            return
        if max_members < len(session.participant_ids):
            await interaction.response.send_message(
                self._t(
                    modal.guild_id,
                    'party_slots_below_participants',
                    current=len(session.participant_ids),
                ),
                ephemeral=True,
            )
            return
        if not await lib_interaction_defer.defer_component(interaction, ephemeral=True):
            return

        async with self._lock_for(modal.recruit_id):
            session = db_recruit.get_by_id(modal.recruit_id)
            if (
                session is None
                or session.guild != modal.guild_id
                or session.host_id != modal.host_id
                or session.status != 'active'
            ):
                await interaction.followup.send(self._t(modal.guild_id, 'party_not_found'), ephemeral=True)
                return
            if max_members < len(session.participant_ids):
                await interaction.followup.send(
                    self._t(
                        modal.guild_id,
                        'party_slots_below_participants',
                        current=len(session.participant_ids),
                    ),
                    ephemeral=True,
                )
                return
            ends_at = db_recruit.now_sec() + duration_min * 60
            updated = db_recruit.update_recruit(
                session.id,
                title=cleaned_title,
                max_slots=max_members,
                ends_at=ends_at,
                create_thread=thread_choice,
            )
            if updated is None:
                await interaction.followup.send(self._t(modal.guild_id, 'party_edit_failed'), ephemeral=True)
                return

        channel = await self._resolve_post_channel(interaction.guild, updated.channel_id)
        if channel is not None:
            try:
                message = await channel.fetch_message(updated.message_id)
                await message.edit(
                    embed=self._build_embed(updated.guild, updated),
                    view=self._panel_view_for(updated.guild),
                )
            except Exception:
                pass
        await interaction.followup.send(
            self._t(modal.guild_id, 'party_edit_success', title=cleaned_title),
            ephemeral=True,
        )
        if len(updated.participant_ids) >= updated.max_slots:
            await self._finalize_recruit(updated, guild=interaction.guild)

    async def _resolve_member(self, guild: discord.Guild, user_id: int) -> discord.Member | None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except Exception:
            return None

    async def _create_private_thread(
        self,
        guild: discord.Guild,
        session: db_recruit.RecruitSession,
    ) -> discord.Thread | None:
        """Create a private thread in the configured party channel and add participants.

        Thread chat is not granted per member. Discord threads inherit access from the
        parent channel — roles that should participate need view_channel,
        read_message_history, and send_messages_in_threads.
        """
        channel_id = db_setting.get_setting(guild.id, 'recruit_thread_channel')
        if not channel_id:
            return None
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            try:
                fetched = await guild.fetch_channel(int(channel_id))
            except Exception:
                return None
            if not isinstance(fetched, discord.TextChannel):
                return None
            channel = fetched
        me = guild.me
        if me is None or not channel.permissions_for(me).create_private_threads:
            return None
        thread_name = session.title[:100] or self._t(
            guild.id,
            'party_thread_name_fallback',
            recruit_id=session.id,
        )
        try:
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=1440,
            )
        except Exception:
            return None
        try:
            await thread.send(
                self._t(
                    guild.id,
                    'party_thread_open',
                    title=session.title,
                    host_id=session.host_id,
                    count=len(session.participant_ids),
                    max_slots=session.max_slots,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            pass
        for user_id in session.participant_ids:
            member = await self._resolve_member(guild, user_id)
            if member is None:
                continue
            try:
                await thread.add_user(member)
            except Exception:
                pass
        return thread

    async def _finalize_recruit(
        self,
        session: db_recruit.RecruitSession,
        *,
        guild: discord.Guild | None = None,
    ) -> db_recruit.RecruitSession | None:
        recruit_id = session.id
        result: db_recruit.RecruitSession | None = None
        async with self._lock_for(recruit_id):
            latest = db_recruit.get_by_id(recruit_id)
            if latest is None or latest.status != 'active':
                result = latest
            else:
                thread_id: int | None = None
                if latest.create_thread and guild is not None:
                    thread = await self._create_private_thread(guild, latest)
                    if thread is not None:
                        thread_id = thread.id

                ended = db_recruit.mark_ended(latest.id, thread_id=thread_id)
                if ended is None:
                    result = latest
                else:
                    channel: discord.abc.Messageable | None = None
                    if guild is not None:
                        channel_obj = guild.get_channel(ended.channel_id)
                        if isinstance(channel_obj, (discord.TextChannel, discord.Thread)):
                            channel = channel_obj
                    if channel is None:
                        try:
                            fetched_channel = await self.bot.fetch_channel(ended.channel_id)
                            if isinstance(fetched_channel, (discord.TextChannel, discord.Thread)):
                                channel = fetched_channel
                        except Exception:
                            channel = None
                    if channel is not None:
                        try:
                            message = await channel.fetch_message(ended.message_id)
                        except Exception:
                            message = None
                        if message is not None:
                            try:
                                await message.edit(
                                    embed=self._build_embed(ended.guild, ended, ended=True),
                                    view=None,
                                )
                            except Exception:
                                pass
                    result = ended

        self._locks.pop(recruit_id, None)
        return result

    async def _refresh_message(self, interaction: discord.Interaction, session: db_recruit.RecruitSession) -> None:
        if interaction.message is None:
            return
        try:
            await interaction.message.edit(
                embed=self._build_embed(session.guild, session),
                view=self._panel_view_for(session.guild),
            )
        except (discord.NotFound, discord.HTTPException):
            pass

    async def _handle_join(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message(db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'), ephemeral=True)
            return
        guild_id = interaction.guild.id
        ok, error = self._apply_feature_guard(guild_id)
        if not ok:
            if error:
                await interaction.response.send_message(error, ephemeral=True)
            return

        session = db_recruit.get_by_message_id(interaction.message.id)
        if session is None or session.guild != guild_id:
            await interaction.response.send_message(self._t(guild_id, 'party_not_found'), ephemeral=True)
            return
        if session.status != 'active':
            await interaction.response.send_message(self._t(guild_id, 'party_already_ended'), ephemeral=True)
            return
        user_id = interaction.user.id
        if user_id in session.participant_ids:
            await interaction.response.send_message(self._t(guild_id, 'party_already_joined'), ephemeral=True)
            return
        if len(session.participant_ids) >= session.max_slots:
            await interaction.response.send_message(self._t(guild_id, 'party_full'), ephemeral=True)
            return
        if not await lib_interaction_defer.defer_component(interaction, ephemeral=False):
            return

        async with self._lock_for(session.id):
            latest = db_recruit.get_by_id(session.id)
            if latest is None or latest.status != 'active':
                await interaction.followup.send(self._t(guild_id, 'party_already_ended'), ephemeral=True)
                return
            if user_id in latest.participant_ids:
                await interaction.followup.send(self._t(guild_id, 'party_already_joined'), ephemeral=True)
                return
            if len(latest.participant_ids) >= latest.max_slots:
                await interaction.followup.send(self._t(guild_id, 'party_full'), ephemeral=True)
                return
            updated = db_recruit.add_participant(latest.id, user_id)
            if updated is None:
                await interaction.followup.send(self._t(guild_id, 'party_not_found'), ephemeral=True)
                return
            if updated is False:
                await interaction.followup.send(self._t(guild_id, 'party_full'), ephemeral=True)
                return

        await self._refresh_message(interaction, updated)
        await interaction.followup.send(self._t(guild_id, 'party_join_success'), ephemeral=True)
        if len(updated.participant_ids) >= updated.max_slots:
            await self._finalize_recruit(updated, guild=interaction.guild)

    async def _handle_leave(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.message is None:
            await interaction.response.send_message(db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'), ephemeral=True)
            return
        guild_id = interaction.guild.id
        ok, error = self._apply_feature_guard(guild_id)
        if not ok:
            if error:
                await interaction.response.send_message(error, ephemeral=True)
            return

        session = db_recruit.get_by_message_id(interaction.message.id)
        if session is None or session.guild != guild_id:
            await interaction.response.send_message(self._t(guild_id, 'party_not_found'), ephemeral=True)
            return
        if session.status != 'active':
            await interaction.response.send_message(self._t(guild_id, 'party_already_ended'), ephemeral=True)
            return
        user_id = interaction.user.id
        if user_id == session.host_id:
            await interaction.response.send_message(self._t(guild_id, 'party_host_cannot_leave'), ephemeral=True)
            return
        if user_id not in session.participant_ids:
            await interaction.response.send_message(self._t(guild_id, 'party_not_joined'), ephemeral=True)
            return
        if not await lib_interaction_defer.defer_component(interaction, ephemeral=False):
            return

        async with self._lock_for(session.id):
            updated = db_recruit.remove_participant(session.id, user_id)
            if updated is None:
                await interaction.followup.send(self._t(guild_id, 'party_not_found'), ephemeral=True)
                return

        await self._refresh_message(interaction, updated)
        await interaction.followup.send(self._t(guild_id, 'party_leave_success'), ephemeral=True)

    @party_commands.command(
        name='모집',
        description=db_tone.render_default_message('party_recruit_desc'),
    )
    async def start_recruit(self, ctx: discord.ApplicationContext):
        if ctx.guild is None:
            await ctx.respond(db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'), ephemeral=True)
            return
        guild_id = ctx.guild.id
        ok, error = self._apply_feature_guard(guild_id)
        if not ok:
            if error:
                await ctx.respond(error, ephemeral=True)
            return
        if not isinstance(ctx.channel, (discord.TextChannel, discord.Thread)):
            await ctx.respond(self._t(guild_id, 'party_channel_invalid'), ephemeral=True)
            return
        await ctx.send_modal(
            _PartyFormModal(
                self,
                mode='start',
                guild_id=guild_id,
                channel_id=ctx.channel.id,
                host_id=ctx.author.id,
            )
        )

    @party_commands.command(
        name='수정',
        description=db_tone.render_default_message('party_edit_desc'),
    )
    async def edit_recruit(
        self,
        ctx: discord.ApplicationContext,
        recruit_id: str = discord.Option(
            str,
            name=db_tone.render_default_message('party_edit_option_name'),
            description=db_tone.render_default_message('party_edit_option_desc'),
            autocomplete=_party_host_autocomplete,
        ),
    ):
        if ctx.guild is None:
            await ctx.respond(db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'), ephemeral=True)
            return
        guild_id = ctx.guild.id
        ok, error = self._apply_feature_guard(guild_id)
        if not ok:
            if error:
                await ctx.respond(error, ephemeral=True)
            return
        try:
            parsed_id = int(recruit_id)
        except (TypeError, ValueError):
            await ctx.respond(self._t(guild_id, 'party_not_found'), ephemeral=True)
            return
        session = db_recruit.get_by_id(parsed_id)
        if (
            session is None
            or session.guild != guild_id
            or session.host_id != ctx.author.id
            or session.status != 'active'
        ):
            await ctx.respond(self._t(guild_id, 'party_not_found'), ephemeral=True)
            return
        await ctx.send_modal(
            _PartyFormModal(
                self,
                mode='edit',
                guild_id=guild_id,
                host_id=ctx.author.id,
                recruit_id=session.id,
                session=session,
            )
        )

    @party_commands.command(
        name='모집종료',
        description=db_tone.render_default_message('party_end_desc'),
    )
    async def end_recruit(
        self,
        ctx: discord.ApplicationContext,
        recruit_id: str = discord.Option(
            str,
            name=db_tone.render_default_message('party_end_option_name'),
            description=db_tone.render_default_message('party_end_option_desc'),
            autocomplete=_party_host_autocomplete,
        ),
    ):
        if ctx.guild is None:
            await ctx.respond(db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'), ephemeral=True)
            return
        guild_id = ctx.guild.id
        ok, error = self._apply_feature_guard(guild_id)
        if not ok:
            if error:
                await ctx.respond(error, ephemeral=True)
            return
        try:
            parsed_id = int(recruit_id)
        except (TypeError, ValueError):
            await ctx.respond(self._t(guild_id, 'party_not_found'), ephemeral=True)
            return
        session = db_recruit.get_by_id(parsed_id)
        if (
            session is None
            or session.guild != guild_id
            or session.host_id != ctx.author.id
            or session.status != 'active'
        ):
            await ctx.respond(self._t(guild_id, 'party_not_found'), ephemeral=True)
            return
        if not await lib_interaction_defer.defer_slash(ctx, ephemeral=True):
            return
        ended = await self._finalize_recruit(session, guild=ctx.guild)
        if ended is None or ended.status != 'ended':
            await ctx.followup.send(self._t(guild_id, 'party_end_failed'), ephemeral=True)
            return
        await ctx.followup.send(
            self._t(
                guild_id,
                'party_end_success',
                title=ended.title,
                current=len(ended.participant_ids),
                max_slots=ended.max_slots,
            ),
            ephemeral=True,
        )

    @tasks.loop(seconds=_EXPIRY_CHECK_SEC)
    async def recruit_expiry_check(self):
        expired_rows = db_recruit.list_active_expired()
        for session in expired_rows:
            guild = self.bot.get_guild(session.guild)
            if guild is None:
                try:
                    guild = await self.bot.fetch_guild(session.guild)
                except Exception:
                    guild = None
            await self._finalize_recruit(session, guild=guild)

    @recruit_expiry_check.before_loop
    async def _before_recruit_expiry_check(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        self._register_persistent_views()
        if not self.recruit_expiry_check.is_running():
            self.recruit_expiry_check.start()


def setup(bot):
    bot.add_cog(party(bot))
