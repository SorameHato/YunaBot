# coding: utf-8
"""Text channel permission checks for bot send targets (exp_channel, log channel, etc.)."""
from __future__ import annotations

import discord


def text_channel_send_issue(
    channel: discord.abc.GuildChannel | None,
    guild: discord.Guild,
) -> str | None:
    if channel is None:
        return '채널을 찾을 수 없어요.'
    if not isinstance(channel, discord.TextChannel):
        return '텍스트 채널만 지정할 수 있어요.'
    me = guild.me
    if me is None:
        return '봇 멤버 정보를 확인할 수 없어요.'
    perms = channel.permissions_for(me)
    if not perms.view_channel:
        return '봇이 이 채널을 볼 수 없어요.'
    if not perms.send_messages:
        return '봇이 이 채널에 메시지를 보낼 권한이 없어요.'
    return None


def exp_channel_issue(
    bot: discord.Client,
    guild: discord.Guild,
    channel_id: int | None,
) -> str | None:
    if not channel_id:
        return None
    channel = bot.get_channel(channel_id)
    if channel is None:
        return (
            '설정된 출석 알림 채널을 찾을 수 없어요. 채널이 삭제되었을 수 있어요. '
            '`/설정 출석채널`로 다시 지정해 주세요.'
        )
    return text_channel_send_issue(channel, guild)


def format_channel_ref(channel_id: int | None) -> str:
    if not channel_id:
        return '(미설정)'
    return f'<#{channel_id}>'


def configured_text_channel_issue(
    bot: discord.Client,
    guild: discord.Guild,
    channel_id: int | None,
    unset_message: str,
    missing_message: str = '설정된 채널을 찾을 수 없어요. 채널이 삭제되었을 수 있어요.',
) -> str | None:
    if not channel_id:
        return unset_message
    channel = bot.get_channel(channel_id)
    if channel is None:
        return missing_message
    return text_channel_send_issue(channel, guild)


def format_exp_channel_status(
    bot: discord.Client,
    guild: discord.Guild,
    channel_id: int | None,
) -> str:
    label = format_channel_ref(channel_id)
    issue = exp_channel_issue(bot, guild, channel_id)
    if issue:
        return f'{label}\n⚠ {issue}'
    return label
