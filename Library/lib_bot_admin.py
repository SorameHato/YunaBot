# coding: utf-8
from __future__ import annotations

import discord

from DB import db_setting

# 운영자·디버그 채널 (main / addon_main 공통)
_BOT_OWNER_UID = 1470810710379466934
_DEFAULT_DEBUG_CHANNEL_ID = 1504509915123945474


def bot_owner_id() -> int:
    return _BOT_OWNER_UID


def default_debug_channel_id() -> int:
    return _DEFAULT_DEBUG_CHANNEL_ID


def is_bot_admin(member: discord.Member, *, include_bot_owner: bool = False) -> bool:
    if include_bot_owner and member.id == _BOT_OWNER_UID:
        return True
    try:
        admin_role_id = db_setting.get_setting(member.guild.id, 'bot_admin_role')
    except Exception:
        admin_role_id = None
    if member.id == member.guild.owner_id:
        return True
    if admin_role_id:
        role = member.guild.get_role(admin_role_id)
        return role is not None and role in member.roles
    return False
