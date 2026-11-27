# coding: utf-8
from __future__ import annotations

from DB import db_setting
from Library import lib_cog_scope


def is_addon_premium_context(bot, guild_id: int) -> bool:
    return lib_cog_scope.is_premium_shortcut(bot, guild_id)


def is_premium_context(bot, guild_id: int) -> bool:
    if is_addon_premium_context(bot, guild_id):
        return True
    try:
        return db_setting.is_premium_enabled(guild_id)
    except Exception:
        return False


def is_verify_entitled(bot, guild_id: int) -> bool:
    if is_addon_premium_context(bot, guild_id):
        return lib_cog_scope.is_extension_enabled_for_guild(
            bot,
            lib_cog_scope.VERIFY_COG_MODULE,
            guild_id,
        )
    return is_premium_context(bot, guild_id)


def is_recruit_entitled(bot, guild_id: int) -> bool:
    if is_addon_premium_context(bot, guild_id):
        return lib_cog_scope.is_extension_enabled_for_guild(
            bot,
            lib_cog_scope.PARTY_COG_MODULE,
            guild_id,
        )
    try:
        return bool(db_setting.get_setting(guild_id, 'recruit_enable'))
    except Exception:
        return False
