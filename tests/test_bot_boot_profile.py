# coding: utf-8
from DB import db_tone


class _Bot:
    def __init__(self, **attrs):
        for key, value in attrs.items():
            setattr(self, key, value)


def test_resolve_boot_profile_ignores_addon_no():
    bot = _Bot(addon_no='0002')
    assert db_tone.resolve_bot_boot_profile(bot) == db_tone.DEFAULT_PROFILE


def test_resolve_boot_profile_uses_explicit_attribute():
    bot = _Bot(tone_boot_profile=db_tone.DEFAULT_PROFILE, addon_no='0002')
    assert db_tone.resolve_bot_boot_profile(bot) == db_tone.DEFAULT_PROFILE
