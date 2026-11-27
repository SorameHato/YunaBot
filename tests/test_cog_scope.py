# coding: utf-8
import pytest

from Library import lib_cog_scope, lib_premium, lib_slash_tone_sync
from Library.lib_cog_scope import CustomerInfo


class _Bot:
    def __init__(self, **attrs):
        self.extensions = {}
        for key, value in attrs.items():
            setattr(self, key, value)


class _Cog:
    pass


def teardown_function():
    lib_cog_scope.install(lib_cog_scope.PUBLIC_POLICY)


def test_public_cog_guard_allows_any_guild():
    bot = _Bot()
    assert lib_cog_scope.is_cog_allowed_guild(bot, _Cog(), 123)
    assert not lib_cog_scope.is_cog_allowed_guild(bot, _Cog(), None)


def test_public_addon_guard_denies():
    bot = _Bot()
    assert not lib_cog_scope.is_addon_allowed_guild(bot, '0002', 123)


def test_public_hooks_are_empty_or_core():
    bot = _Bot()
    assert lib_cog_scope.addon_no_for_guild(bot, 123) is None
    assert lib_cog_scope.customer_info(bot, 123) is None
    assert lib_cog_scope.render_party_addon_tone(bot, 123, 'party_group_desc') is None
    assert lib_cog_scope.owns_global_daily_init(bot) is True
    assert lib_cog_scope.is_premium_shortcut(bot, 123) is False
    assert lib_cog_scope.ranking_url(bot, 123) is None
    assert lib_cog_scope.policy_id() == lib_cog_scope.POLICY_PUBLIC


def test_public_premium_uses_db_setting_only(monkeypatch):
    bot = _Bot()
    monkeypatch.setattr(
        'Library.lib_premium.db_setting.is_premium_enabled',
        lambda guild_id: guild_id == 9,
    )
    assert lib_premium.is_premium_context(bot, 9) is True
    assert lib_premium.is_premium_context(bot, 8) is False


def test_require_policy_rejects_public_default():
    try:
        lib_cog_scope.require_policy(lib_cog_scope.POLICY_ADDON)
    except RuntimeError as exc:
        assert 'addon' in str(exc)
    else:
        raise AssertionError('expected RuntimeError')


def test_addon_policy_denies_outside_map_and_owns_no_daily():
    addon_scope = pytest.importorskip('addon_scope')

    bot = _Bot(
        addon_no='0002',
        addon_guild_map={'0002': [10]},
        addon_guilds=[10],
        addon_cog_guild_map={'Cogs.c_expFE': [10]},
        extensions={'Cogs.c_expFE': object()},
        addon_customer_map={10: CustomerInfo('Sky', True)},
    )
    addon_scope.install()
    cog = _Cog()
    cog.__class__.__module__ = 'Cogs.c_expFE'

    assert lib_cog_scope.policy_id() == lib_cog_scope.POLICY_ADDON
    assert lib_cog_scope.is_cog_allowed_guild(bot, cog, 10)
    assert not lib_cog_scope.is_cog_allowed_guild(bot, cog, 99)
    assert lib_cog_scope.is_addon_allowed_guild(bot, '0002', 10)
    assert not lib_cog_scope.is_addon_allowed_guild(bot, '0002', 99)
    assert lib_cog_scope.addon_no_for_guild(bot, 10) == '0002'
    assert lib_cog_scope.addon_no_for_guild(bot, 99) == '0002'
    assert lib_cog_scope.customer_info(bot, 10).customer_name == 'Sky'
    assert lib_cog_scope.owns_global_daily_init(bot) is False
    assert lib_cog_scope.is_premium_shortcut(bot, 10) is True
    assert lib_cog_scope.is_premium_shortcut(bot, 99) is False


def test_core_slash_specs_exclude_addon_commands():
    assert lib_slash_tone_sync.CORE_GROUP_NAMES == frozenset({'경험치', '알림', '인증', '파티'})
    assert lib_slash_tone_sync.CORE_TOP_LEVEL_NAMES == frozenset({'정보', '설정', '초기설정'})
    assert '음악봇' not in lib_slash_tone_sync.CORE_GROUP_NAMES
    assert '운세' not in lib_slash_tone_sync.CORE_TOP_LEVEL_NAMES
    assert lib_slash_tone_sync.CORE_GROUP_NAMES <= set(lib_slash_tone_sync._GROUP_SPECS)
    assert lib_slash_tone_sync.CORE_TOP_LEVEL_NAMES <= set(lib_slash_tone_sync._TOP_LEVEL_SPECS)
