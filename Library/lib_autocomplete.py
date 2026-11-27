# coding: utf-8
from __future__ import annotations

import discord


def autocomplete_guild(ctx: discord.AutocompleteContext) -> discord.Guild | None:
    guild = ctx.interaction.guild
    if guild is not None:
        return guild
    guild_id = ctx.interaction.guild_id
    if guild_id is None:
        return None
    return ctx.bot.get_guild(guild_id)
