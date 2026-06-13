# coding: utf-8
"""Guild-specific slash command description/option sync when tone profile differs from default."""
from __future__ import annotations

import asyncio
import inspect
from typing import Any

import discord
from discord.commands import SlashCommand, SlashCommandGroup

import db_tone

_SLASH_TONE_KEYS: tuple[str, ...] = (
    'info_command_desc',
    'expFE_group_name',
    'expFE_status_desc',
    'expFE_ranking_desc',
    'expFE_ranking_option1_name',
    'expFE_ranking_option1_desc',
    'expFE_ranking_option1_choice0',
    'expFE_ranking_option1_choice1',
    'expFE_ranking_option1_choice2',
    'expFE_ranking_option2_name',
    'expFE_ranking_option2_desc',
    'expFE_mention_desc',
    'expFE_mention_option_name',
    'expFE_mention_option_desc',
    'expFE_mention_option_choice_on',
    'expFE_mention_option_choice_off',
    'dailyInform_group_desc',
    'dailyInform_add_desc',
    'dailyInform_add_option1_name',
    'dailyInform_add_option1_desc',
    'dailyInform_add_option_message_name',
    'dailyInform_add_option_message_desc',
    'dailyInform_list_desc',
    'dailyInform_list_option1_name',
    'dailyInform_list_option1_desc',
    'dailyInform_edit_desc_time',
    'dailyInform_edit_desc_msg',
    'dailyInform_edit_option1_name',
    'dailyInform_edit_option1_desc',
    'dailyInform_edit_option2_time_name',
    'dailyInform_edit_option2_time_desc',
    'dailyInform_edit_option2_msg_name',
    'dailyInform_edit_option2_msg_desc',
    'dailyInform_delete_desc',
    'dailyInform_delete_option1_name',
    'dailyInform_delete_option1_desc',
)

_GROUP_SPECS: dict[str, dict[str, Any]] = {
    '경험치': {
        'desc': 'expFE_group_name',
        'commands': {
            '현황': {'desc': 'expFE_status_desc'},
            '랭킹': {
                'desc': 'expFE_ranking_desc',
                'params': {
                    'todayOrder': {
                        'name': 'expFE_ranking_option1_name',
                        'desc': 'expFE_ranking_option1_desc',
                        'choices': (
                            'expFE_ranking_option1_choice0',
                            'expFE_ranking_option1_choice1',
                            'expFE_ranking_option1_choice2',
                        ),
                    },
                    'page': {
                        'name': 'expFE_ranking_option2_name',
                        'desc': 'expFE_ranking_option2_desc',
                    },
                },
            },
            '멘션': {
                'desc': 'expFE_mention_desc',
                'params': {
                    'enabled': {
                        'name': 'expFE_mention_option_name',
                        'desc': 'expFE_mention_option_desc',
                        'choices': (
                            'expFE_mention_option_choice_on',
                            'expFE_mention_option_choice_off',
                        ),
                    },
                },
            },
        },
    },
    '알림': {
        'desc': 'dailyInform_group_desc',
        'commands': {
            '등록': {
                'desc': 'dailyInform_add_desc',
                'params': {
                    'time_value': {
                        'name': 'dailyInform_add_option1_name',
                        'desc': 'dailyInform_add_option1_desc',
                    },
                    'message': {
                        'name': 'dailyInform_add_option_message_name',
                        'desc': 'dailyInform_add_option_message_desc',
                    },
                },
            },
            '조회': {
                'desc': 'dailyInform_list_desc',
                'params': {
                    'page': {
                        'name': 'dailyInform_list_option1_name',
                        'desc': 'dailyInform_list_option1_desc',
                    },
                },
            },
            '시간수정': {
                'desc': 'dailyInform_edit_desc_time',
                'params': {
                    'row_id': {
                        'name': 'dailyInform_edit_option1_name',
                        'desc': 'dailyInform_edit_option1_desc',
                    },
                    'time_value': {
                        'name': 'dailyInform_edit_option2_time_name',
                        'desc': 'dailyInform_edit_option2_time_desc',
                    },
                },
            },
            '내용수정': {
                'desc': 'dailyInform_edit_desc_msg',
                'params': {
                    'row_id': {
                        'name': 'dailyInform_edit_option1_name',
                        'desc': 'dailyInform_edit_option1_desc',
                    },
                    'message': {
                        'name': 'dailyInform_edit_option2_msg_name',
                        'desc': 'dailyInform_edit_option2_msg_desc',
                    },
                },
            },
            '삭제': {
                'desc': 'dailyInform_delete_desc',
                'params': {
                    'row_id': {
                        'name': 'dailyInform_delete_option1_name',
                        'desc': 'dailyInform_delete_option1_desc',
                    },
                },
            },
        },
    },
}

_TOP_LEVEL_SPECS: dict[str, dict[str, str]] = {
    '정보': {'desc': 'info_command_desc'},
}

_guild_overrides: dict[int, list[discord.ApplicationCommand]] = {}
_bot: discord.Bot | None = None


def _t(guild_id: int, message_key: str) -> str:
    return db_tone.render_message(guild_id, message_key)


def needs_guild_slash_sync(guild_id: int) -> bool:
    if guild_id in db_tone.GUILD_TEMPLATES:
        return True
    for key in _SLASH_TONE_KEYS:
        if _t(guild_id, key) != db_tone.render_default_message(key):
            return True
    return False


