# coding: utf-8
import discord
from discord.ext import commands

import db_setting
import db_tone


class info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not getattr(bot, 'ame_color', None):
            bot.ame_color = 0xa57bdb

    @staticmethod
    def _guild_id(ctx) -> int:
        if ctx.guild is not None:
            return ctx.guild.id
        return 0

    def _t(self, guild_id: int, message_key: str, **kwargs) -> str:
        if guild_id:
            return db_tone.render_message(guild_id, message_key, **kwargs)
        return db_tone.render_default_message(message_key, **kwargs)

    async def _send_error_fallback(self, guild_id: int, message: str, embed: discord.Embed) -> None:
        channel = None
        if guild_id:
            log_channel_id = db_setting.get_setting(guild_id, 'bot_log_channel')
            if log_channel_id:
                channel = self.bot.get_channel(log_channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(self.bot.dbgChannel)
        await channel.send(message, embed=embed)

    @commands.Cog.listener()
    async def on_application_command_error(self, ctx, error):
        guild_id = self._guild_id(ctx)
        color = getattr(self.bot, 'ame_color', 0xa57bdb)
        command_label = ctx.command.qualified_name if ctx.command else '(알 수 없음)'

        embed = discord.Embed(
            title=self._t(guild_id, 'error_embed_title'),
            description=str(error),
            color=color,
        )
        embed.add_field(
            name=self._t(guild_id, 'error_embed_field1'),
            value=str(ctx.author),
            inline=False,
        )
        embed.add_field(
            name=self._t(guild_id, 'error_embed_field2'),
            value=command_label,
            inline=False,
        )
        embed.set_footer(
            text=self._t(guild_id, 'error_embed_footer', ver=self.bot.ame_ver),
        )
        photo = self._t(guild_id, 'error_embed_photo')
        if photo and not photo.startswith('error_embed_'):
            embed.set_image(url=photo)

        message = self._t(guild_id, 'error_title')
        try:
            await ctx.respond(message, embed=embed)
        except discord.NotFound:
            await self._send_error_fallback(guild_id, message, embed)
        except discord.InteractionResponded:
            await self._send_error_fallback(guild_id, message, embed)
        raise error

    @commands.slash_command(
        name='정보',
        description=db_tone.render_default_message('info_command_desc'),
    )
    async def amebot_info(self, ctx):
        guild_id = self._guild_id(ctx)
        bot_name = db_tone.render_default_name()
        title = self._t(guild_id, 'info_response_title', bot_name=bot_name)
        desc = self._t(
            guild_id,
            'info_response_desc',
            ver=self.bot.ame_ver,
            addon=getattr(self.bot, 'ame_addon', '없음'),
        )
        await ctx.respond(f'{title}\n{desc}')


def setup(bot):
    bot.add_cog(info(bot))
