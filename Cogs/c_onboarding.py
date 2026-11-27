# coding: utf-8
import discord
from discord.ext import commands

from DB import db_setting, db_tone
from Library import lib_cog_scope, lib_channel_check, lib_interaction_defer, lib_slash_guild_sync

_BTN_CLEAR_ADMIN_ROLE = db_tone.render_default_message('onboarding_btn_clear_admin_role')
_BTN_NEXT = db_tone.render_default_message('onboarding_btn_next')
_BTN_BACK = db_tone.render_default_message('onboarding_btn_back')
_BTN_EXP_ENABLE = db_tone.render_default_message('onboarding_btn_exp_enable')
_BTN_EXP_DISABLE = db_tone.render_default_message('onboarding_btn_exp_disable')
_BTN_CLEAR_EXP_CHANNEL = db_tone.render_default_message('onboarding_btn_clear_exp_channel')
_BTN_CLEAR_EXP_ROLE = db_tone.render_default_message('onboarding_btn_clear_exp_role')
_BTN_COMPLETE = db_tone.render_default_message('onboarding_btn_complete')
_PLACEHOLDER_LOG_CHANNEL = db_tone.render_default_message('onboarding_placeholder_log_channel')
_PLACEHOLDER_ADMIN_ROLE = db_tone.render_default_message('onboarding_placeholder_admin_role')
_PLACEHOLDER_EXP_CHANNEL = db_tone.render_default_message('onboarding_placeholder_exp_channel')
_PLACEHOLDER_EXP_ROLE = db_tone.render_default_message('onboarding_placeholder_exp_role')


def _build_anniversary_line(cog: 'onboarding', customer_name: str) -> str | None:
    template = cog._t('onboarding_anniversary_message', customer_name=customer_name)
    if not template or not template.strip() or template == 'onboarding_anniversary_message':
        return None
    return template


def _build_greeting_line(
    cog: 'onboarding',
    customer_info: lib_cog_scope.CustomerInfo | None,
) -> str:
    if customer_info is None:
        return cog._t('onboarding_greeting_default')
    customer_name = customer_info.customer_name
    if customer_info.is_tpc:
        greeting = cog._t('onboarding_greeting_tpc', customer_name=customer_name)
    else:
        greeting = cog._t('onboarding_greeting_regular', customer_name=customer_name)
    anniversary = _build_anniversary_line(cog, customer_name)
    if anniversary:
        return f'{greeting}{anniversary}'
    return greeting


def _guild_join_message(
    cog: 'onboarding',
    guild_name: str,
    *,
    customer_info: lib_cog_scope.CustomerInfo | None = None,
) -> str:
    greeting = _build_greeting_line(cog, customer_info)
    return cog._t('onboarding_join_message', greeting=greeting, guild_name=guild_name)


