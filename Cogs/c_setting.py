# coding: utf-8
from typing import Annotated, Awaitable, Callable, Literal, NamedTuple

import discord
from discord.ext import commands

from DB import db_setting, db_tone
from Library import (
    lib_autocomplete,
    lib_bot_admin,
    lib_channel_check,
    lib_embed_fields,
    lib_interaction_defer,
    lib_cog_scope,
    lib_premium,
    lib_setting_registry,
)


SettingKind = Literal['bool', 'channel', 'role', 'color', 'profile', 'text']
SettingCategory = Literal['basic', 'exp', 'verify', 'party']

_CATEGORY_TONE_KEYS: dict[str, str] = {
    'basic': 'setting_category_basic',
    'exp': 'setting_category_exp',
    'verify': 'setting_category_verify',
    'party': 'setting_category_party',
    'addon': 'setting_category_addon',
}

_BTN_BACK_TO_LIST = db_tone.render_default_message('setting_btn_back_to_list')
_BTN_REFRESH = db_tone.render_default_message('setting_btn_refresh')
_BTN_CLEAR = db_tone.render_default_message('setting_btn_clear')
_BTN_CHANGE = db_tone.render_default_message('setting_btn_change')
_BTN_ENABLE = db_tone.render_default_message('setting_btn_enable')
_BTN_DISABLE = db_tone.render_default_message('setting_btn_disable')
_SELECT_ITEM_PLACEHOLDER = db_tone.render_default_message('setting_select_item_placeholder')
_CHANNEL_PLACEHOLDER = db_tone.render_default_message('setting_channel_placeholder')
_ROLE_PLACEHOLDER = db_tone.render_default_message('setting_role_placeholder')
_VERIFY_SELECT_PLACEHOLDER = db_tone.render_default_message('setting_verify_select_question_placeholder')
_VERIFY_BTN_ADD = db_tone.render_default_message('setting_verify_btn_add')
_VERIFY_BTN_BACK = db_tone.render_default_message('setting_verify_btn_back')
_VERIFY_BTN_EDIT = db_tone.render_default_message('setting_verify_btn_edit')
_VERIFY_BTN_MOVE = db_tone.render_default_message('setting_verify_btn_move')
_VERIFY_BTN_DELETE = db_tone.render_default_message('setting_verify_btn_delete')

_SETTING_UI_UPDATE_FAILED = (
    '설정 화면을 갱신하지 못했어요. `/설정` 명령을 다시 실행해 주세요.'
)


async def _defer_setting_interaction(interaction: discord.Interaction) -> bool:
    return await lib_interaction_defer.defer_component(interaction, ephemeral=True)


async def _refresh_setting_message(
    interaction: discord.Interaction,
    *,
    content: str | None,
    embed_builder: Callable[[], Awaitable[discord.Embed]],
    view_builder: Callable[[], discord.ui.View | None],
) -> None:
    try:
        embed = await embed_builder()
        view = view_builder()
        await interaction.edit_original_response(
            content=content,
            embed=embed,
            view=view,
        )
    except discord.HTTPException:
        try:
            await interaction.followup.send(_SETTING_UI_UPDATE_FAILED, ephemeral=True)
        except discord.HTTPException:
            pass


async def _edit_setting_interaction(
    interaction: discord.Interaction,
    *,
    content: str | None,
    embed_builder: Callable[[], Awaitable[discord.Embed]],
    view_builder: Callable[[], discord.ui.View | None],
) -> None:
    if not await _defer_setting_interaction(interaction):
        return
    await _refresh_setting_message(
        interaction,
        content=content,
        embed_builder=embed_builder,
        view_builder=view_builder,
    )


def _profile_select_options() -> list[discord.SelectOption]:
    stems = sorted(
        db_tone.PROFILE_TEMPLATES.keys(),
        key=db_tone.get_profile_title,
    )
    return [
        discord.SelectOption(label=db_tone.get_profile_title(stem), value=stem)
        for stem in stems
    ]


class _SettingSpec(NamedTuple):
    kind: SettingKind
    clearable: bool = False


_SETTING_SPECS: dict[str, _SettingSpec] = {
    'exp_enable': _SettingSpec(kind='bool'),
    'exp_channel': _SettingSpec(kind='channel', clearable=True),
    'exp_role': _SettingSpec(kind='role', clearable=True),
    'bot_admin_role': _SettingSpec(kind='role', clearable=True),
    'bot_log_channel': _SettingSpec(kind='channel'),
    'embed_color': _SettingSpec(kind='color', clearable=True),
    'tone_profile': _SettingSpec(kind='profile'),
    'recruit_thread_channel': _SettingSpec(kind='channel', clearable=True),
    'verify_enable': _SettingSpec(kind='bool'),
    'verify_questions': _SettingSpec(kind='text'),
    'verify_panel_channel': _SettingSpec(kind='channel'),
    'verify_log_channel': _SettingSpec(kind='channel'),
    'verify_role': _SettingSpec(kind='role'),
    'verify_repass_enable': _SettingSpec(kind='bool'),
    'verify_auto_reject_wrong': _SettingSpec(kind='bool'),
}

_SETTING_ORDER_BASIC: tuple[str, ...] = (
    'bot_admin_role',
    'bot_log_channel',
    'embed_color',
    'tone_profile',
)
_SETTING_ORDER_EXP: tuple[str, ...] = (
    'exp_enable',
    'exp_channel',
    'exp_role',
)
_SETTING_ORDER_VERIFY: tuple[str, ...] = (
    'verify_enable',
    'verify_questions',
    'verify_panel_channel',
    'verify_log_channel',
    'verify_role',
    'verify_repass_enable',
    'verify_auto_reject_wrong',
)
_SETTING_ORDER_PARTY: tuple[str, ...] = (
    'recruit_thread_channel',
)
_SETTING_CATEGORY_KEYS: dict[str, tuple[str, ...]] = {
    'basic': _SETTING_ORDER_BASIC,
    'exp': _SETTING_ORDER_EXP,
    'verify': _SETTING_ORDER_VERIFY,
    'party': _SETTING_ORDER_PARTY,
}


def _setting_spec(item_key: str) -> _SettingSpec | None:
    spec = _SETTING_SPECS.get(item_key)
    if spec is not None:
        return spec
    item = lib_setting_registry.get_item(item_key)
    if item is None:
        return None
    return _SettingSpec(kind=item.kind, clearable=item.clearable)


