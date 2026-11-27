# coding: utf-8
"""Guild-specific slash command description/option sync when tone profile differs from default."""
from __future__ import annotations

import asyncio
import inspect
from typing import Any

import discord
from discord.commands import SlashCommand, SlashCommandGroup

from DB import db_tone
from Library import lib_cog_scope

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
    'dailyInform_period_option_name',
    'dailyInform_add_period_desc',
    'dailyInform_edit_period_desc',
    'dailyInform_period_choice_daily',
    'dailyInform_period_choice_weekly',
    'dailyInform_period_choice_monthly',
    'dailyInform_period_choice_yearly',
    'dailyInform_period_choice_once',
    'dailyInform_add_desc',
    'dailyInform_add_option1_name',
    'dailyInform_add_option1_desc',
    'dailyInform_add_option_message_name',
    'dailyInform_add_option_message_desc',
    'dailyInform_list_desc',
    'dailyInform_list_option1_name',
    'dailyInform_list_option1_desc',
    'dailyInform_edit_desc',
    'dailyInform_edit_option_name',
    'dailyInform_edit_option_desc',
    'dailyInform_delete_desc',
    'dailyInform_delete_option_name',
    'dailyInform_delete_option_desc',
    'verify_group_desc',
    'verify_post_panel_desc',
    'verify_post_panel_option_channel_name',
    'verify_post_panel_option_channel_desc',
    'party_group_desc',
    'party_recruit_desc',
    'party_end_desc',
    'party_end_option_name',
    'party_end_option_desc',
    'party_edit_desc',
    'party_edit_option_name',
    'party_edit_option_desc',
    'setting_command_desc',
    'setting_option_category_name',
    'setting_option_category_desc',
    'onboarding_command_desc',
)

CORE_GROUP_NAMES = frozenset({'경험치', '알림', '인증', '파티'})
CORE_TOP_LEVEL_NAMES = frozenset({'정보', '설정', '초기설정'})

