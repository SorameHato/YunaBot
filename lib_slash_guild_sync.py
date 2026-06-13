# coding: utf-8
"""Per-guild slash registration: onboarding vs feature commands by bot_enable."""
from __future__ import annotations

import asyncio

import discord
from discord.commands import SlashCommand, SlashCommandGroup
from discord.utils import find

import db_setting
import lib_slash_tone_sync

FEATURE_ROOT_NAMES = frozenset({'정보', '경험치', '알림', '설정'})
ONBOARDING_ROOT_NAMES = frozenset({'초기설정'})

_guild_registered: dict[int, list[discord.ApplicationCommand]] = {}
_guild_sync_locks: dict[int, asyncio.Lock] = {}


def _refresh_slash_command_options(command: SlashCommand) -> None:
    """Re-parse slash options after cog/group metadata is known.

    py-cord registers callback parameters at import time while ``cog`` is still
    None, so ``ctx`` can be exposed as a user-facing option. Guild clones from
    ``copy()`` repeat the same mistake unless options are refreshed here.
    """
    if command.parent is not None:
        command.attached_to_group = True
    command._validate_parameters()


def _clone_slash_command(subcommand: SlashCommand, parent) -> SlashCommand:
    sub_clone = subcommand.copy()
    sub_clone.parent = parent
    if subcommand.cog is not None:
        sub_clone.cog = subcommand.cog
    _refresh_slash_command_options(sub_clone)
    return sub_clone


def _clone_plain_group(group: SlashCommandGroup, guild_id: int) -> SlashCommandGroup:
    clone = group.copy()
    clone.guild_ids = [guild_id]
    clone.subcommands = []
    for subcommand in group.subcommands:
        if not isinstance(subcommand, SlashCommand):
            continue
        clone.subcommands.append(_clone_slash_command(subcommand, clone))
    return clone


def _clone_feature_commands(bot: discord.Bot, guild_id: int) -> list[discord.ApplicationCommand]:
    commands: list[discord.ApplicationCommand] = []
    for command in bot.pending_application_commands:
        if command.guild_ids is not None:
            continue
        if command.name not in FEATURE_ROOT_NAMES:
            continue
        if isinstance(command, SlashCommandGroup):
            if command.name in lib_slash_tone_sync._GROUP_SPECS:
                clone = lib_slash_tone_sync._clone_group_for_guild(command, guild_id)
            else:
                clone = _clone_plain_group(command, guild_id)
            if clone is not None:
                commands.append(clone)
        elif isinstance(command, SlashCommand) and not command.is_subcommand:
            clone = lib_slash_tone_sync._clone_top_level_for_guild(command, guild_id)
            if clone is None:
                clone = command.copy()
                clone.guild_ids = [guild_id]
            if command.cog is not None:
                clone.cog = command.cog
            _refresh_slash_command_options(clone)
            commands.append(clone)
    return commands


def _clone_onboarding_commands(bot: discord.Bot, guild_id: int) -> list[discord.ApplicationCommand]:
    commands: list[discord.ApplicationCommand] = []
    for command in bot.pending_application_commands:
        if command.guild_ids is not None:
            continue
        if command.name not in ONBOARDING_ROOT_NAMES:
            continue
        if isinstance(command, SlashCommandGroup):
            commands.append(_clone_plain_group(command, guild_id))
    return commands


def _unregister_guild(bot: discord.Bot, guild_id: int) -> None:
    for command in _guild_registered.pop(guild_id, []):
        bot.remove_application_command(command)
    lib_slash_tone_sync._guild_overrides.pop(guild_id, None)


def _is_bot_enabled(guild_id: int) -> bool:
    try:
        return bool(db_setting.get_setting(guild_id, 'bot_enable'))
    except Exception:
        return False


def _guild_sync_lock(guild_id: int) -> asyncio.Lock:
    lock = _guild_sync_locks.get(guild_id)
    if lock is None:
        lock = asyncio.Lock()
        _guild_sync_locks[guild_id] = lock
    return lock


async def sync_guild_commands(bot: discord.Bot, guild_id: int) -> None:
    async with _guild_sync_lock(guild_id):
        _unregister_guild(bot, guild_id)

        if _is_bot_enabled(guild_id):
            guild_commands = _clone_feature_commands(bot, guild_id)
            mode = 'feature'
            if not guild_commands:
                raise RuntimeError('등록할 기능 명령어가 없습니다.')
        else:
            guild_commands = _clone_onboarding_commands(bot, guild_id)
            mode = 'onboarding'
            if not guild_commands:
                raise RuntimeError('등록할 초기설정 명령어가 없습니다.')

        for command in guild_commands:
            bot.add_application_command(command)
        _guild_registered[guild_id] = guild_commands

        registered = await bot.register_commands(
            guild_commands,
            guild_id=guild_id,
            method='bulk',
            force=True,
            delete_existing=True,
        )
        for item in registered:
            api_guild_id = item.get('guild_id', guild_id)
            cmd = find(
                lambda c, item=item, api_guild_id=api_guild_id: (
                    c.name == item['name']
                    and c.type == item.get('type')
                    and c.guild_ids is not None
                    and api_guild_id in c.guild_ids
                ),
                bot.pending_application_commands,
            )
            if cmd is not None:
                cmd.id = item['id']
                bot._application_commands[item['id']] = cmd
        print(f'[slash_guild] {mode} sync guild {guild_id} ({len(guild_commands)} roots)')


async def clear_global_commands(bot: discord.Bot) -> None:
    await bot.sync_commands(
        commands=[],
        register_guild_commands=False,
        force=True,
        delete_existing=True,
    )


async def sync_all_guilds(bot: discord.Bot) -> None:
    await clear_global_commands(bot)
    guild_ids = sorted(g.id for g in bot.guilds)
    for guild_id in guild_ids:
        await sync_guild_commands(bot, guild_id)


def schedule_guild_sync(bot: discord.Bot, guild_id: int) -> None:
    async def _run() -> None:
        try:
            await sync_guild_commands(bot, guild_id)
        except Exception as exc:
            print(f'[slash_guild] sync failed for guild {guild_id}: {exc}')

    try:
        loop = bot.loop
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_run(), loop)
        else:
            loop.create_task(_run())
    except Exception as exc:
        print(f'[slash_guild] schedule failed for guild {guild_id}: {exc}')


def schedule_all_guild_sync(bot: discord.Bot) -> None:
    async def _run() -> None:
        try:
            await sync_all_guilds(bot)
        except Exception as exc:
            print(f'[slash_guild] bulk sync failed: {exc}')

    try:
        loop = bot.loop
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_run(), loop)
        else:
            loop.create_task(_run())
    except Exception as exc:
        print(f'[slash_guild] bulk schedule failed: {exc}')


def install(bot: discord.Bot) -> None:
    if not getattr(SlashCommand, '_kuma_param_fix_installed', False):
        _orig_set_cog = SlashCommand._set_cog

        def _set_cog_with_param_fix(self, cog):
            _orig_set_cog(self, cog)
            _refresh_slash_command_options(self)

        SlashCommand._set_cog = _set_cog_with_param_fix
        SlashCommand._kuma_param_fix_installed = True

    lib_slash_tone_sync.install(bot)

    def _on_tone_profile_change(guild_id: int, _profile: str) -> None:
        if _is_bot_enabled(guild_id):
            schedule_guild_sync(bot, guild_id)

    db_setting.register_tone_profile_listener(_on_tone_profile_change)

    def _on_bot_enable_change(guild_id: int, enabled: int) -> None:
        schedule_guild_sync(bot, guild_id)

    db_setting.register_bot_enable_listener(_on_bot_enable_change)