def _get_setting_value(guild_id: int, item_key: str):
    item = lib_setting_registry.get_item(item_key)
    if item is not None and item.get is not None:
        return item.get(guild_id)
    return db_setting.get_setting(guild_id, item_key)


def _update_setting_value(guild_id: int, item_key: str, value) -> None:
    item = lib_setting_registry.get_item(item_key)
    if item is not None and item.set is not None:
        item.set(guild_id, value)
        return
    db_setting.update_setting(guild_id, item_key, value)


class _SettingBaseView(discord.ui.View):
    def __init__(
        self,
        cog: 'setting',
        requester_id: int,
        category: str,
        item_key: str | None = None,
    ):
        super().__init__(timeout=600)
        self.cog = cog
        self.requester_id = requester_id
        self.category = category
        self.item_key = item_key

    async def on_timeout(self) -> None:
        self.disable_all_items()
        target = self.parent or self.message
        if target is None:
            return
        try:
            await target.edit(
                content=self.cog._t('setting_view_expired'),
                view=self,
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def _check_requester(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            db_tone.render_validation_error(
                interaction.guild.id if interaction.guild else 0,
                '명령어 실행자 이외의 사람이 조작',
            ),
            ephemeral=True,
        )
        return False

    async def _show_dashboard(self, interaction: discord.Interaction, notice: str | None = None):
        guild = interaction.guild
        category = self.category
        requester_id = self.requester_id
        cog = self.cog

        def build_dashboard_view() -> _SettingDashboardView:
            dashboard_view = _SettingDashboardView(cog, requester_id, category)
            cog._configure_dashboard_view(dashboard_view, guild, category)
            return dashboard_view

        await _edit_setting_interaction(
            interaction,
            content=cog._notice_content(notice),
            embed_builder=lambda: cog._build_status_embed(guild, category),
            view_builder=build_dashboard_view,
        )

    async def _show_verify_questions(
        self,
        interaction: discord.Interaction,
        notice: str | None = None,
        *,
        already_deferred: bool = False,
    ):
        guild = interaction.guild
        category = self.category
        requester_id = self.requester_id
        cog = self.cog
        content = cog._notice_content(
            notice or cog._t('setting_verify_questions_notice'),
        )

        def build_verify_questions_view() -> _VerifyQuestionsEditView:
            return _VerifyQuestionsEditView(
                cog,
                requester_id,
                'verify_questions',
                category,
                guild=guild,
            )

        if already_deferred:
            await _refresh_setting_message(
                interaction,
                content=content,
                embed_builder=lambda: cog._build_item_embed(guild, 'verify_questions', category),
                view_builder=build_verify_questions_view,
            )
            return

        await _edit_setting_interaction(
            interaction,
            content=content,
            embed_builder=lambda: cog._build_item_embed(guild, 'verify_questions', category),
            view_builder=build_verify_questions_view,
        )

    async def _show_item(
        self,
        interaction: discord.Interaction,
        item_key: str,
        notice: str | None = None,
    ):
        if not await _defer_setting_interaction(interaction):
            return
        if item_key == 'verify_questions':
            await self._show_verify_questions(interaction, notice, already_deferred=True)
            return

        guild = interaction.guild
        category = self.category
        requester_id = self.requester_id
        cog = self.cog

        await _refresh_setting_message(
            interaction,
            content=cog._notice_content(notice),
            embed_builder=lambda: cog._build_item_embed(guild, item_key, category),
            view_builder=lambda: cog._build_item_view(
                guild, requester_id, item_key, category,
            ),
        )


def _create_item_view(
    cog: 'setting',
    requester_id: int,
    item_key: str,
    category: str,
) -> discord.ui.View:
    spec = _setting_spec(item_key)
    if spec is None:
        return _SettingItemView(cog, requester_id, item_key, category)
    view_by_kind = {
        'bool': _SettingBoolEditView,
        'channel': _SettingChannelEditView,
        'role': _SettingRoleEditView,
        'profile': _SettingProfileEditView,
    }
    view_cls = view_by_kind.get(spec.kind, _SettingItemView)
    return view_cls(cog, requester_id, item_key, category)


class _SettingItemFooterView(_SettingBaseView):
    def __init__(self, cog: 'setting', requester_id: int, item_key: str, category: str):
        super().__init__(cog, requester_id, category, item_key=item_key)
        spec = _setting_spec(item_key)
        self.clear_button.disabled = not (spec and spec.clearable)
        self.item_select = discord.ui.Select(
            select_type=discord.ComponentType.string_select,
            placeholder=_SELECT_ITEM_PLACEHOLDER,
            options=[],
            min_values=1,
            max_values=1,
            row=2,
        )
        self.item_select.callback = self._switch_item
        self.add_item(self.item_select)

    def _apply_clear_label(self) -> None:
        spec = _setting_spec(self.item_key)
        if spec and spec.clearable:
            self.clear_button.label = self.cog._spec_clear_label(self.item_key)
        else:
            self.clear_button.label = _BTN_CLEAR

    async def _switch_item(self, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not self.item_select.values:
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    interaction.guild.id if interaction.guild else 0,
                    '설정 항목이 비어있음',
                ),
                ephemeral=True,
            )
            return
        item_key = self.item_select.values[0]
        if item_key not in self.cog._visible_setting_keys(interaction.guild, self.category):
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    interaction.guild.id if interaction.guild else 0,
                    '이 서버에서 사용할 수 없는 항목임',
                ),
                ephemeral=True,
            )
            return
        await self._show_item(interaction, item_key)

    @discord.ui.button(label=_BTN_BACK_TO_LIST, style=discord.ButtonStyle.secondary, row=1)
    async def back_to_dashboard_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        await self._show_dashboard(interaction)

    @discord.ui.button(label=_BTN_REFRESH, style=discord.ButtonStyle.secondary, row=1)
    async def refresh_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        await self._show_item(
            interaction,
            self.item_key,
            notice=f'✅ {self.cog._t("setting_refresh_done")}',
        )

    @discord.ui.button(label=_BTN_CLEAR, style=discord.ButtonStyle.secondary, row=1)
    async def clear_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        ok, message = self.cog._save_setting_value(interaction.guild, self.item_key, None)
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        await self._show_item(interaction, self.item_key, notice=notice)