def _callback_param_names(callback) -> list[str]:
    return [
        name
        for name, param in inspect.signature(callback).parameters.items()
        if name not in ('self', 'ctx', 'cog') and param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    ]


def _apply_option_tone(guild_id: int, option, param_spec: dict[str, Any]) -> None:
    if 'name' in param_spec:
        option.name = _t(guild_id, param_spec['name'])
    if 'desc' in param_spec:
        option.description = _t(guild_id, param_spec['desc'])
    choice_keys = param_spec.get('choices')
    if choice_keys and option.choices:
        for choice, key in zip(option.choices, choice_keys):
            if isinstance(choice, discord.OptionChoice):
                choice.name = _t(guild_id, key)


def _apply_command_tone(guild_id: int, command: SlashCommand, spec: dict[str, Any]) -> None:
    command.description = _t(guild_id, spec['desc'])
    params_spec = spec.get('params')
    if not params_spec or not command.options:
        return
    param_names = _callback_param_names(command.callback)
    for param_name, option in zip(param_names, command.options):
        param_spec = params_spec.get(param_name)
        if param_spec:
            _apply_option_tone(guild_id, option, param_spec)


def _clone_group_for_guild(group: SlashCommandGroup, guild_id: int) -> SlashCommandGroup | None:
    spec = _GROUP_SPECS.get(group.name)
    if spec is None:
        return None

    clone = group.copy()
    clone.guild_ids = [guild_id]
    clone.description = _t(guild_id, spec['desc'])
    clone.subcommands = []

    command_specs = spec.get('commands', {})
    for subcommand in group.subcommands:
        if not isinstance(subcommand, SlashCommand):
            continue
        sub_spec = command_specs.get(subcommand.name)
        if sub_spec is None:
            continue
        sub_clone = subcommand.copy()
        sub_clone.parent = clone
        if subcommand.cog is not None:
            sub_clone.cog = subcommand.cog
        if subcommand.parent is not None:
            sub_clone.attached_to_group = True
        sub_clone._validate_parameters()
        _apply_command_tone(guild_id, sub_clone, sub_spec)
        clone.subcommands.append(sub_clone)

    return clone


def _clone_top_level_for_guild(command: SlashCommand, guild_id: int) -> SlashCommand | None:
    spec = _TOP_LEVEL_SPECS.get(command.name)
    if spec is None:
        return None
    clone = command.copy()
    clone.guild_ids = [guild_id]
    clone.description = _t(guild_id, spec['desc'])
    if command.cog is not None:
        clone.cog = command.cog
    clone._validate_parameters()
    return clone


def _remove_guild_overrides(bot: discord.Bot, guild_id: int) -> None:
    for command in _guild_overrides.pop(guild_id, []):
        bot.remove_application_command(command)


def _build_guild_overrides(bot: discord.Bot, guild_id: int) -> list[discord.ApplicationCommand]:
    overrides: list[discord.ApplicationCommand] = []
    for command in bot.pending_application_commands:
        if command.guild_ids is not None:
            continue
        if isinstance(command, SlashCommandGroup):
            clone = _clone_group_for_guild(command, guild_id)
            if clone is not None:
                overrides.append(clone)
        elif isinstance(command, SlashCommand) and not command.is_subcommand:
            clone = _clone_top_level_for_guild(command, guild_id)
            if clone is not None:
                overrides.append(clone)
    return overrides


async def sync_guild_slash_tone(bot: discord.Bot, guild_id: int) -> None:
    _remove_guild_overrides(bot, guild_id)

    if needs_guild_slash_sync(guild_id):
        overrides = _build_guild_overrides(bot, guild_id)
        for command in overrides:
            bot.add_application_command(command)
        _guild_overrides[guild_id] = overrides
        await bot.sync_commands(
            commands=overrides,
            check_guilds=[guild_id],
            force=True,
        )
        print(f'[slash_tone] synced guild {guild_id} ({len(overrides)} commands)')
        return

    await bot.sync_commands(
        commands=[],
        check_guilds=[guild_id],
        register_guild_commands=True,
        force=True,
    )
    print(f'[slash_tone] cleared guild overrides for {guild_id}')


def schedule_guild_slash_sync(bot: discord.Bot, guild_id: int) -> None:
    async def _run() -> None:
        try:
            await sync_guild_slash_tone(bot, guild_id)
        except Exception as exc:
            print(f'[slash_tone] sync failed for guild {guild_id}: {exc}')

    try:
        loop = bot.loop
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_run(), loop)
        else:
            loop.create_task(_run())
    except Exception as exc:
        print(f'[slash_tone] schedule failed for guild {guild_id}: {exc}')


async def sync_all_guild_slash_tones(bot: discord.Bot) -> None:
    guild_ids = {guild.id for guild in bot.guilds}
    guild_ids.update(db_tone.GUILD_TEMPLATES.keys())
    for guild_id in sorted(guild_ids):
        if needs_guild_slash_sync(guild_id):
            await sync_guild_slash_tone(bot, guild_id)


def schedule_all_guild_slash_sync(bot: discord.Bot) -> None:
    async def _run() -> None:
        try:
            await sync_all_guild_slash_tones(bot)
        except Exception as exc:
            print(f'[slash_tone] bulk sync failed: {exc}')

    try:
        loop = bot.loop
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_run(), loop)
        else:
            loop.create_task(_run())
    except Exception as exc:
        print(f'[slash_tone] bulk schedule failed: {exc}')


def install(bot: discord.Bot) -> None:
    global _bot
    _bot = bot
