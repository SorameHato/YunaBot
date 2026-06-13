# coding: utf-8
from typing import Annotated, Optional

import discord
from discord.ext import commands

import lib_channel_check
import db_setting
import lib_slash_guild_sync


def _guild_join_message(guild_name: str) -> str:
    return (
        f'처음 뵙겠습니다, 치쿠마 유나라고 해요! **{guild_name}**에 유나봇이 추가되었어요.\n'
        f'유나봇은 초기 설정이 필요해요. 먼저, 서버 소유자님께서 `/초기설정` 명령을 실행해 주세요.\n'
        f'## 1. `/초기설정 일반`\n * 로그 채널 (필수) : 오류 보고서, 투명성 보고서 등 여러 로그를 보낼 채널을 선택해 주세요.\n * 관리자 역할 (선택) : 이 서버의 관리자에게 부여한 역할을 선택해 주세요. 설정 변경과 일일알림 강제 수정/삭제 같은 몇몇 명령어는 해당 권한이 있는 분만 사용하실 수 있어요. 만약 선택하지 않은 경우, 관리자 권한이 있는지를 기준으로 확인할게요.\n'
        f'## 2. `/초기설정 경험치`\n * 활성화 여부 (필수) : 경험치 기능을 활성화할 지 선택해 주세요.\n * 출석 메세지를 보낼 채널 (선택) : 출석이 완료되었다는 메세지를 보낼 채널을 선택해주세요. 만약 선택하지 않은 경우, 출석 메세지를 보내지 않아요.\n * 기본 유저 역할 (선택) : 인증방 기능을 사용하고 계신 경우, 인증방을 통과한 모든 유저에게 부여되는 역할을 선택해주세요. 인증방을 통과한 유저만 경험치를 집계할게요. 만약 선택하지 않은 경우(인증방이 없는 경우 등), 모든 유저를 대상으로 집계할게요.\n'
        f'## 3. `/초기설정 완료`\n모든 설정을 완료하신 후 입력하시면 바로 유나봇을 쓸 수 있게 도와드릴게요.'
    )


class onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not getattr(bot, 'ame_color', None):
            bot.ame_color = 0xa57bdb

    async def _resolve_guild_owner(self, guild: discord.Guild) -> discord.User | None:
        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_owner()
            except Exception:
                owner = None
        return owner

    def _first_private_thread_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        me = guild.me
        if me is None:
            return None
        for channel in guild.text_channels:
            if lib_channel_check.text_channel_send_issue(channel, guild) is not None:
                continue
            if not channel.permissions_for(me).create_private_threads:
                continue
            return channel
        return None

    async def _send_join_welcome_dm(self, guild: discord.Guild) -> None:
        owner = await self._resolve_guild_owner(guild)
        if owner is None:
            return

        guide_text = _guild_join_message(guild.name)
        try:
            await owner.send(guide_text)
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f'[onboarding] DM failed guild={guild.id}: {exc}')
            await self._send_join_welcome_private_thread_fallback(guild, owner, guide_text)
        except Exception as exc:
            print(f'[onboarding] DM failed guild={guild.id}: {exc}')
            await self._send_join_welcome_private_thread_fallback(guild, owner, guide_text)

    async def _send_join_welcome_system_channel_fallback(
        self,
        guild: discord.Guild,
        owner: discord.User,
        guide_text: str,
    ) -> None:
        channel = guild.system_channel
        if channel is None:
            print(f'[onboarding] system channel fallback skipped, no system channel guild={guild.id}')
            return

        err = lib_channel_check.text_channel_send_issue(channel, guild)
        if err:
            print(f'[onboarding] system channel fallback skipped guild={guild.id}: {err}')
            return

        try:
            await channel.send(
                f'{owner.mention}\n{guide_text}',
                allowed_mentions=discord.AllowedMentions(users=[owner]),
            )
        except Exception as exc:
            print(f'[onboarding] system channel fallback failed guild={guild.id}: {exc}')

    async def _send_join_welcome_private_thread_fallback(
        self,
        guild: discord.Guild,
        owner: discord.User,
        guide_text: str,
    ) -> None:
        channel = self._first_private_thread_channel(guild)
        if channel is not None:
            try:
                thread = await channel.create_thread(
                    name='봇 초기 설정 안내',
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    auto_archive_duration=10080,
                )
                await thread.add_user(owner)
                await thread.send(
                    f'{owner.mention}\n{guide_text}',
                    allowed_mentions=discord.AllowedMentions(users=[owner]),
                )
                return
            except Exception as exc:
                print(f'[onboarding] private thread fallback failed guild={guild.id}: {exc}')

        await self._send_join_welcome_system_channel_fallback(guild, owner, guide_text)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        db_setting.ensure_guild(guild.id)
        try:
            await lib_slash_guild_sync.sync_guild_commands(self.bot, guild.id)
        except Exception as exc:
            print(f'[slash_guild] join sync failed for {guild.id}: {exc}')
        await self._send_join_welcome_dm(guild)

    async def _require_owner(self, ctx) -> bool:
        if ctx.guild is None:
            await ctx.respond('서버에서만 사용할 수 있는 명령어에요.', ephemeral=True)
            return False
        if ctx.author.id != ctx.guild.owner_id:
            await ctx.respond('서버 소유자만 사용할 수 있어요.', ephemeral=True)
            return False
        return True

    onboarding_commands = discord.SlashCommandGroup(
        name='초기설정',
        description='유나봇의 초기 필수 설정을 진행할 수 있어요. (서버 소유자 전용)',
    )

    @onboarding_commands.command(
        name='일반',
        description='로그 채널과 관리자 역할을 설정할 수 있어요.',
    )
    async def setup_general(
        self,
        ctx,
        log_channel: Annotated[
            discord.TextChannel,
            discord.Option(
                discord.TextChannel,
                name='로그채널',
                description='오류·실패·투명성 보고 등의 알림을 보낼 채널 (필수)',
            ),
        ],
        admin_role: Annotated[
            Optional[discord.Role],
            discord.Option(
                discord.Role,
                name='관리자역할',
                description='봇 설정·알림 관리 등을 할 수 있는 역할 (선택, 미입력 시 Discord 관리자 권한 확인)',
                required=False,
            ),
        ] = None,
    ):
        if not await self._require_owner(ctx):
            return
        if db_setting.get_setting(ctx.guild.id, 'bot_enable'):
            await ctx.respond('이미 초기 설정이 완료된 서버예요.', ephemeral=True)
            return

        err = lib_channel_check.text_channel_send_issue(log_channel, ctx.guild)
        if err:
            await ctx.respond(
                f'{err}\n다른 텍스트 채널을 선택하거나, 봇에게 해당 채널의 보기·메시지 전송 권한을 부여해 주세요.',
                ephemeral=True,
            )
            return

        db_setting.update_setting(ctx.guild.id, 'bot_log_channel', log_channel.id)
        if admin_role is None:
            db_setting.update_setting(ctx.guild.id, 'bot_admin_role', None)
            role_text = 'Discord 관리자 권한'
        else:
            db_setting.update_setting(ctx.guild.id, 'bot_admin_role', admin_role.id)
            role_text = admin_role.mention

        await ctx.respond(
            f'일반 설정을 저장했어요.\n'
            f'- 로그 채널: {log_channel.mention}\n'
            f'- 관리 역할: {role_text}\n'
            f'다음으로 `/초기설정 경험치`를 실행해 주세요.',
            ephemeral=True,
        )

    @onboarding_commands.command(
        name='경험치',
        description='경험치 기능과 출석 알림 채널을 설정할 수 있어요.',
    )
    async def setup_exp(
        self,
        ctx,
        enable_choice: Annotated[
            int,
            discord.Option(
                int,
                name='활성화여부',
                description='경험치 기능 사용 여부 (필수)',
                choices=[
                    discord.OptionChoice('활성화', value=1),
                    discord.OptionChoice('비활성화', value=0),
                ],
            ),
        ],
        exp_channel: Annotated[
            Optional[discord.TextChannel],
            discord.Option(
                discord.TextChannel,
                name='출석메세지채널',
                description='출석 메시지를 보낼 채널 (선택, 미입력 시 출석 메시지를 보내지 않음)',
                required=False,
            ),
        ] = None,
        exp_role: Annotated[
            Optional[discord.Role],
            discord.Option(
                discord.Role,
                name='기본유저역할',
                description='인증방이 있는 경우, 인증방을 통과한 모든 유저에게 부여되는 역할 (선택, 해당 역할이 있는 유저만 집계, 미입력 시 전체 멤버)',
                required=False,
            ),
        ] = None,
    ):
        if not await self._require_owner(ctx):
            return
        if db_setting.get_setting(ctx.guild.id, 'bot_enable'):
            await ctx.respond('이미 초기 설정이 완료된 서버예요.', ephemeral=True)
            return

        if exp_channel is not None:
            err = lib_channel_check.text_channel_send_issue(exp_channel, ctx.guild)
            if err:
                await ctx.respond(
                    f'{err}\n출석 메시지를 보낼 수 있는 텍스트 채널을 다시 선택해 주세요.',
                    ephemeral=True,
                )
                return
            channel_text = exp_channel.mention
        else:
            channel_text = '(미설정 — 출석 메시지를 보내지 않음)'

        db_setting.update_setting(ctx.guild.id, 'exp_enable', enable_choice)
        db_setting.update_setting(
            ctx.guild.id,
            'exp_channel',
            exp_channel.id if exp_channel is not None else None,
        )
        if exp_role is None:
            db_setting.update_setting(ctx.guild.id, 'exp_role', None)
            role_text = '전체 멤버'
        else:
            db_setting.update_setting(ctx.guild.id, 'exp_role', exp_role.id)
            role_text = exp_role.mention

        state = '활성화' if enable_choice else '비활성화'
        await ctx.respond(
            f'경험치 설정을 저장했어요.\n'
            f'- 경험치 기능: {state}\n'
            f'- 출석 메세지를 보낼 채널: {channel_text}\n'
            f'- 기본 유저 역할: {role_text}\n'
            f'모든 항목을 입력했다면 `/초기설정 완료`를 실행해 주세요.',
            ephemeral=True,
        )

    @onboarding_commands.command(
        name='완료',
        description='필수 설정이 모두 들어갔는지 확인하고 초기 설정을 마무리할 수 있어요.',
    )
    async def setup_complete(self, ctx):
        if not await self._require_owner(ctx):
            return
        guild = ctx.guild
        guild_id = guild.id

        if db_setting.get_setting(guild_id, 'bot_enable'):
            await ctx.respond('이미 초기 설정이 완료된 서버예요.', ephemeral=True)
            return

        settings = db_setting.get_all_settings(guild_id)
        missing = []
        if not settings.bot_log_channel:
            missing.append('`/초기설정 일반` — 로그 채널')
        if missing:
            await ctx.respond(
                '아직 필수 설정이 빠져 있어요.\n- ' + '\n- '.join(missing),
                ephemeral=True,
            )
            return

        log_channel = self.bot.get_channel(settings.bot_log_channel)
        if log_channel is None:
            await ctx.respond('설정된 로그 채널을 찾을 수 없어요.', ephemeral=True)
            return
        log_issue = lib_channel_check.configured_text_channel_issue(
            self.bot,
            guild,
            settings.bot_log_channel,
            unset_message='로그 채널이 설정되지 않았어요. `/초기설정 일반`을 먼저 실행해 주세요.',
            missing_message=(
                '설정된 로그 채널을 찾을 수 없어요. `/초기설정 일반`으로 다시 지정해 주세요.'
            ),
        )
        if log_issue:
            await ctx.respond(f'로그 채널을 사용할 수 없어요.\n{log_issue}', ephemeral=True)
            return

        if settings.exp_channel:
            exp_issue = lib_channel_check.exp_channel_issue(
                self.bot,
                guild,
                settings.exp_channel,
            )
            if exp_issue:
                await ctx.respond(f'출석 채널을 사용할 수 없어요.\n{exp_issue}', ephemeral=True)
                return

        try:
            db_setting.mark_setup_complete(guild_id)
        except db_setting.SettingValidationError as exc:
            await ctx.respond(str(exc), ephemeral=True)
            return

        try:
            await lib_slash_guild_sync.sync_guild_commands(self.bot, guild_id)
        except Exception as exc:
            print(f'[slash_guild] post-setup sync failed guild={guild_id}: {exc}')
            await ctx.respond(
                '초기 설정은 저장됐지만 명령어 목록 갱신에 실패했어요. '
                '잠시 후 `/초기설정 완료`를 다시 실행하거나 봇을 재시작해 주세요.',
                ephemeral=True,
            )
            return

        await ctx.respond(
            '초기 설정을 완료했어요! 이제 `/정보`, `/경험치`, `/알림`, `/설정` 명령을 사용할 수 있어요.',
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(onboarding(bot))
