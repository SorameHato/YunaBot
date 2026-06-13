# coding: utf-8
from typing import Annotated

import discord
from discord.ext import commands

import lib_channel_check
import db_setting
import db_tone


def _profile_choices() -> list[discord.OptionChoice]:
    stems = sorted(
        db_tone.PROFILE_TEMPLATES.keys(),
        key=db_tone.get_profile_title,
    )
    return [
        discord.OptionChoice(name=db_tone.get_profile_title(stem), value=stem)
        for stem in stems
    ]


_BOT_OWNER_UID = 1470810710379466934


class setting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not getattr(bot, 'ame_color', None):
            bot.ame_color = 0xa57bdb

    async def _is_bot_admin(self, member: discord.Member) -> bool:
        try:
            admin_role_id = db_setting.get_setting(member.guild.id, 'bot_admin_role')
        except Exception:
            admin_role_id = None
        if member.id == member.guild.owner_id:
            return True
        if admin_role_id:
            if member.id == _BOT_OWNER_UID:
                return True
            role = member.guild.get_role(admin_role_id)
            return role is not None and role in member.roles
        permissions = getattr(member, 'guild_permissions', None)
        return bool(permissions and permissions.administrator)

    async def _require_admin(self, ctx) -> bool:
        if ctx.guild is None:
            await ctx.respond('서버에서만 사용할 수 있는 명령어에요.', ephemeral=True)
            return False
        if not isinstance(ctx.author, discord.Member):
            await ctx.respond('권한을 확인할 수 없어요.', ephemeral=True)
            return False
        if not await self._is_bot_admin(ctx.author):
            await ctx.respond('이 명령어는 서버 관리자 또는 봇 관리 역할이 있어야 사용할 수 있어요.', ephemeral=True)
            return False
        return True

    def _fmt_bool(self, value: int) -> str:
        return '켜짐' if value else '꺼짐'

    def _fmt_role(self, guild: discord.Guild, role_id: int | None) -> str:
        if not role_id:
            return '(미설정 — Discord 관리자)'
        role = guild.get_role(role_id)
        return role.mention if role else f'(삭제된 역할 ID {role_id})'

    def _fmt_channel(self, channel_id: int | None) -> str:
        if not channel_id:
            return '(미설정)'
        return f'<#{channel_id}>'

    def _build_status_embed(self, guild: discord.Guild) -> discord.Embed:
        settings = db_setting.get_all_settings(guild.id)
        exp_channel_label = lib_channel_check.format_exp_channel_status(
            self.bot,
            guild,
            settings.exp_channel,
        )
        exp_issue = lib_channel_check.exp_channel_issue(
            self.bot,
            guild,
            settings.exp_channel,
        )
        color = getattr(self.bot, 'ame_color', 0xa57bdb)
        if settings.exp_enable and exp_issue:
            color = 0xE67E22

        embed = discord.Embed(
            title='서버 설정',
            description='이 서버에서 사용되는 유나봇의 설정이에요.',
            color=color,
        )
        embed.add_field(
            name='초기 설정 완료',
            value=self._fmt_bool(settings.bot_enable),
            inline=True,
        )
        embed.add_field(
            name='경험치 기능',
            value=self._fmt_bool(settings.exp_enable),
            inline=True,
        )
        embed.add_field(
            name='언어팩 프로필',
            value=db_tone.get_profile_title(settings.tone_profile),
            inline=True,
        )
        embed.add_field(
            name='출석 알림 채널',
            value=exp_channel_label,
            inline=False,
        )
        embed.add_field(
            name='경험치 집계 대상 역할 (기본 유저 역할)',
            value=self._fmt_role(guild, settings.exp_role) if settings.exp_role else '(미설정 — 전체 멤버)',
            inline=False,
        )
        embed.add_field(
            name='봇 관리 역할',
            value=self._fmt_role(guild, settings.bot_admin_role),
            inline=False,
        )
        embed.add_field(
            name='로그 채널',
            value=self._fmt_channel(settings.bot_log_channel),
            inline=False,
        )
        if settings.exp_enable and exp_issue:
            embed.add_field(
                name='출석 알림 안내',
                value=exp_issue,
                inline=False,
            )
            embed.set_footer(text='`/설정 출석채널`로 출석 알림 채널을 지정·변경할 수 있어요.')
        return embed

    setting_commands = discord.SlashCommandGroup(
        name='설정',
        description='서버의 봇 설정을 조회·변경할 수 있어요. (관리자 전용)',
    )

    @setting_commands.command(name='조회', description='현재 서버 설정을 확인할 수 있어요.')
    async def show_settings(self, ctx):
        if not await self._require_admin(ctx):
            return
        await ctx.respond(embed=self._build_status_embed(ctx.guild))

    @setting_commands.command(name='경험치활성화', description='경험치 기능을 끄거나 켤 수 있어요.')
    async def set_exp_enable(
        self,
        ctx,
        enabled: Annotated[
            bool,
            discord.Option(bool, name='활성화', description='경험치 기능을 켤까요?'),
        ],
    ):
        if not await self._require_admin(ctx):
            return
        db_setting.update_setting(ctx.guild.id, 'exp_enable', enabled)
        state = '켰' if enabled else '껐'
        await ctx.respond(f'경험치 기능을 {state}어요.', ephemeral=True)

    @setting_commands.command(
        name='출석채널',
        description='출석 알림을 보낼 텍스트 채널을 변경할 수 있어요.',
    )
    async def set_exp_channel(
        self,
        ctx,
        channel: Annotated[
            discord.TextChannel,
            discord.Option(
                discord.TextChannel,
                name='채널',
                description='출석 알림을 보낼 텍스트 채널',
            ),
        ],
    ):
        if not await self._require_admin(ctx):
            return
        err = lib_channel_check.text_channel_send_issue(channel, ctx.guild)
        if err:
            await ctx.respond(
                f'{err}\n다른 텍스트 채널을 선택하거나, 봇에게 해당 채널의 보기·메시지 전송 권한을 부여해 주세요.',
                ephemeral=True,
            )
            return
        db_setting.update_setting(ctx.guild.id, 'exp_channel', channel.id)
        await ctx.respond(
            f'출석 알림 채널을 {channel.mention}으로 설정했어요.\n'
            f'경험치 기능이 꺼져 있다면 `/설정 경험치활성화`로 켤 수 있어요.',
            ephemeral=True,
        )

    @setting_commands.command(
        name='경험치역할',
        description='경험치를 집계할 기본 유저 역할을 변경할 수 있어요. 미지정 시 전체 멤버를 대상으로 집계할게요.',
    )
    async def set_exp_role(
        self,
        ctx,
        role: Annotated[
            discord.Role,
            discord.Option(discord.Role, name='역할', description='경험치 집계 대상 역할'),
        ],
    ):
        if not await self._require_admin(ctx):
            return
        db_setting.update_setting(ctx.guild.id, 'exp_role', role.id)
        await ctx.respond(
            f'경험치 집계 대상 역할을 {role.mention}으로 설정했어요.',
            ephemeral=True,
        )

    @setting_commands.command(
        name='경험치역할해제',
        description='경험치 집계 대상 역할 제한을 해제할 수 있어요. (전체 멤버를 대상으로 집계할게요.)',
    )
    async def clear_exp_role(self, ctx):
        if not await self._require_admin(ctx):
            return
        db_setting.update_setting(ctx.guild.id, 'exp_role', None)
        await ctx.respond('경험치 집계 대상 역할 제한을 해제했어요. 앞으로는 전체 멤버를 대상으로 집계할게요.', ephemeral=True)

    @setting_commands.command(
        name='관리자역할',
        description='봇 설정·알림 관리 등을 할 수 있는 관리자 역할을 변경할 수 있어요.',
    )
    async def set_admin_role(
        self,
        ctx,
        role: Annotated[
            discord.Role,
            discord.Option(discord.Role, name='역할', description='봇 관리자 역할을 선택해주세요.'),
        ],
    ):
        if not await self._require_admin(ctx):
            return
        db_setting.update_setting(ctx.guild.id, 'bot_admin_role', role.id)
        await ctx.respond(
            f'봇 관리자 역할을 {role.mention}으로 설정했어요.',
            ephemeral=True,
        )

    @setting_commands.command(
        name='관리자역할해제',
        description='봇 관리자 역할을 지정하지 않을 수 있어요. (Discord 관리자 권한으로 판단)',
    )
    async def clear_admin_role(self, ctx):
        if not await self._require_admin(ctx):
            return
        db_setting.update_setting(ctx.guild.id, 'bot_admin_role', None)
        await ctx.respond(
            '봇 관리자 역할을 지정 해제했어요. 앞으로는 Discord 관리자 권한으로 판단할게요.',
            ephemeral=True,
        )

    @setting_commands.command(
        name='로그채널',
        description='오류·실패·투명성 보고 알림을 보낼 텍스트 채널을 변경할 수 있어요.',
    )
    async def set_log_channel(
        self,
        ctx,
        channel: Annotated[
            discord.TextChannel,
            discord.Option(
                discord.TextChannel,
                name='채널',
                description='로그·오류 등을 알릴 채널',
            ),
        ],
    ):
        if not await self._require_admin(ctx):
            return
        err = lib_channel_check.text_channel_send_issue(channel, ctx.guild)
        if err:
            await ctx.respond(err, ephemeral=True)
            return
        db_setting.update_setting(ctx.guild.id, 'bot_log_channel', channel.id)
        await ctx.respond(
            f'로그 채널을 {channel.mention}으로 설정했어요.',
            ephemeral=True,
        )

    @setting_commands.command(
        name='언어팩',
        description='서버의 언어팩 프로필을 변경할 수 있어요.',
    )
    async def set_tone_profile(
        self,
        ctx,
        profile: Annotated[
            str,
            discord.Option(
                str,
                name='프로필',
                description='사용할 언어팩',
                choices=_profile_choices(),
            ),
        ],
    ):
        if not await self._require_admin(ctx):
            return
        try:
            db_setting.update_setting(ctx.guild.id, 'tone_profile', profile)
        except db_setting.SettingValidationError as exc:
            await ctx.respond(str(exc), ephemeral=True)
            return
        await ctx.respond(
            f'언어팩 프로필을 `{db_tone.get_profile_title(profile)}`(으)로 변경했어요. 대사는 잠시 후 변경될 거에요.',
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(setting(bot))
