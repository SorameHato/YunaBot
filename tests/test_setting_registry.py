# coding: utf-8
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, sentinel

from Cogs import c_setting
from Library import lib_setting_registry


def teardown_function():
    lib_setting_registry.clear()


def test_public_settings_have_no_addon_category():
    assert 'addon' not in c_setting._SETTING_CATEGORY_KEYS
    assert 'addon2_music_text_channel' not in c_setting._SETTING_SPECS
    assert 'addon2_welcome_dm_message' not in c_setting._SETTING_SPECS
    assert 'addon2_expression_register_channel' not in c_setting._SETTING_SPECS


def test_registered_addon_settings_appear_at_request_time():
    lib_setting_registry.register_item(lib_setting_registry.SettingItem(
        category='addon',
        key='addon2_music_text_channel',
        kind='channel',
        clearable=True,
        get=lambda guild_id: 111,
        set=lambda guild_id, value: None,
        save_message=lambda value, t: 'saved',
    ))
    assert lib_setting_registry.registered_categories() == ('addon',)
    assert lib_setting_registry.items_for_category('addon') == ('addon2_music_text_channel',)
    spec = c_setting._setting_spec('addon2_music_text_channel')
    assert spec is not None
    assert spec.kind == 'channel'
    assert spec.clearable is True
    assert c_setting._get_setting_value(1, 'addon2_music_text_channel') == 111


def test_open_settings_accepts_registered_category_only_in_allowed_guild(monkeypatch):
    lib_setting_registry.register_category('addon', is_available=lambda bot, guild_id: guild_id == 1)
    cog = c_setting.setting(SimpleNamespace())
    monkeypatch.setattr(cog, '_require_admin', AsyncMock(return_value=True))
    monkeypatch.setattr(cog, '_is_verify_available', lambda guild_id: False)
    monkeypatch.setattr(cog, '_is_party_available', lambda guild_id: False)
    configure = Mock()
    monkeypatch.setattr(cog, '_configure_dashboard_view', configure)
    monkeypatch.setattr(cog, '_build_status_embed', AsyncMock(return_value=sentinel.embed))
    monkeypatch.setattr(c_setting.lib_interaction_defer, 'defer_slash', AsyncMock(return_value=True))

    async def invoke(guild_id, category):
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=guild_id), author=SimpleNamespace(id=3),
            respond=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()),
        )
        await c_setting.setting.open_settings.callback(cog, ctx, category)
        return ctx

    allowed = asyncio.run(invoke(1, 'addon'))
    allowed.followup.send.assert_awaited_once()
    assert allowed.followup.send.await_args.kwargs['embed'] is sentinel.embed
    configure.assert_called_once()

    denied = asyncio.run(invoke(2, 'addon'))
    denied.respond.assert_awaited_once_with(cog._t('setting_category_unavailable'), ephemeral=True)
    denied.followup.send.assert_not_awaited()

    unknown = asyncio.run(invoke(1, 'invalid'))
    unknown.respond.assert_awaited_once_with(cog._t('setting_category_unknown'), ephemeral=True)
