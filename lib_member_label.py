# coding: utf-8
from __future__ import annotations

import discord


def format_user_label(user: discord.abc.User) -> str:
    display_name = (
        getattr(user, 'display_name', None)
        or getattr(user, 'global_name', None)
        or user.name
    )
    return f'{display_name} ({user.name})'
