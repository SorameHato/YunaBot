# coding: utf-8
"""Guild tone_profile lookup + cog guild-map guard for Cogs/c_*.py."""
from __future__ import annotations

from DB import db_tone
from Library import lib_cog_scope


class ToneAwareCog:
    def _t(self, guild_id: int, message_key: str, **kwargs) -> str:
        if guild_id:
            return db_tone.render_message(guild_id, message_key, **kwargs)
        return db_tone.render_default_message(message_key, **kwargs)

    def _is_allowed_guild(self, guild_id: int | None) -> bool:
        return lib_cog_scope.is_cog_allowed_guild(self.bot, self, guild_id)
