# coding: utf-8
import discord

DISCORD_EMBED_FIELD_VALUE_LIMIT = 1024
EMBED_FIELD_CONTINUATION_SUFFIX = ' (계속)'


def split_embed_field_value(
    text: str,
    *,
    max_len: int = DISCORD_EMBED_FIELD_VALUE_LIMIT,
) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind('\n', 0, max_len + 1)
        if split_at <= 0:
            split_at = max_len
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip('\n')
    return chunks


def add_embed_field_safe(
    embed: discord.Embed,
    name: str,
    value: str,
    *,
    inline: bool = False,
    continuation_suffix: str = EMBED_FIELD_CONTINUATION_SUFFIX,
) -> None:
    for index, chunk in enumerate(split_embed_field_value(value)):
        field_name = name if index == 0 else f'{name}{continuation_suffix}'
        embed.add_field(name=field_name, value=chunk, inline=inline)
