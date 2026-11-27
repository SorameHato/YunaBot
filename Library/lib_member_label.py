# coding: utf-8
from __future__ import annotations

import discord


def resolve_display_name(user: discord.abc.User) -> str:
    return (
        getattr(user, 'display_name', None)
        or getattr(user, 'global_name', None)
        or user.name
    )


def format_user_label(user: discord.abc.User) -> str:
    return f'{resolve_display_name(user)} ({user.name})'