class _SettingDashboardView(_SettingBaseView):
    def __init__(self, cog: 'setting', requester_id: int, category: str):
        super().__init__(cog, requester_id, category, item_key=None)
        self.item_select = discord.ui.Select(
            select_type=discord.ComponentType.string_select,
            placeholder=_SELECT_ITEM_PLACEHOLDER,
            options=[],
            min_values=1,
            max_values=1,
            row=0,
        )
        self.item_select.callback = self.select_item
        self.add_item(self.item_select)

    async def select_item(self, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not self.item_select.values:
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    interaction.guild.id if interaction.guild else 0,
                    '설정 항목이 비어있음',
                ),
                ephemeral=True,
            )
            return
        item_key = self.item_select.values[0]
        if item_key not in self.cog._visible_setting_keys(interaction.guild, self.category):
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    interaction.guild.id if interaction.guild else 0,
                    '이 서버에서 사용할 수 없는 항목임',
                ),
                ephemeral=True,
            )
            return
        await self._show_item(interaction, item_key)

    @discord.ui.button(label=_BTN_REFRESH, style=discord.ButtonStyle.secondary, row=1)
    async def refresh_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        await self._show_dashboard(
            interaction,
            notice=f'✅ {self.cog._t("setting_refresh_done")}',
        )


class _SettingItemView(_SettingItemFooterView):
    @discord.ui.button(label=_BTN_CHANGE, style=discord.ButtonStyle.primary, row=0)
    async def change_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        guild_id = interaction.guild.id
        spec = _setting_spec(self.item_key)
        if spec is not None and spec.kind == 'color':
            await interaction.response.send_modal(
                _EmbedColorModal(self.cog, self.requester_id, self.category),
            )
            return
        if spec is not None and spec.kind == 'text':
            await interaction.response.send_modal(
                _TextSettingModal(
                    self.cog,
                    self.requester_id,
                    self.item_key,
                    self.category,
                    current_value=_get_setting_value(guild_id, self.item_key),
                    title=self.cog._t('setting_text_modal_title',
                        label=self.cog._spec_label(self.item_key),
                    ),
                ),
            )
            return
        await interaction.response.send_message(
            self.cog._t('setting_change_ui_not_ready'),
            ephemeral=True,
        )


class _SettingBoolEditView(_SettingItemFooterView):
    @discord.ui.button(label=_BTN_ENABLE, style=discord.ButtonStyle.success, row=0)
    async def enable_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if self.item_key in ('exp_enable', 'verify_enable'):
            block = await self.cog._feature_enable_block_reason(interaction.guild)
            if block:
                await self._show_item(interaction, self.item_key, notice=f'⚠ {block}')
                return
        ok, message = self.cog._save_setting_value(interaction.guild, self.item_key, True)
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        await self._show_item(interaction, self.item_key, notice=notice)

    @discord.ui.button(label=_BTN_DISABLE, style=discord.ButtonStyle.danger, row=0)
    async def disable_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        ok, message = self.cog._save_setting_value(interaction.guild, self.item_key, False)
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        await self._show_item(interaction, self.item_key, notice=notice)


class _SettingChannelEditView(_SettingItemFooterView):
    @discord.ui.select(
        select_type=discord.ComponentType.channel_select,
        channel_types=[discord.ChannelType.text],
        placeholder=_CHANNEL_PLACEHOLDER,
        min_values=1,
        max_values=1,
        row=0,
    )
    async def channel_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not select.values:
            return
        channel = select.values[0]
        ok, message = self.cog._save_setting_value(interaction.guild, self.item_key, channel.id)
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        await self._show_item(interaction, self.item_key, notice=notice)


class _SettingRoleEditView(_SettingItemFooterView):
    @discord.ui.select(
        select_type=discord.ComponentType.role_select,
        placeholder=_ROLE_PLACEHOLDER,
        min_values=1,
        max_values=1,
        row=0,
    )
    async def role_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not select.values:
            return
        role = select.values[0]
        ok, message = self.cog._save_setting_value(interaction.guild, self.item_key, role.id)
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        await self._show_item(interaction, self.item_key, notice=notice)


class _SettingProfileEditView(_SettingItemFooterView):
    def __init__(self, cog: 'setting', requester_id: int, item_key: str, category: str):
        super().__init__(cog, requester_id, item_key, category)
        self.profile_select_menu = discord.ui.Select(
            select_type=discord.ComponentType.string_select,
            placeholder=db_tone.render_default_message('setting_profile_placeholder'),
            min_values=1,
            max_values=1,
            options=_profile_select_options(),
            row=0,
        )
        self.profile_select_menu.callback = self._on_select_profile
        self.add_item(self.profile_select_menu)

    async def _on_select_profile(self, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not self.profile_select_menu.values:
            return
        profile = self.profile_select_menu.values[0]
        ok, message = self.cog._save_setting_value(interaction.guild, self.item_key, profile)
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        await self._show_item(interaction, self.item_key, notice=notice)


class _EmbedColorModal(discord.ui.Modal):
    def __init__(self, cog: 'setting', requester_id: int, category: str):
        self.cog = cog
        self.requester_id = requester_id
        self.category = category
        self.color_input = discord.ui.InputText(
            label=db_tone.render_default_message('setting_embed_color_input_label'),
            placeholder=db_tone.render_default_message('setting_embed_color_input_placeholder'),
            required=True,
            min_length=6,
            max_length=7,
        )
        super().__init__(self.color_input, title=db_tone.render_default_message('setting_embed_color_modal_title'))

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    interaction.guild.id if interaction.guild else 0,
                    '명령어 실행자와 모달 제출자가 다름',
                ),
                ephemeral=True,
            )
            return
        if not await _defer_setting_interaction(interaction):
            return
        raw = (self.color_input.value or '').strip()
        ok, message = self.cog._save_setting_value(interaction.guild, 'embed_color', raw)
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        guild = interaction.guild
        cog = self.cog
        requester_id = self.requester_id
        category = self.category
        await _refresh_setting_message(
            interaction,
            content=cog._notice_content(notice),
            embed_builder=lambda: cog._build_item_embed(guild, 'embed_color', category),
            view_builder=lambda: cog._build_item_view(
                guild, requester_id, 'embed_color', category,
            ),
        )


