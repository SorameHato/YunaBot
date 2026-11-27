# coding: utf-8
"""Defer-first helpers for Discord slash / component interactions.

Discord must receive an ACK within ~3 seconds. Do cheap validation first
(permission / missing-arg early returns via ``respond``), then call one of
the ``defer_*`` helpers **before** any heavy work (channel fetch, role grant,
panel post/edit, guild slash sync, private thread create, …). Send the user
result with ``followup.send`` or ``edit_original_response``.

This ordering avoids “side effects already applied, but the user only saw
Unknown interaction” (panel posted / setup marked complete / recruit ended
while the command response failed).

If ``response.is_done()`` is already true, helpers treat that as success and
return ``True`` so callers can continue to followup / edit_original safely.
Returns ``False`` only when the interaction could not be acknowledged at all
(caller should stop without assuming a followup will succeed).
"""
from __future__ import annotations

import discord

_DEFER_ERRORS = (
    discord.NotFound,
    discord.HTTPException,
    discord.InteractionResponded,
)


async def defer_slash(
    ctx: discord.ApplicationContext,
    *,
    ephemeral: bool = True,
) -> bool:
    """ACK a slash command before heavy work. Prefer after cheap validation."""
    if ctx.interaction.response.is_done():
        return True
    try:
        await ctx.defer(ephemeral=ephemeral)
        return True
    except _DEFER_ERRORS:
        return ctx.interaction.response.is_done()


async def defer_component(
    interaction: discord.Interaction,
    *,
    ephemeral: bool = True,
) -> bool:
    """ACK a button / select / modal submit before heavy work."""
    if interaction.response.is_done():
        return True
    try:
        await interaction.response.defer(ephemeral=ephemeral)
        return True
    except _DEFER_ERRORS:
        return interaction.response.is_done()


async def defer_interaction(
    target: discord.Interaction | discord.ApplicationContext,
    *,
    ephemeral: bool = True,
) -> bool:
    """Dispatch to :func:`defer_slash` or :func:`defer_component`."""
    if isinstance(target, discord.ApplicationContext):
        return await defer_slash(target, ephemeral=ephemeral)
    return await defer_component(target, ephemeral=ephemeral)


async def followup_send(
    target: discord.Interaction | discord.ApplicationContext,
    content: str | None = None,
    *,
    ephemeral: bool = True,
    **kwargs,
) -> discord.WebhookMessage | None:
    """Send via followup after a successful defer (or prior ACK)."""
    followup = target.followup if isinstance(target, discord.ApplicationContext) else target.followup
    try:
        return await followup.send(content, ephemeral=ephemeral, **kwargs)
    except (discord.NotFound, discord.HTTPException):
        return None


async def edit_original(
    target: discord.Interaction | discord.ApplicationContext,
    **kwargs,
) -> discord.InteractionMessage | None:
    """Edit the original (deferred) response; for component UI refresh paths."""
    interaction = target if isinstance(target, discord.Interaction) else target.interaction
    try:
        return await interaction.edit_original_response(**kwargs)
    except (discord.NotFound, discord.HTTPException):
        return None
