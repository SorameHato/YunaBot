# coding: utf-8
import discord
from discord.ext import commands

from DB import db_setting, db_tone
from Library import lib_cog_scope, lib_cog_tone


class info(lib_cog_tone.ToneAwareCog, commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def _guild_id(ctx) -> int:
        if ctx.guild is not None:
            return ctx.guild.id
        return 0

    async def _send_error_fallback(self, guild_id: int, message: str, embed: discord.Embed) -> None:
        channel = None
        if guild_id:
            log_channel_id = db_setting.get_setting(guild_id, 'bot_log_channel')
            if log_channel_id:
                channel = self.bot.get_channel(log_channel_id)
        if channel is None:
            dbg_channel_id = getattr(self.bot, 'dbgChannel', None)
            if dbg_channel_id is not None:
                try:
                    channel = await self.bot.fetch_channel(dbg_channel_id)
                except Exception as exc:
                    print(f'[c_info] dbgChannel fetch failed: {exc}')
                    print(f'[c_info] error fallback: {message}')
                    return
        if channel is None:
            print(f'[c_info] no log/dbg channel; error fallback: {message}')
            return
        try:
            await channel.send(message, embed=embed)
        except Exception as exc:
            print(f'[c_info] channel.send failed: {exc}')
            print(f'[c_info] error fallback: {message}')

    @commands.Cog.listener()
    async def on_application_command_error(self, ctx, error):
        guild_id = self._guild_id(ctx)
        color = db_setting.get_embed_color(guild_id) if guild_id else db_setting.DEFAULT_EMBED_COLOR
        command_label = (
            ctx.command.qualified_name
            if ctx.command
            else self._t(guild_id, 'error_embed_field2_unknown')
        )

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
        embed.set_footer(text=db_tone.render_embed_footer(guild_id, self.bot.ame_ver))
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
        color = db_setting.get_embed_color(guild_id) if guild_id else db_setting.DEFAULT_EMBED_COLOR
        bot_name = db_tone.render_name(guild_id)
        title = self._t(guild_id, 'info_response_title', bot_name=bot_name)
        addon_no = lib_cog_scope.addon_no_for_guild(self.bot, guild_id or None)
        addon_text = ''
        if addon_no is not None:
            addon_text = self._t(guild_id, 'info_response_addon', addon_no=addon_no)
        desc = self._t(
            guild_id,
            'info_response_desc',
            ver=self.bot.ame_ver,
            addon=addon_text,
        )

        embed = discord.Embed(
            title=title,
            description=desc,
            color=color,
        )
        embed.add_field(
            name=self._t(guild_id, 'info_response_field1_title'),
            value=self._t(
                guild_id,
                'info_response_field1_value',
                loaded_time=getattr(self.bot, 'loadedTime', ''),
            ),
            inline=False,
        )
        embed.add_field(
            name=self._t(guild_id, 'info_response_field2_title'),
            value=self._t(guild_id, 'info_response_field2_value'),
            inline=False,
        )
        embed.set_footer(text=db_tone.render_embed_footer(guild_id, self.bot.ame_ver))
        await ctx.respond(embed=embed)


def setup(bot):
    bot.add_cog(info(bot))