class _TextSettingModal(discord.ui.Modal):
    def __init__(
        self,
        cog: 'setting',
        requester_id: int,
        item_key: str,
        category: str,
        current_value: str | None,
        title: str,
    ):
        self.cog = cog
        self.requester_id = requester_id
        self.item_key = item_key
        self.category = category
        self.text_input = discord.ui.InputText(
            label=db_tone.render_default_message('setting_text_modal_label'),
            placeholder=db_tone.render_default_message('setting_text_modal_placeholder'),
            required=True,
            value=str(current_value or '')[:512],
            min_length=1,
            max_length=512,
            style=discord.InputTextStyle.long,
        )
        super().__init__(self.text_input, title=title)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    interaction.guild.id if interaction.guild else 0,
                    '명령어 실행자와 모달 제출자가 다름',
                ),
                ephemeral=True,
            )
            return
        if not await _defer_setting_interaction(interaction):
            return
        raw = (self.text_input.value or '').strip()
        ok, message = self.cog._save_setting_value(interaction.guild, self.item_key, raw)
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        guild = interaction.guild
        cog = self.cog
        requester_id = self.requester_id
        item_key = self.item_key
        category = self.category
        await _refresh_setting_message(
            interaction,
            content=cog._notice_content(notice),
            embed_builder=lambda: cog._build_item_embed(guild, item_key, category),
            view_builder=lambda: cog._build_item_view(
                guild, requester_id, item_key, category,
            ),
        )


class _VerifyQuestionsEditView(_SettingBaseView):
    def __init__(
        self,
        cog: 'setting',
        requester_id: int,
        item_key: str,
        category: str,
        guild: discord.Guild,
    ):
        super().__init__(cog, requester_id, category, item_key=item_key)
        items = cog._load_verify_questions(guild.id)
        if items:
            self.question_select = discord.ui.Select(
                placeholder=_VERIFY_SELECT_PLACEHOLDER,
                options=cog._verify_question_select_options(items),
                min_values=1,
                max_values=1,
                row=0,
            )
            self.question_select.callback = self._on_select_question
            self.add_item(self.question_select)

    @discord.ui.button(label=_VERIFY_BTN_ADD, style=discord.ButtonStyle.primary, row=1)
    async def add_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if len(self.cog._load_verify_questions(interaction.guild.id)) >= 4:
            await interaction.response.send_message(
                self.cog._t('setting_verify_max_questions'),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            _VerifyQuestionUpsertModal(self.cog, self.requester_id, self.category)
        )

    @discord.ui.button(label=_VERIFY_BTN_BACK, style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        await self._show_dashboard(interaction)

    async def _on_select_question(self, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not self.question_select.values:
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    interaction.guild.id if interaction.guild else 0,
                    '질문이 선택되지 않음',
                ),
                ephemeral=True,
            )
            return
        question_index = int(self.question_select.values[0])
        guild = interaction.guild
        cog = self.cog
        requester_id = self.requester_id
        item_key = self.item_key
        category = self.category
        await _edit_setting_interaction(
            interaction,
            content=cog._notice_content(
                cog._t('setting_verify_question_selected', index=question_index),
            ),
            embed_builder=lambda: cog._build_item_embed(guild, item_key, category),
            view_builder=lambda: _VerifyQuestionActionView(
                cog,
                requester_id,
                item_key,
                category,
                guild=guild,
                question_index=question_index,
            ),
        )


class _VerifyQuestionActionView(_SettingBaseView):
    def __init__(
        self,
        cog: 'setting',
        requester_id: int,
        item_key: str,
        category: str,
        *,
        guild: discord.Guild,
        question_index: int,
    ):
        super().__init__(cog, requester_id, category, item_key=item_key)
        self.guild = guild
        self.question_index = question_index
        items = cog._load_verify_questions(guild.id)
        self._current = items[question_index - 1] if 0 < question_index <= len(items) else None

    @discord.ui.button(label=_VERIFY_BTN_EDIT, style=discord.ButtonStyle.primary, row=0)
    async def edit_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if self._current is None:
            await interaction.response.send_message(
                self.cog._t('setting_verify_question_not_found'),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            _VerifyQuestionUpsertModal(
                self.cog,
                self.requester_id,
                self.category,
                index=self.question_index,
                current=self._current,
            )
        )

    @discord.ui.button(label=_VERIFY_BTN_MOVE, style=discord.ButtonStyle.secondary, row=0)
    async def move_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        await interaction.response.send_modal(
            _VerifyQuestionMoveModal(
                self.cog,
                self.requester_id,
                self.category,
                source_index=self.question_index,
            )
        )

    @discord.ui.button(label=_VERIFY_BTN_DELETE, style=discord.ButtonStyle.danger, row=0)
    async def delete_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not await _defer_setting_interaction(interaction):
            return
        ok, message = self.cog._save_verify_question_delete(
            interaction.guild,
            str(self.question_index),
        )
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        guild = interaction.guild
        cog = self.cog
        requester_id = self.requester_id
        item_key = self.item_key
        category = self.category
        await _refresh_setting_message(
            interaction,
            content=cog._notice_content(notice),
            embed_builder=lambda: cog._build_item_embed(guild, item_key, category),
            view_builder=lambda: _VerifyQuestionsEditView(
                cog,
                requester_id,
                item_key,
                category,
                guild=guild,
            ),
        )

    @discord.ui.button(label=_VERIFY_BTN_BACK, style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        guild = interaction.guild
        cog = self.cog
        requester_id = self.requester_id
        item_key = self.item_key
        category = self.category
        await _edit_setting_interaction(
            interaction,
            content=cog._notice_content(cog._t('setting_verify_questions_notice')),
            embed_builder=lambda: cog._build_item_embed(guild, item_key, category),
            view_builder=lambda: _VerifyQuestionsEditView(
                cog,
                requester_id,
                item_key,
                category,
                guild=guild,
            ),
        )


class _VerifyQuestionUpsertModal(discord.ui.Modal):
    def __init__(
        self,
        cog: 'setting',
        requester_id: int,
        category: str,
        *,
        index: int | None = None,
        current: dict | None = None,
    ):
        self.cog = cog
        self.requester_id = requester_id
        self.category = category
        self.fixed_index = index
        current = current or {}
        modal_items: list[discord.ui.Item] = []
        if index is None:
            self.index_input = discord.ui.InputText(
                label=db_tone.render_default_message('setting_verify_modal_index_label'),
                placeholder=db_tone.render_default_message('setting_verify_modal_index_placeholder'),
                required=True,
                min_length=1,
                max_length=1,
            )
            modal_items.append(self.index_input)
        self.question_input = discord.ui.InputText(
            label=db_tone.render_default_message('setting_verify_modal_question_label'),
            placeholder=db_tone.render_default_message('setting_verify_modal_question_placeholder'),
            required=True,
            min_length=1,
            max_length=512,
            style=discord.InputTextStyle.long,
            value=str(current.get('question') or '')[:512],
        )
        self.answers_input = discord.ui.InputText(
            label=db_tone.render_default_message('setting_verify_modal_answers_label'),
            placeholder=db_tone.render_default_message('setting_verify_modal_answers_placeholder'),
            required=False,
            max_length=1024,
            style=discord.InputTextStyle.long,
            value='\n'.join(str(x) for x in (current.get('answers') or []))[:1024],
        )
        modal_items.extend([self.question_input, self.answers_input])
        if index is not None:
            title = db_tone.render_default_message('setting_verify_modal_edit_title', index=index)
        else:
            title = db_tone.render_default_message('setting_verify_modal_add_title')
        super().__init__(*modal_items, title=title)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    interaction.guild.id if interaction.guild else 0,
                    '명령어 실행자와 모달 제출자가 다름',
                ),
                ephemeral=True,
            )
            return
        if not await _defer_setting_interaction(interaction):
            return
        index_raw = str(self.fixed_index) if self.fixed_index is not None else self.index_input.value
        if self.fixed_index is not None:
            ok, message = self.cog._save_verify_question_upsert(
                interaction.guild,
                index_raw,
                self.question_input.value,
                self.answers_input.value,
            )
        else:
            ok, message = self.cog._save_verify_question_insert(
                interaction.guild,
                index_raw,
                self.question_input.value,
                self.answers_input.value,
            )
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        guild = interaction.guild
        cog = self.cog
        requester_id = self.requester_id
        category = self.category
        await _refresh_setting_message(
            interaction,
            content=cog._notice_content(notice),
            embed_builder=lambda: cog._build_item_embed(guild, 'verify_questions', category),
            view_builder=lambda: _VerifyQuestionsEditView(
                cog,
                requester_id,
                'verify_questions',
                category,
                guild=guild,
            ),
        )


