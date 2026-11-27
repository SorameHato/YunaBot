# coding: utf-8
"""Guild/feature policy hooks. Public defaults; addon_scope.install() replaces them."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CustomerInfo:
    customer_name: str
    is_tpc: bool


VERIFY_COG_MODULE = 'Cogs.c_verify'
PARTY_COG_MODULE = 'Cogs.c_party'
POLICY_PUBLIC = 'public'
POLICY_ADDON = 'addon'


def _public_is_cog_allowed_guild(bot, cog, guild_id: int | None, addon_no=None) -> bool:
    return guild_id is not None


def _public_is_command_allowed_for_guild(bot, command, guild_id: int | None) -> bool:
    return guild_id is not None


def _public_is_extension_enabled_for_guild(bot, module_name: str, guild_id: int) -> bool:
    extensions = getattr(bot, 'extensions', {})
    return module_name in extensions


def _public_is_addon_allowed_guild(bot, addon_no, guild_id: int | None) -> bool:
    return False


def _public_addon_no_for_guild(bot, guild_id: int | None) -> str | None:
    return None


def _public_customer_info(bot, guild_id: int | None) -> CustomerInfo | None:
    return None


def _public_render_party_addon_tone(bot, guild_id: int, message_key: str, **kwargs) -> str | None:
    return None


def _public_owns_global_daily_init(bot) -> bool:
    return True


def _public_is_premium_shortcut(bot, guild_id: int) -> bool:
    return False


def _public_ranking_url(bot, guild_id: int) -> str | None:
    return None


@dataclass
class CogScopePolicy:
    policy_id: str
    is_cog_allowed_guild: Callable[..., bool]
    is_command_allowed_for_guild: Callable[..., bool]
    is_extension_enabled_for_guild: Callable[..., bool]
    is_addon_allowed_guild: Callable[..., bool]
    addon_no_for_guild: Callable[..., str | None]
    customer_info: Callable[..., CustomerInfo | None]
    render_party_addon_tone: Callable[..., str | None]
    owns_global_daily_init: Callable[..., bool]
    is_premium_shortcut: Callable[..., bool]
    ranking_url: Callable[..., str | None] = _public_ranking_url


PUBLIC_POLICY = CogScopePolicy(
    policy_id=POLICY_PUBLIC,
    is_cog_allowed_guild=_public_is_cog_allowed_guild,
    is_command_allowed_for_guild=_public_is_command_allowed_for_guild,
    is_extension_enabled_for_guild=_public_is_extension_enabled_for_guild,
    is_addon_allowed_guild=_public_is_addon_allowed_guild,
    addon_no_for_guild=_public_addon_no_for_guild,
    customer_info=_public_customer_info,
    render_party_addon_tone=_public_render_party_addon_tone,
    owns_global_daily_init=_public_owns_global_daily_init,
    is_premium_shortcut=_public_is_premium_shortcut,
)

_policy = PUBLIC_POLICY


def install(policy: CogScopePolicy) -> None:
    global _policy
    if not isinstance(policy, CogScopePolicy):
        raise TypeError('policy must be a CogScopePolicy')
    _policy = policy


def policy_id() -> str:
    return _policy.policy_id


def require_policy(expected: str) -> None:
    if _policy.policy_id != expected:
        raise RuntimeError(
            f'cog scope policy must be {expected!r} before loading extensions '
            f'(current: {_policy.policy_id!r})'
        )


def is_cog_allowed_guild(bot, cog, guild_id: int | None, addon_no=None) -> bool:
    return _policy.is_cog_allowed_guild(bot, cog, guild_id, addon_no=addon_no)


def is_command_allowed_for_guild(bot, command, guild_id: int | None) -> bool:
    return _policy.is_command_allowed_for_guild(bot, command, guild_id)


def is_extension_enabled_for_guild(bot, module_name: str, guild_id: int) -> bool:
    return _policy.is_extension_enabled_for_guild(bot, module_name, guild_id)


def is_addon_allowed_guild(bot, addon_no, guild_id: int | None) -> bool:
    return _policy.is_addon_allowed_guild(bot, addon_no, guild_id)


def addon_no_for_guild(bot, guild_id: int | None) -> str | None:
    return _policy.addon_no_for_guild(bot, guild_id)


def customer_info(bot, guild_id: int | None) -> CustomerInfo | None:
    return _policy.customer_info(bot, guild_id)


def render_party_addon_tone(bot, guild_id: int, message_key: str, **kwargs) -> str | None:
    return _policy.render_party_addon_tone(bot, guild_id, message_key, **kwargs)


def owns_global_daily_init(bot) -> bool:
    return _policy.owns_global_daily_init(bot)


def is_premium_shortcut(bot, guild_id: int) -> bool:
    return _policy.is_premium_shortcut(bot, guild_id)


def ranking_url(bot, guild_id: int) -> str | None:
    return _policy.ranking_url(bot, guild_id)