_GROUP_SPECS: dict[str, dict[str, Any]] = {
    '경험치': {
        'desc': 'expFE_group_name',
        'commands': {
            '현황': {'desc': 'expFE_status_desc'},
            '랭킹': {
                'desc': 'expFE_ranking_desc',
                'params': {
                    'today_order': {
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
                    'period': {
                        'name': 'dailyInform_period_option_name',
                        'desc': 'dailyInform_add_period_desc',
                        'choices': tuple(
                            f'dailyInform_period_choice_{value}'
                            for value in ('daily', 'weekly', 'monthly', 'yearly', 'once')
                        ),
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
            '수정': {
                'desc': 'dailyInform_edit_desc',
                'params': {
                    'period': {
                        'name': 'dailyInform_period_option_name',
                        'desc': 'dailyInform_edit_period_desc',
                        'choices': tuple(
                            f'dailyInform_period_choice_{value}'
                            for value in ('daily', 'weekly', 'monthly', 'yearly', 'once')
                        ),
                    },
                    'row_id': {
                        'name': 'dailyInform_edit_option_name',
                        'desc': 'dailyInform_edit_option_desc',
                    },
                },
            },
            '삭제': {
                'desc': 'dailyInform_delete_desc',
                'params': {
                    'row_id': {
                        'name': 'dailyInform_delete_option_name',
                        'desc': 'dailyInform_delete_option_desc',
                    },
                },
            },
        },
    },
    '인증': {
        'desc': 'verify_group_desc',
        'commands': {
            '패널게시': {
                'desc': 'verify_post_panel_desc',
                'params': {
                    'channel': {
                        'name': 'verify_post_panel_option_channel_name',
                        'desc': 'verify_post_panel_option_channel_desc',
                    },
                },
            },
        },
    },
    '파티': {
        'desc': 'party_group_desc',
        'commands': {
            '모집': {
                'desc': 'party_recruit_desc',
            },
            '모집종료': {
                'desc': 'party_end_desc',
                'params': {
                    'recruit_id': {
                        'name': 'party_end_option_name',
                        'desc': 'party_end_option_desc',
                    },
                },
            },
            '수정': {
                'desc': 'party_edit_desc',
                'params': {
                    'recruit_id': {
                        'name': 'party_edit_option_name',
                        'desc': 'party_edit_option_desc',
                    },
                },
            },
        },
    },
}

_TOP_LEVEL_SPECS: dict[str, dict[str, Any]] = {
    '정보': {'desc': 'info_command_desc'},
    '설정': {
        'desc': 'setting_command_desc',
        'params': {
            'category': {
                'name': 'setting_option_category_name',
                'desc': 'setting_option_category_desc',
            },
        },
    },
    '초기설정': {'desc': 'onboarding_command_desc'},
}

_guild_overrides: dict[int, list[discord.ApplicationCommand]] = {}
_bot: discord.Bot | None = None


def _collect_keys_from_spec(spec: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    desc = spec.get('desc')
    if isinstance(desc, str):
        keys.append(desc)
    for param in spec.get('params', {}).values():
        if not isinstance(param, dict):
            continue
        name = param.get('name')
        if isinstance(name, str):
            keys.append(name)
        param_desc = param.get('desc')
        if isinstance(param_desc, str):
            keys.append(param_desc)
        choices = param.get('choices') or ()
        keys.extend(choice for choice in choices if isinstance(choice, str))
    for command_spec in spec.get('commands', {}).values():
        if isinstance(command_spec, dict):
            keys.extend(_collect_keys_from_spec(command_spec))
    return keys


def register_tone_keys(*keys: str) -> None:
    global _SLASH_TONE_KEYS
    seen = set(_SLASH_TONE_KEYS)
    extra: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            extra.append(key)
    if extra:
        _SLASH_TONE_KEYS = _SLASH_TONE_KEYS + tuple(extra)


def register_group(name: str, spec: dict[str, Any]) -> None:
    _GROUP_SPECS[name] = spec
    register_tone_keys(*_collect_keys_from_spec(spec))


def register_top_level(name: str, spec: dict[str, Any]) -> None:
    _TOP_LEVEL_SPECS[name] = spec
    register_tone_keys(*_collect_keys_from_spec(spec))


def _t(guild_id: int, message_key: str) -> str:
    return db_tone.render_command_message(guild_id, message_key)


def needs_guild_slash_sync(guild_id: int) -> bool:
    """True when guild-resolved slash strings differ from process boot/default pack.

    Compare against ``render_default_message(key)`` *without* guild so a guild
    ``tone_profile`` (or GUILD_TEMPLATES) that differs from the import-time boot
    profile is detected. Passing ``guild=`` made both sides identical.
    """
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


def _clone_group_for_guild(
    bot: discord.Bot, group: SlashCommandGroup, guild_id: int,
) -> SlashCommandGroup | None:
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
        if (
            group.name == '경험치'
            and subcommand.name == '랭킹'
            and lib_cog_scope.ranking_url(bot, guild_id) is not None
        ):
            sub_clone.options = []
        _apply_command_tone(guild_id, sub_clone, sub_spec)
        clone.subcommands.append(sub_clone)

    return clone


def _clone_top_level_for_guild(command: SlashCommand, guild_id: int) -> SlashCommand | None:
    spec = _TOP_LEVEL_SPECS.get(command.name)
    if spec is None:
        return None
    clone = command.copy()
    clone.guild_ids = [guild_id]
    if command.cog is not None:
        clone.cog = command.cog
    clone._validate_parameters()
    _apply_command_tone(guild_id, clone, spec)
    return clone


def _remove_guild_overrides(bot: discord.Bot, guild_id: int) -> None:
    for command in _guild_overrides.pop(guild_id, []):
        bot.remove_application_command(command)


def _build_guild_overrides(bot: discord.Bot, guild_id: int) -> list[discord.ApplicationCommand]:
    overrides: list[discord.ApplicationCommand] = []
    for command in bot.pending_application_commands:
        if command.guild_ids is not None:
            continue
        if not lib_cog_scope.is_command_allowed_for_guild(bot, command, guild_id):
            continue
        if isinstance(command, SlashCommandGroup):
            clone = _clone_group_for_guild(bot, command, guild_id)
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