class _VerifyQuestionMoveModal(discord.ui.Modal):
    def __init__(
        self,
        cog: 'setting',
        requester_id: int,
        category: str,
        *,
        source_index: int,
    ):
        self.cog = cog
        self.requester_id = requester_id
        self.category = category
        self.source_index = source_index
        self.target_input = discord.ui.InputText(
            label=db_tone.render_default_message('setting_verify_modal_move_label'),
            placeholder=db_tone.render_default_message('setting_verify_modal_move_placeholder'),
            required=True,
            min_length=1,
            max_length=1,
        )
        super().__init__(
            self.target_input,
            title=db_tone.render_default_message('setting_verify_modal_move_title', index=source_index),
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    interaction.guild.id if interaction.guild else 0,
                    '명령어 실행자와 모달 제출자가 다름',
                ),
                ephemeral=True,
            )
            return
        if not await _defer_setting_interaction(interaction):
            return
        ok, message = self.cog._save_verify_question_move(
            interaction.guild,
            str(self.source_index),
            self.target_input.value,
        )
        notice = f'✅ {message}' if ok else f'⚠ {message}'
        guild = interaction.guild
        cog = self.cog
        requester_id = self.requester_id
        category = self.category
        await _refresh_setting_message(
            interaction,
            content=cog._notice_content(notice),
            embed_builder=lambda: cog._build_item_embed(guild, 'verify_questions', category),
            view_builder=lambda: _VerifyQuestionsEditView(
                cog,
                requester_id,
                'verify_questions',
                category,
                guild=guild,
            ),
        )


def _autocomplete_guild(ctx: discord.AutocompleteContext) -> discord.Guild | None:
    return lib_autocomplete.autocomplete_guild(ctx)


async def _setting_category_autocomplete(ctx: discord.AutocompleteContext):
    cog = ctx.bot.get_cog('setting')
    if cog is None or _autocomplete_guild(ctx) is None:
        return []
    return await cog.category_autocomplete_choices(ctx)