class _OnboardingBaseView(discord.ui.View):
    def __init__(self, cog: 'onboarding', requester_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.requester_id = requester_id

    async def on_timeout(self) -> None:
        self.disable_all_items()
        target = self.parent or self.message
        if target is None:
            return
        try:
            await target.edit(
                content=self.cog._t('onboarding_view_expired'),
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

    async def _show_general(self, interaction: discord.Interaction, notice: str | None = None):
        await interaction.response.edit_message(
            content=self.cog._notice_content(notice),
            embed=await self.cog._build_general_embed(interaction.guild),
            view=_OnboardingGeneralView(self.cog, self.requester_id),
        )

    async def _show_exp_enable(self, interaction: discord.Interaction, notice: str | None = None):
        await interaction.response.edit_message(
            content=self.cog._notice_content(notice),
            embed=await self.cog._build_exp_enable_embed(interaction.guild),
            view=_OnboardingExpEnableView(self.cog, self.requester_id),
        )

    async def _show_exp_detail(self, interaction: discord.Interaction, notice: str | None = None):
        await interaction.response.edit_message(
            content=self.cog._notice_content(notice),
            embed=await self.cog._build_exp_detail_embed(interaction.guild),
            view=_OnboardingExpDetailView(self.cog, self.requester_id),
        )

    async def _show_complete(self, interaction: discord.Interaction, notice: str | None = None):
        await interaction.response.edit_message(
            content=self.cog._notice_content(notice),
            embed=await self.cog._build_complete_embed(interaction.guild),
            view=_OnboardingCompleteView(self.cog, self.requester_id),
        )


class _OnboardingGeneralView(_OnboardingBaseView):
    async def _refresh(self, interaction: discord.Interaction, notice: str | None = None):
        await interaction.response.edit_message(
            content=self.cog._notice_content(notice),
            embed=await self.cog._build_general_embed(interaction.guild),
            view=_OnboardingGeneralView(self.cog, self.requester_id),
        )

    @discord.ui.select(
        select_type=discord.ComponentType.channel_select,
        channel_types=[discord.ChannelType.text],
        placeholder=_PLACEHOLDER_LOG_CHANNEL,
        min_values=1,
        max_values=1,
        row=0,
    )
    async def log_channel_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        guild_id = interaction.guild.id
        if not select.values:
            await self._refresh(interaction, self.cog._t('onboarding_notice_select_log_channel'))
            return
        channel = select.values[0]
        err = lib_channel_check.text_channel_send_issue(channel, interaction.guild)
        if err:
            await self._refresh(interaction, f'⚠ {err}')
            return
        db_setting.update_setting(guild_id, 'bot_log_channel', channel.id)
        await self._refresh(
            interaction,
            self.cog._t('onboarding_notice_log_channel_saved', channel=channel.mention),
        )

    @discord.ui.select(
        select_type=discord.ComponentType.role_select,
        placeholder=_PLACEHOLDER_ADMIN_ROLE,
        min_values=1,
        max_values=1,
        row=1,
    )
    async def admin_role_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        guild_id = interaction.guild.id
        if not select.values:
            await self._refresh(interaction, self.cog._t('onboarding_notice_select_admin_role'))
            return
        role = select.values[0]
        db_setting.update_setting(guild_id, 'bot_admin_role', role.id)
        await self._refresh(
            interaction,
            self.cog._t('onboarding_notice_admin_role_saved', role=role.mention),
        )

    @discord.ui.button(label=_BTN_CLEAR_ADMIN_ROLE, style=discord.ButtonStyle.secondary, row=2)
    async def clear_admin_role_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        db_setting.update_setting(interaction.guild.id, 'bot_admin_role', None)
        await self._refresh(
            interaction,
            self.cog._t('onboarding_notice_admin_role_cleared'),
        )

    @discord.ui.button(label=_BTN_NEXT, style=discord.ButtonStyle.primary, row=2)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not await lib_interaction_defer.defer_component(interaction, ephemeral=True):
            return
        guild = interaction.guild
        guild_id = guild.id
        settings = db_setting.get_all_settings(guild_id)
        if not settings.bot_log_channel:
            await interaction.edit_original_response(
                content=self.cog._notice_content(self.cog._t('onboarding_notice_log_channel_required')),
                embed=await self.cog._build_general_embed(guild),
                view=_OnboardingGeneralView(self.cog, self.requester_id),
            )
            return
        log_issue = await lib_channel_check.configured_text_channel_issue(
            self.cog.bot,
            guild,
            settings.bot_log_channel,
            unset_message=self.cog._t('onboarding_log_channel_unset'),
            missing_message=self.cog._t('onboarding_log_channel_missing'),
        )
        if log_issue:
            await interaction.edit_original_response(
                content=self.cog._notice_content(f'⚠ {log_issue}'),
                embed=await self.cog._build_general_embed(guild),
                view=_OnboardingGeneralView(self.cog, self.requester_id),
            )
            return
        await interaction.edit_original_response(
            content=self.cog._notice_content(self.cog._t('onboarding_notice_general_done')),
            embed=await self.cog._build_exp_enable_embed(guild),
            view=_OnboardingExpEnableView(self.cog, self.requester_id),
        )


class _OnboardingExpEnableView(_OnboardingBaseView):
    @discord.ui.button(label=_BTN_EXP_ENABLE, style=discord.ButtonStyle.success, row=0)
    async def exp_enable_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        db_setting.update_setting(interaction.guild.id, 'exp_enable', 1)
        await self._show_exp_detail(
            interaction,
            self.cog._t('onboarding_notice_exp_enabled'),
        )

    @discord.ui.button(label=_BTN_EXP_DISABLE, style=discord.ButtonStyle.danger, row=0)
    async def exp_disable_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        guild_id = interaction.guild.id
        db_setting.update_setting(guild_id, 'exp_enable', 0)
        db_setting.update_setting(guild_id, 'exp_channel', None)
        db_setting.update_setting(guild_id, 'exp_role', None)
        await self._show_complete(
            interaction,
            self.cog._t('onboarding_notice_exp_disabled'),
        )

    @discord.ui.button(label=_BTN_BACK, style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        await self._show_general(interaction)


class _OnboardingExpDetailView(_OnboardingBaseView):
    async def _refresh(self, interaction: discord.Interaction, notice: str | None = None):
        await interaction.response.edit_message(
            content=self.cog._notice_content(notice),
            embed=await self.cog._build_exp_detail_embed(interaction.guild),
            view=_OnboardingExpDetailView(self.cog, self.requester_id),
        )

    @discord.ui.select(
        select_type=discord.ComponentType.channel_select,
        channel_types=[discord.ChannelType.text],
        placeholder=_PLACEHOLDER_EXP_CHANNEL,
        min_values=1,
        max_values=1,
        row=0,
    )
    async def exp_channel_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not select.values:
            return
        channel = select.values[0]
        err = lib_channel_check.text_channel_send_issue(channel, interaction.guild)
        if err:
            await self._refresh(interaction, f'⚠ {err}')
            return
        db_setting.update_setting(interaction.guild.id, 'exp_channel', channel.id)
        await self._refresh(
            interaction,
            self.cog._t('onboarding_notice_exp_channel_saved', channel=channel.mention),
        )

    @discord.ui.select(
        select_type=discord.ComponentType.role_select,
        placeholder=_PLACEHOLDER_EXP_ROLE,
        min_values=1,
        max_values=1,
        row=1,
    )
    async def exp_role_select(self, select: discord.ui.Select, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not select.values:
            return
        role = select.values[0]
        db_setting.update_setting(interaction.guild.id, 'exp_role', role.id)
        await self._refresh(
            interaction,
            self.cog._t('onboarding_notice_exp_role_saved', role=role.mention),
        )

    @discord.ui.button(label=_BTN_CLEAR_EXP_CHANNEL, style=discord.ButtonStyle.secondary, row=2)
    async def clear_exp_channel_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        db_setting.update_setting(interaction.guild.id, 'exp_channel', None)
        await self._refresh(
            interaction,
            self.cog._t('onboarding_notice_exp_channel_cleared'),
        )

    @discord.ui.button(label=_BTN_CLEAR_EXP_ROLE, style=discord.ButtonStyle.secondary, row=2)
    async def clear_exp_role_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        db_setting.update_setting(interaction.guild.id, 'exp_role', None)
        await self._refresh(
            interaction,
            self.cog._t('onboarding_notice_exp_role_cleared'),
        )

    @discord.ui.button(label=_BTN_NEXT, style=discord.ButtonStyle.primary, row=2)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not await lib_interaction_defer.defer_component(interaction, ephemeral=True):
            return
        guild = interaction.guild
        settings = db_setting.get_all_settings(guild.id)
        if settings.exp_channel:
            exp_issue = await lib_channel_check.exp_channel_issue(
                self.cog.bot,
                guild,
                settings.exp_channel,
            )
            if exp_issue:
                await interaction.edit_original_response(
                    content=self.cog._notice_content(f'⚠ {exp_issue}'),
                    embed=await self.cog._build_exp_detail_embed(guild),
                    view=_OnboardingExpDetailView(self.cog, self.requester_id),
                )
                return
        await interaction.edit_original_response(
            content=self.cog._notice_content(self.cog._t('onboarding_notice_exp_detail_done')),
            embed=await self.cog._build_complete_embed(guild),
            view=_OnboardingCompleteView(self.cog, self.requester_id),
        )

    @discord.ui.button(label=_BTN_BACK, style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        await self._show_exp_enable(interaction)


class _OnboardingCompleteView(_OnboardingBaseView):
    @discord.ui.button(label=_BTN_COMPLETE, style=discord.ButtonStyle.primary, row=0)
    async def complete_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        if not await lib_interaction_defer.defer_component(interaction, ephemeral=True):
            return
        ok, message = await self.cog._complete_onboarding(interaction.guild)
        await interaction.edit_original_response(
            content=self.cog._notice_content(f'{"✅" if ok else "⚠"} {message}'),
            embed=await self.cog._build_complete_embed(interaction.guild),
            view=None if ok else _OnboardingCompleteView(self.cog, self.requester_id),
        )

    @discord.ui.button(label=_BTN_BACK, style=discord.ButtonStyle.secondary, row=0)
    async def back_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_requester(interaction):
            return
        settings = db_setting.get_all_settings(interaction.guild.id)
        if settings.exp_enable:
            await self._show_exp_detail(interaction)
        else:
            await self._show_exp_enable(interaction)


class onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _t(self, message_key: str, **kwargs) -> str:
        profile = db_tone.resolve_bot_boot_profile(self.bot)
        return db_tone.render_boot_message(message_key, profile, **kwargs)

    async def _resolve_guild_owner(self, guild: discord.Guild) -> discord.User | None:
        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_owner()
            except Exception:
                owner = None
        return owner

    def _first_private_thread_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        me = guild.me
        if me is None:
            return None
        for channel in guild.text_channels:
            if lib_channel_check.text_channel_send_issue(channel, guild) is not None:
                continue
            if not channel.permissions_for(me).create_private_threads:
                continue
            return channel
        return None

    async def _send_join_welcome_system_channel_fallback(
        self,
        guild: discord.Guild,
        owner: discord.User,
        guide_text: str,
    ) -> None:
        channel = guild.system_channel
        if channel is None:
            print(f'[onboarding] system channel fallback skipped, no system channel guild={guild.id}')
            return

        err = lib_channel_check.text_channel_send_issue(channel, guild)
        if err:
            print(f'[onboarding] system channel fallback skipped guild={guild.id}: {err}')
            return

        try:
            await channel.send(
                f'{owner.mention}\n{guide_text}',
                allowed_mentions=discord.AllowedMentions(users=[owner]),
            )
        except Exception as exc:
            print(f'[onboarding] system channel fallback failed guild={guild.id}: {exc}')

    async def _send_join_welcome_private_thread_fallback(
        self,
        guild: discord.Guild,
        owner: discord.User,
        guide_text: str,
    ) -> None:
        channel = self._first_private_thread_channel(guild)
        if channel is not None:
            try:
                thread = await channel.create_thread(
                    name=self._t('onboarding_thread_fallback_name'),
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    auto_archive_duration=10080,
                )
                await thread.add_user(owner)
                await thread.send(
                    f'{owner.mention}\n{guide_text}',
                    allowed_mentions=discord.AllowedMentions(users=[owner]),
                )
                return
            except Exception as exc:
                print(f'[onboarding] private thread fallback failed guild={guild.id}: {exc}')

        await self._send_join_welcome_system_channel_fallback(guild, owner, guide_text)

    def _mark_onboarding_dm_sent(self, guild_id: int) -> None:
        db_setting.update_setting(guild_id, 'onboarding_dm_sent', 1)

    async def _send_join_welcome_dm(self, guild: discord.Guild) -> None:
        owner = await self._resolve_guild_owner(guild)
        if owner is None:
            return

        guide_text = _guild_join_message(
            self,
            guild.name,
            customer_info=lib_cog_scope.customer_info(self.bot, guild.id),
        )
        try:
            await owner.send(guide_text)
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f'[onboarding] DM failed guild={guild.id}: {exc}')
            await self._send_join_welcome_private_thread_fallback(guild, owner, guide_text)
        except Exception as exc:
            print(f'[onboarding] DM failed guild={guild.id}: {exc}')
            await self._send_join_welcome_private_thread_fallback(guild, owner, guide_text)
        self._mark_onboarding_dm_sent(guild.id)

    async def _handle_new_guild(self, guild: discord.Guild) -> None:
        db_setting.ensure_guild(guild.id)
        try:
            await lib_slash_guild_sync.sync_guild_commands(self.bot, guild.id)
        except Exception as exc:
            print(f'[slash_guild] join sync failed for {guild.id}: {exc}')
        if db_setting.get_setting(guild.id, 'onboarding_dm_sent'):
            return
        await self._send_join_welcome_dm(guild)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            if not lib_cog_scope.is_cog_allowed_guild(self.bot, self, guild.id):
                continue
            if db_setting.get_setting(guild.id, 'onboarding_dm_sent'):
                continue
            await self._handle_new_guild(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        if not lib_cog_scope.is_cog_allowed_guild(self.bot, self, guild.id):
            return
        await self._handle_new_guild(guild)

    async def _require_owner(self, ctx) -> bool:
        if ctx.guild is None:
            await ctx.respond(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return False
        if ctx.author.id != ctx.guild.owner_id:
            await ctx.respond(self._t('onboarding_owner_only'), ephemeral=True)
            return False
        return True

    def _fmt_channel(self, channel_id: int | None) -> str:
        if not channel_id:
            return self._t('onboarding_fmt_unset')
        return f'<#{channel_id}>'

    def _fmt_role(self, role_id: int | None, *, none_text_key: str) -> str:
        if not role_id:
            return self._t(none_text_key)
        return f'<@&{role_id}>'

    def _notice_content(self, notice: str | None) -> str | None:
        if not notice:
            return None
        return notice

    async def _build_general_embed(self, guild: discord.Guild) -> discord.Embed:
        guild_id = guild.id
        settings = db_setting.get_all_settings(guild_id)
        embed = discord.Embed(
            title=self._t('onboarding_embed_general_title'),
            description=self._t('onboarding_embed_general_desc'),
            color=db_setting.get_embed_color(guild_id),
        )
        embed.add_field(
            name=self._t('onboarding_embed_general_field_current'),
            value=self._t('onboarding_embed_general_field_value',
                log_channel=self._fmt_channel(settings.bot_log_channel),
                admin_role=self._fmt_role(
                    settings.bot_admin_role,
                    none_text_key='onboarding_fmt_owner_only',
                ),
            ),
            inline=False,
        )
        embed.set_footer(text=self._t('onboarding_embed_general_footer'))
        return embed

    async def _build_exp_enable_embed(self, guild: discord.Guild) -> discord.Embed:
        guild_id = guild.id
        settings = db_setting.get_all_settings(guild_id)
        status_key = 'onboarding_fmt_enabled' if settings.exp_enable else 'onboarding_fmt_disabled'
        embed = discord.Embed(
            title=self._t('onboarding_embed_exp_enable_title'),
            description=self._t('onboarding_embed_exp_enable_desc'),
            color=db_setting.get_embed_color(guild_id),
        )
        embed.add_field(
            name=self._t('onboarding_embed_general_field_current'),
            value=self._t('onboarding_embed_exp_enable_field_value',
                status=self._t(status_key),
            ),
            inline=False,
        )
        embed.set_footer(text=self._t('onboarding_embed_exp_enable_footer'))
        return embed

    async def _build_exp_detail_embed(self, guild: discord.Guild) -> discord.Embed:
        guild_id = guild.id
        settings = db_setting.get_all_settings(guild_id)
        embed = discord.Embed(
            title=self._t('onboarding_embed_exp_detail_title'),
            description=self._t('onboarding_embed_exp_detail_desc'),
            color=db_setting.get_embed_color(guild_id),
        )
        embed.add_field(
            name=self._t('onboarding_embed_general_field_current'),
            value=self._t('onboarding_embed_exp_detail_field_value',
                exp_channel=self._fmt_channel(settings.exp_channel),
                exp_role=self._fmt_role(
                    settings.exp_role,
                    none_text_key='onboarding_fmt_all_members',
                ),
            ),
            inline=False,
        )
        embed.set_footer(text=self._t('onboarding_embed_exp_detail_footer'))
        return embed

    async def _build_complete_embed(self, guild: discord.Guild) -> discord.Embed:
        guild_id = guild.id
        settings = db_setting.get_all_settings(guild_id)
        status_key = 'onboarding_fmt_enabled' if settings.exp_enable else 'onboarding_fmt_disabled'
        if settings.exp_enable:
            exp_lines = self._t('onboarding_embed_exp_lines_enabled',
                status=self._t(status_key),
                exp_channel=self._fmt_channel(settings.exp_channel),
                exp_role=self._fmt_role(
                    settings.exp_role,
                    none_text_key='onboarding_fmt_all_members',
                ),
            )
        else:
            exp_lines = self._t('onboarding_embed_exp_lines_disabled',
                status=self._t(status_key),
            )
        embed = discord.Embed(
            title=self._t('onboarding_embed_complete_title'),
            description=self._t('onboarding_embed_complete_desc'),
            color=db_setting.get_embed_color(guild_id),
        )
        embed.add_field(
            name=self._t('onboarding_embed_complete_field_general'),
            value=self._t('onboarding_embed_complete_field_general_value',
                log_channel=self._fmt_channel(settings.bot_log_channel),
                admin_role=self._fmt_role(
                    settings.bot_admin_role,
                    none_text_key='onboarding_fmt_owner_only',
                ),
            ),
            inline=False,
        )
        embed.add_field(
            name=self._t('onboarding_embed_complete_field_exp'),
            value=self._t('onboarding_embed_complete_field_exp_value', exp_lines=exp_lines),
            inline=False,
        )
        if settings.bot_enable:
            embed.add_field(
                name=self._t('onboarding_embed_complete_field_status'),
                value=self._t('onboarding_fmt_complete_status'),
                inline=False,
            )
        return embed

    async def _complete_onboarding(self, guild: discord.Guild) -> tuple[bool, str]:
        guild_id = guild.id
        if db_setting.get_setting(guild_id, 'bot_enable'):
            return False, self._t('onboarding_already_complete')

        settings = db_setting.get_all_settings(guild_id)
        if not settings.bot_log_channel:
            return False, self._t('onboarding_complete_missing_required')

        log_issue = await lib_channel_check.configured_text_channel_issue(
            self.bot,
            guild,
            settings.bot_log_channel,
            unset_message=self._t('onboarding_log_channel_unset'),
            missing_message=self._t('onboarding_log_channel_missing'),
        )
        if log_issue:
            return False, self._t('onboarding_complete_log_channel_issue', issue=log_issue)

        if settings.exp_channel:
            exp_issue = await lib_channel_check.exp_channel_issue(
                self.bot,
                guild,
                settings.exp_channel,
            )
            if exp_issue:
                return False, self._t('onboarding_complete_exp_channel_issue', issue=exp_issue)

        try:
            db_setting.mark_setup_complete(guild_id)
        except db_setting.SettingValidationError as exc:
            return False, str(exc)

        try:
            await lib_slash_guild_sync.sync_guild_commands(self.bot, guild_id)
        except Exception as exc:
            print(f'[slash_guild] post-setup sync failed guild={guild_id}: {exc}')
            return False, self._t('onboarding_complete_sync_failed')
        return True, self._t('onboarding_complete_success')

    @commands.slash_command(
        name='초기설정',
        description=db_tone.render_default_message('onboarding_command_desc'),
    )
    async def open_onboarding(self, ctx):
        if not await self._require_owner(ctx):
            return
        guild_id = ctx.guild.id
        if db_setting.get_setting(guild_id, 'bot_enable'):
            await ctx.respond(
                embed=await self._build_complete_embed(ctx.guild),
                content=self._t('onboarding_already_complete'),
                ephemeral=True,
            )
            return
        await ctx.respond(
            embed=await self._build_general_embed(ctx.guild),
            view=_OnboardingGeneralView(self, ctx.author.id),
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(onboarding(bot))
