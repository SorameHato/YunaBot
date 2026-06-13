# coding: utf-8
"""Throttled admin notice when attendance is skipped due to exp_channel misconfiguration."""
from __future__ import annotations

import time

import discord

import lib_channel_check
import db_setting

_WARN_COOLDOWN_SEC = 1800
_last_warn_at: dict[int, float] = {}


async def maybe_warn_exp_channel(
    bot: discord.Client,
    guild: discord.Guild,
    channel_id: int,
) -> None:
    issue = lib_channel_check.exp_channel_issue(bot, guild, channel_id)
    if issue is None:
        return

    now = time.monotonic()
    last = _last_warn_at.get(guild.id, 0.0)
    if now - last < _WARN_COOLDOWN_SEC:
        return
    _last_warn_at[guild.id] = now

    text = (
        f'[출석 알림] **{guild.name}** 서버에서 출석 메시지를 보내지 못했어요.\n'
        f'사유: {issue}\n'
        f'`/설정 조회`로 상태를 확인하거나 `/설정 출석채널`로 채널을 다시 지정해 주세요.'
    )

    log_channel_id = None
    try:
        log_channel_id = db_setting.get_setting(guild.id, 'bot_log_channel')
    except Exception:
        pass

    target = None
    if log_channel_id:
        target = bot.get_channel(log_channel_id)
    if target is None and getattr(bot, 'dbgChannel', None):
        try:
            target = await bot.fetch_channel(bot.dbgChannel)
        except Exception:
            target = None
    if target is None:
        print(f'[exp_channel] warn skipped (no log channel) guild={guild.id}: {issue}')
        return
    try:
        await target.send(text)
    except Exception as exc:
        print(f'[exp_channel] warn send failed guild={guild.id}: {exc}')