class setting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _t(self, message_key: str, **kwargs) -> str:
        profile = db_tone.resolve_bot_boot_profile(self.bot)
        return db_tone.render_boot_message(message_key, profile, **kwargs)

    def _category_label(self, category: str) -> str:
        key = _CATEGORY_TONE_KEYS.get(category, f'setting_category_{category}')
        return self._t(key)

    def _spec_label(self, item_key: str) -> str:
        return self._t(f'setting_spec_{item_key}_label')

    def _spec_desc(self, item_key: str) -> str:
        return self._t(f'setting_spec_{item_key}_desc')

    def _spec_clear_label(self, item_key: str) -> str:
        return self._t(f'setting_spec_{item_key}_clear')

    async def _feature_enable_block_reason(self, guild: discord.Guild) -> str | None:
        guild_id = guild.id
        settings = db_setting.get_all_settings(guild_id)
        if not settings.bot_log_channel:
            return self._t('setting_feature_enable_block')
        log_issue = await lib_channel_check.configured_text_channel_issue(
            self.bot,
            guild,
            settings.bot_log_channel,
            unset_message=self._t('onboarding_log_channel_unset'),
            missing_message=self._t('onboarding_log_channel_missing'),
        )
        if log_issue:
            return self._t('setting_feature_enable_block_log_issue', issue=log_issue)
        return None

    def _feature_enable_block_reason_sync(self, guild_id: int) -> str | None:
        settings = db_setting.get_all_settings(guild_id)
        if not settings.bot_log_channel:
            return self._t('setting_feature_enable_block')
        return None

    async def _is_bot_admin(self, member: discord.Member) -> bool:
        return lib_bot_admin.is_bot_admin(member, include_bot_owner=True)

    def _is_premium_context(self, guild_id: int) -> bool:
        return lib_premium.is_premium_context(self.bot, guild_id)

    def _is_verify_available(self, guild_id: int) -> bool:
        if not self._is_premium_context(guild_id):
            return False
        return lib_cog_scope.is_extension_enabled_for_guild(
            self.bot,
            lib_cog_scope.VERIFY_COG_MODULE,
            guild_id,
        )

    def _is_party_available(self, guild_id: int) -> bool:
        if not lib_premium.is_recruit_entitled(self.bot, guild_id):
            return False
        return lib_cog_scope.is_extension_enabled_for_guild(
            self.bot,
            lib_cog_scope.PARTY_COG_MODULE,
            guild_id,
        )

    def _visible_categories(self, guild: discord.Guild) -> tuple[str, ...]:
        categories: list[str] = ['basic', 'exp']
        if self._is_verify_available(guild.id):
            categories.append('verify')
        if self._is_party_available(guild.id):
            categories.append('party')
        categories.extend(lib_setting_registry.visible_categories(self.bot, guild.id))
        return tuple(categories)

    def _visible_setting_keys(self, guild: discord.Guild, category: str) -> tuple[str, ...]:
        if category not in self._visible_categories(guild):
            return ()
        core = _SETTING_CATEGORY_KEYS.get(category)
        if core is not None:
            return core
        return lib_setting_registry.items_for_category(category)

    async def category_autocomplete_choices(
        self,
        ctx: discord.AutocompleteContext,
    ) -> list[discord.OptionChoice]:
        guild = _autocomplete_guild(ctx)
        if guild is None:
            return []
        current = (ctx.value or '').strip().lower()
        choices: list[discord.OptionChoice] = []
        for category in self._visible_categories(guild):
            label = self._category_label(category)
            if current and current not in label.lower() and current not in category:
                continue
            choices.append(discord.OptionChoice(name=label, value=category))
        return choices[:25]

    def _item_select_options(
        self,
        guild: discord.Guild,
        category: str,
        *,
        current_key: str | None = None,
    ) -> list[discord.SelectOption]:
        return [
            discord.SelectOption(
                label=self._spec_label(key),
                value=key,
                description=self._spec_desc(key)[:100],
                default=(key == current_key),
            )
            for key in self._visible_setting_keys(guild, category)
        ]

    def _configure_item_select(
        self,
        select: discord.ui.Select,
        guild: discord.Guild,
        category: str,
        *,
        current_key: str | None = None,
    ) -> None:
        select.options = self._item_select_options(
            guild, category, current_key=current_key,
        )

    def _configure_dashboard_view(
        self,
        view: _SettingDashboardView,
        guild: discord.Guild,
        category: str,
    ) -> None:
        self._configure_item_select(view.item_select, guild, category)

    def _build_item_view(
        self,
        guild: discord.Guild,
        requester_id: int,
        item_key: str,
        category: str,
    ) -> discord.ui.View:
        view = _create_item_view(self, requester_id, item_key, category)
        if isinstance(view, _SettingItemFooterView):
            view._apply_clear_label()
            self._configure_item_select(
                view.item_select,
                guild,
                category,
                current_key=item_key,
            )
        return view

    async def _require_admin(self, ctx) -> bool:
        if ctx.guild is None:
            await ctx.respond(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return False
        if not isinstance(ctx.author, discord.Member):
            await ctx.respond(
                db_tone.render_validation_error(ctx.guild.id, '길드 멤버 정보를 확인할 수 없음'),
                ephemeral=True,
            )
            return False
        if not await self._is_bot_admin(ctx.author):
            await ctx.respond(self._t('setting_perm_denied'), ephemeral=True)
            return False
        return True

    def _fmt_bool(self, value: int) -> str:
        key = 'setting_fmt_bool_on' if value else 'setting_fmt_bool_off'
        return self._t(key)

    def _fmt_role(self, guild: discord.Guild, role_id: int | None) -> str:
        if not role_id:
            return self._t('setting_fmt_role_unset')
        role = guild.get_role(role_id)
        return role.mention if role else self._t('setting_fmt_role_deleted', role_id=role_id)

    def _fmt_channel(self, channel_id: int | None) -> str:
        if not channel_id:
            return self._t('setting_fmt_channel_unset')
        return f'<#{channel_id}>'

    def _notice_content(self, notice: str | None) -> str | None:
        if not notice:
            return None
        return f'{notice}'

    def _verify_question_select_options(self, items: list[dict]) -> list[discord.SelectOption]:
        options: list[discord.SelectOption] = []
        for index, item in enumerate(items, start=1):
            question = str(item.get('question') or '').strip()
            if not question:
                continue
            if not item.get('answers'):
                answer_desc = self._t('setting_verify_answer_descriptive')
            else:
                answer_desc = self._t('setting_verify_answer_count',
                    count=len(item['answers']),
                )
            label = f'{index}. {question}'
            if len(label) > 100:
                label = f'{label[:97]}...'
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(index),
                    description=answer_desc[:100],
                )
            )
        return options

    def _load_verify_questions(self, guild_id: int) -> list[dict]:
        return db_setting.get_verify_questions(guild_id)

    def _save_verify_questions(self, guild_id: int, questions: list[dict]) -> None:
        db_setting.save_verify_questions(guild_id, questions)

    def _save_verify_question_upsert(self, guild: discord.Guild, index_raw: str, question_raw: str, answers_raw: str | None) -> tuple[bool, str]:
        guild_id = guild.id
        try:
            index = int((index_raw or '').strip())
        except Exception:
            return False, self._t('setting_verify_index_invalid')
        if index < 1 or index > 4:
            return False, self._t('setting_verify_index_out_of_range')
        question = (question_raw or '').strip()
        if not question:
            return False, db_tone.render_validation_error(guild_id, '질문이 비어있음')
        if len(question) > 512:
            return False, db_tone.render_validation_error(guild_id, '질문이 너무 긺')
        answers = [line.strip() for line in (answers_raw or '').splitlines() if line.strip()]
        items = self._load_verify_questions(guild_id)
        if index < 1 or index > len(items):
            return False, self._t('setting_verify_question_not_exists')
        items[index - 1] = {'question': question, 'answers': answers}
        self._save_verify_questions(guild_id, items)
        return True, self._t('setting_verify_question_saved', index=index)

    def _save_verify_question_insert(self, guild: discord.Guild, index_raw: str, question_raw: str, answers_raw: str | None) -> tuple[bool, str]:
        guild_id = guild.id
        try:
            index = int((index_raw or '').strip())
        except Exception:
            return False, self._t('setting_verify_index_not_number')
        question = (question_raw or '').strip()
        if not question:
            return False, db_tone.render_validation_error(guild_id, '질문이 비어있음')
        if len(question) > 512:
            return False, db_tone.render_validation_error(guild_id, '질문이 너무 긺')
        answers = [line.strip() for line in (answers_raw or '').splitlines() if line.strip()]
        items = self._load_verify_questions(guild_id)
        if len(items) >= 4:
            return False, self._t('setting_verify_question_max')
        max_index = len(items) + 1
        if index < 1 or index > max_index:
            return False, self._t('setting_verify_question_insert_range', max_index=max_index)
        items.insert(index - 1, {'question': question, 'answers': answers})
        self._save_verify_questions(guild_id, items)
        return True, self._t('setting_verify_question_inserted', index=index)

    def _save_verify_question_delete(self, guild: discord.Guild, index_raw: str) -> tuple[bool, str]:
        guild_id = guild.id
        try:
            index = int((index_raw or '').strip())
        except Exception:
            return False, self._t('setting_verify_index_invalid')
        items = self._load_verify_questions(guild_id)
        if index < 1 or index > len(items):
            return False, self._t('setting_verify_question_not_exists')
        del items[index - 1]
        self._save_verify_questions(guild_id, items)
        return True, self._t('setting_verify_question_deleted', index=index)

    def _save_verify_question_move(self, guild: discord.Guild, source_raw: str, target_raw: str) -> tuple[bool, str]:
        guild_id = guild.id
        try:
            source = int((source_raw or '').strip())
            target = int((target_raw or '').strip())
        except Exception:
            return False, self._t('setting_verify_index_invalid')
        items = self._load_verify_questions(guild_id)
        if source < 1 or source > len(items):
            return False, self._t('setting_verify_move_source_missing')
        if target < 1 or target > 4:
            return False, self._t('setting_verify_move_target_invalid')
        moved = items.pop(source - 1)
        items.insert(min(len(items), target - 1), moved)
        self._save_verify_questions(guild_id, items)
        return True, self._t('setting_verify_question_moved', source=source, target=target)

    async def _setting_value_text(
        self,
        guild: discord.Guild,
        settings: db_setting.GuildSettings,
        item_key: str,
    ) -> str:
        guild_id = guild.id
        if item_key == 'exp_enable':
            return self._fmt_bool(settings.exp_enable)
        if item_key == 'exp_channel':
            return await lib_channel_check.format_exp_channel_status(
                self.bot,
                guild,
                settings.exp_channel,
            )
        if item_key == 'exp_role':
            if settings.exp_role:
                return self._fmt_role(guild, settings.exp_role)
            return self._t('setting_fmt_exp_role_all')
        if item_key == 'bot_admin_role':
            return self._fmt_role(guild, settings.bot_admin_role)
        if item_key == 'bot_log_channel':
            value = self._fmt_channel(settings.bot_log_channel)
            issue = await lib_channel_check.configured_text_channel_issue(
                self.bot,
                guild,
                settings.bot_log_channel,
                unset_message='',
                missing_message=self._t('setting_log_channel_missing'),
            )
            if issue:
                value = f'{value}\n⚠ {issue}'
            return value
        if item_key == 'embed_color':
            return db_setting.format_embed_color(settings.embed_color)
        if item_key == 'tone_profile':
            return db_tone.get_profile_title(settings.tone_profile)
        if item_key == 'verify_enable':
            return self._fmt_bool(settings.verify_enable)
        if item_key == 'verify_panel_channel':
            return self._fmt_channel(settings.verify_panel_channel)
        if item_key == 'verify_log_channel':
            return self._fmt_channel(settings.verify_log_channel)
        if item_key == 'verify_role':
            return self._fmt_role(guild, settings.verify_role)
        if item_key == 'verify_repass_enable':
            return self._fmt_bool(settings.verify_repass_enable)
        if item_key == 'verify_auto_reject_wrong':
            return self._fmt_bool(settings.verify_auto_reject_wrong)
        if item_key == 'recruit_thread_channel':
            return self._fmt_channel(settings.recruit_thread_channel)
        if item_key == 'verify_questions':
            items = self._load_verify_questions(guild_id)
            if not items:
                return self._t('setting_verify_questions_unset')
            lines = []
            for index, item in enumerate(items, start=1):
                if not item.get('answers'):
                    answer_desc = self._t('setting_verify_answer_descriptive')
                else:
                    answer_desc = self._t('setting_verify_answer_count',
                        count=len(item['answers']),
                    )
                lines.append(f'{index}. {item["question"]} ({answer_desc})')
            return '\n'.join(lines)
        item = lib_setting_registry.get_item(item_key)
        if item is not None:
            value = item.get(guild_id) if item.get is not None else None
            if item.format is not None:
                return item.format(
                    guild_id,
                    value,
                    t=self._t,
                    fmt_channel=self._fmt_channel,
                )
            if item.kind == 'channel':
                return self._fmt_channel(value)
            if item.kind == 'text':
                if not value:
                    return self._t('setting_fmt_channel_unset')
                return str(value)
        return self._t('setting_unknown_value')

    async def _build_status_embed(
        self,
        guild: discord.Guild,
        category: str,
    ) -> discord.Embed:
        settings = db_setting.get_all_settings(guild.id)
        exp_issue = await lib_channel_check.exp_channel_issue(
            self.bot,
            guild,
            settings.exp_channel,
        )
        color = db_setting.get_embed_color(guild.id)
        if category == 'exp' and settings.exp_enable and exp_issue:
            color = 0xE67E22

        category_label = self._category_label(category)
        embed = discord.Embed(
            title=self._t('setting_embed_status_title', category=category_label),
            color=color,
        )
        for item_key in self._visible_setting_keys(guild, category):
            lib_embed_fields.add_embed_field_safe(
                embed,
                self._spec_label(item_key),
                await self._setting_value_text(guild, settings, item_key),
                inline=False,
            )
        if category == 'exp' and settings.exp_enable and exp_issue:
            lib_embed_fields.add_embed_field_safe(
                embed,
                self._t('setting_exp_warning_field'),
                exp_issue,
                inline=False,
            )
        embed.set_footer(text=self._t('setting_embed_footer'))
        return embed

    async def _build_item_embed(
        self,
        guild: discord.Guild,
        item_key: str,
        category: str,
    ) -> discord.Embed:
        guild_id = guild.id
        if item_key not in self._visible_setting_keys(guild, category):
            return discord.Embed(
                title=self._t('setting_embed_item_title'),
                description=self._t('setting_embed_item_unavailable'),
                color=db_setting.get_embed_color(guild_id),
            )
        settings = db_setting.get_all_settings(guild_id)
        value_text = await self._setting_value_text(guild, settings, item_key)
        embed = discord.Embed(
            title=self._t('setting_embed_item_detail_title',
                label=self._spec_label(item_key),
            ),
            description=self._spec_desc(item_key),
            color=db_setting.get_embed_color(guild_id),
        )
        lib_embed_fields.add_embed_field_safe(
            embed,
            self._t('setting_embed_current_value'),
            value_text,
            inline=False,
        )
        if item_key == 'verify_questions':
            lib_embed_fields.add_embed_field_safe(
                embed,
                self._t('setting_embed_change_method'),
                self._t('setting_embed_verify_howto'),
                inline=False,
            )
        item_spec = _setting_spec(item_key)
        if item_spec is not None and item_spec.kind == 'color':
            clear_label = self._spec_clear_label(item_key)
            howto_key = (
                'setting_embed_color_howto_clearable'
                if item_spec.clearable
                else 'setting_embed_color_howto'
            )
            lib_embed_fields.add_embed_field_safe(
                embed,
                self._t('setting_embed_change_method'),
                self._t(howto_key, clear_label=clear_label),
                inline=False,
            )
        return embed

    def _save_setting_value(
        self,
        guild: discord.Guild,
        item_key: str,
        value,
    ) -> tuple[bool, str]:
        guild_id = guild.id
        spec = _setting_spec(item_key)
        if spec is None:
            return False, db_tone.render_validation_error(guild_id, '알 수 없는 설정 항목임')
        if item_key in _SETTING_ORDER_VERIFY and not self._is_verify_available(guild_id):
            return False, db_tone.render_validation_error(guild_id, '프리미엄 전용 항목임')
        if item_key in _SETTING_ORDER_PARTY and not self._is_party_available(guild_id):
            return False, db_tone.render_validation_error(guild_id, '프리미엄 전용 항목임')
        if value is None and not spec.clearable:
            return False, self._t('setting_not_clearable')

        normalized_value = value
        if spec.kind == 'channel' and item_key != 'recruit_thread_channel' and value is not None:
            channel = guild.get_channel(int(value))
            err = lib_channel_check.text_channel_send_issue(channel, guild)
            if err:
                return False, self._t('setting_channel_permission_hint', issue=err)
            normalized_value = channel.id
        elif item_key == 'recruit_thread_channel' and value is not None:
            channel = guild.get_channel(int(value))
            if not isinstance(channel, discord.TextChannel):
                return False, self._t(
                    'setting_channel_permission_hint',
                    issue='텍스트 채널만 지정할 수 있어요.',
                )
            normalized_value = channel.id
        elif item_key in ('exp_role', 'bot_admin_role', 'verify_role') and value is not None:
            role = guild.get_role(int(value))
            if role is None:
                return False, self._t('setting_role_not_found')
            normalized_value = role.id
        elif item_key in ('exp_enable', 'verify_enable'):
            normalized_value = 1 if value else 0
            if normalized_value:
                block = self._feature_enable_block_reason_sync(guild_id)
                if block:
                    return False, block

        try:
            _update_setting_value(guild_id, item_key, normalized_value)
            if item_key == 'embed_color':
                normalized_value = db_setting.get_setting(guild_id, 'embed_color')
        except db_setting.SettingValidationError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, self._t('setting_save_error', detail=exc)
        return True, self._build_saved_message(item_key, normalized_value)

    def _build_saved_message(self, item_key: str, value) -> str:
        def saved(key: str, **kwargs) -> str:
            return self._t(key, **kwargs)

        item = lib_setting_registry.get_item(item_key)
        if item is not None and item.save_message is not None:
            return item.save_message(value, t=self._t)

        if item_key == 'exp_enable':
            key = 'setting_saved_exp_enable_on' if value else 'setting_saved_exp_enable_off'
            return saved(key)
        if item_key == 'exp_channel':
            if value is None:
                return self._t('setting_saved_exp_channel_off')
            return self._t('setting_saved_exp_channel_on', channel_id=value)
        if item_key == 'exp_role':
            if value is None:
                return self._t('setting_saved_exp_role_off')
            return self._t('setting_saved_exp_role_on', role_id=value)
        if item_key == 'bot_admin_role':
            if value is None:
                return self._t('setting_saved_bot_admin_role_off')
            return self._t('setting_saved_bot_admin_role_on', role_id=value)
        if item_key == 'bot_log_channel':
            return self._t('setting_saved_bot_log_channel', channel_id=value)
        if item_key == 'embed_color':
            return self._t('setting_saved_embed_color',
                color=db_setting.format_embed_color(value),
            )
        if item_key == 'tone_profile':
            return self._t('setting_saved_tone_profile',
                profile_title=db_tone.get_profile_title(value),
            )
        if item_key == 'verify_enable':
            key = 'setting_saved_verify_enable_on' if value else 'setting_saved_verify_enable_off'
            return self._t(key)
        if item_key == 'verify_panel_channel':
            return self._t('setting_saved_verify_panel_channel', channel_id=value)
        if item_key == 'verify_log_channel':
            return self._t('setting_saved_verify_log_channel', channel_id=value)
        if item_key == 'verify_role':
            return self._t('setting_saved_verify_role', role_id=value)
        if item_key == 'verify_repass_enable':
            key = (
                'setting_saved_verify_repass_enable_on'
                if value
                else 'setting_saved_verify_repass_enable_off'
            )
            return self._t(key)
        if item_key == 'verify_auto_reject_wrong':
            key = (
                'setting_saved_verify_auto_reject_wrong_on'
                if value
                else 'setting_saved_verify_auto_reject_wrong_off'
            )
            return self._t(key)
        if item_key == 'recruit_thread_channel':
            if value is None:
                return saved('setting_saved_recruit_thread_channel_off')
            return saved('setting_saved_recruit_thread_channel_on', channel_id=value)
        if item_key == 'verify_questions':
            return self._t('setting_saved_verify_questions')
        return saved('setting_saved_generic')

    @commands.slash_command(
        name='설정',
        description=db_tone.render_default_message('setting_command_desc'),
    )
    async def open_settings(
        self,
        ctx,
        category: Annotated[
            str,
            discord.Option(
                str,
                name=db_tone.render_default_message('setting_option_category_name'),
                description=db_tone.render_default_message('setting_option_category_desc'),
                required=True,
                autocomplete=_setting_category_autocomplete,
            ),
        ],
    ):
        if not await self._require_admin(ctx):
            return
        if (
            category not in _SETTING_CATEGORY_KEYS
            and category not in lib_setting_registry.registered_categories()
        ):
            await ctx.respond(self._t('setting_category_unknown'), ephemeral=True)
            return
        if category not in self._visible_categories(ctx.guild):
            await ctx.respond(self._t('setting_category_unavailable'), ephemeral=True)
            return
        if not await lib_interaction_defer.defer_slash(ctx, ephemeral=True):
            return
        try:
            dashboard_view = _SettingDashboardView(self, ctx.author.id, category)
            self._configure_dashboard_view(dashboard_view, ctx.guild, category)
            await ctx.followup.send(
                embed=await self._build_status_embed(ctx.guild, category),
                view=dashboard_view,
                ephemeral=True,
            )
        except Exception:
            try:
                await ctx.followup.send(_SETTING_UI_UPDATE_FAILED, ephemeral=True)
            except discord.HTTPException:
                pass


def setup(bot):
    bot.add_cog(setting(bot))
