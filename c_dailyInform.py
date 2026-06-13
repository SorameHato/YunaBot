# coding: utf-8
import discord
from discord.ext import commands, tasks
from datetime import datetime as dt
from datetime import timedelta as td
from datetime import timezone as tz
from typing import Annotated

import db_dailyInform
import db_setting
import db_tone
import lib_member_label

_BTN_EDIT_DEFAULT = db_tone.render_default_message('dailyInform_btn_edit')
_BTN_CANCEL_DEFAULT = db_tone.render_default_message('dailyInform_btn_cancel')


class _DailyInformConfirmView(discord.ui.View):
    def __init__(
        self,
        cog,
        requester_id: int,
        row: db_dailyInform.DailyInformRow,
        action: str,
        new_time_min: int = None,
        new_message: str = None,
    ):
        super().__init__(timeout=60)
        self.cog = cog
        self.requester_id = requester_id
        self.row_id = row.id
        self.guild_id = row.guild
        self.author_id = row.author
        self.old_time_min = row.time_min
        self.old_message = row.message
        self.action = action
        self.new_time_min = new_time_min
        self.new_message = new_message

        self.confirm_button.label = (
            cog._t(self.guild_id, 'dailyInform_btn_delete')
            if action == 'delete'
            else cog._t(self.guild_id, 'dailyInform_btn_edit')
        )
        self.confirm_button.style = (
            discord.ButtonStyle.danger
            if action == 'delete'
            else discord.ButtonStyle.primary
        )
        self.cancel_button.label = cog._t(self.guild_id, 'dailyInform_btn_cancel')

    async def _send_permission_error(self, interaction: discord.Interaction):
        verb = (
            self.cog._t(self.guild_id, 'dailyInform_btn_delete')
            if self.action == 'delete'
            else self.cog._t(self.guild_id, 'dailyInform_btn_edit')
        )
        owner = await self.cog._author_label(interaction.guild, self.author_id)
        await interaction.response.send_message(
            self.cog._t(self.guild_id, 'dailyInform_perm_denied', owner=owner, verb=verb),
            ephemeral=True,
        )

    async def _can_press(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        if await self.cog._can_manage_row(interaction.user, self.author_id):
            return True
        await self._send_permission_error(interaction)
        return False

    @discord.ui.button(label=_BTN_EDIT_DEFAULT, style=discord.ButtonStyle.primary)
    async def confirm_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._can_press(interaction):
            return

        row = db_dailyInform.get_message_by_id(self.guild_id, self.row_id)
        if row is None:
            await interaction.response.edit_message(
                content=self.cog._t(self.guild_id, 'dailyInform_confirm_already_deleted'),
                view=None,
            )
            return

        try:
            last_editor = 0 if self.requester_id == self.author_id else self.requester_id
            if self.action == 'time':
                db_dailyInform.update_message_time(
                    self.guild_id,
                    self.row_id,
                    self.new_time_min,
                    last_editor=last_editor,
                )
                content = self.cog._t(
                    self.guild_id,
                    'dailyInform_edit_time_success',
                    message=row.message,
                    new_time=self.cog._format_time_text(self.guild_id, self.new_time_min),
                )
            elif self.action == 'message':
                db_dailyInform.update_message_text(
                    self.guild_id,
                    self.row_id,
                    self.new_message,
                    last_editor=last_editor,
                )
                content = self.cog._t(
                    self.guild_id,
                    'dailyInform_edit_msg_success',
                    time=self.cog._format_time_text(self.guild_id, row.time_min),
                    new_message=self.new_message,
                )
            else:
                db_dailyInform.delete_message_by_id(self.guild_id, self.row_id)
                content = self.cog._t(
                    self.guild_id,
                    'dailyInform_delete_success',
                    message=row.message,
                )
        except db_dailyInform.DuplicateDailyInformError:
            content = self.cog._t(
                self.guild_id,
                'dailyInform_add_duplicate',
                time=self.cog._format_time_text(self.guild_id, self.new_time_min),
            )

        await interaction.response.edit_message(content=content, view=None)

    @discord.ui.button(label=_BTN_CANCEL_DEFAULT, style=discord.ButtonStyle.secondary)
    async def cancel_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._can_press(interaction):
            return
        await interaction.response.edit_message(
            content=self.cog._t(self.guild_id, 'dailyInform_confirm_cancelled'),
            view=None,
        )


class dailyInform(commands.Cog):
    _ALERTS_PER_PAGE = 5

    def __init__(self, bot):
        self.bot: discord.Bot = bot
        self._last_sent_key = None
        self._alerted = {}
        self._alert_cooldown = td(hours=1)
        try:
            db_dailyInform.ensure_schema()
        except Exception as e:
            print(f'dailyInform: schema init failed: {e}')
        self.daily_inform.start()

    def _t(self, guild_id: int, message_key: str, **kwargs) -> str:
        return db_tone.render_message(guild_id, message_key, **kwargs)

    def _fail_reason_label(self, guild_id: int, reason: str) -> str:
        key = f'dailyInform_fail_reason_{reason}'
        label = self._t(guild_id, key)
        return reason if label == key else label

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.daily_inform_count = self.daily_inform.current_loop
        self.bot.daily_inform_next = (
            self.daily_inform.next_iteration.astimezone(tz=tz(td(hours=9)))
            if self.daily_inform.next_iteration is not None
            else None
        )

    @tasks.loop(seconds=1.0)
    async def daily_inform(self):
        now = dt.now(tz=tz(td(hours=9)))
        current_minute = now.replace(second=0, microsecond=0)
        current_key = self._make_key(current_minute)
        if self._last_sent_key == current_key:
            return

        if self._last_sent_key is None:
            send_minute = current_minute
        else:
            last_dt = self._key_to_dt(self._last_sent_key)
            if current_minute <= last_dt:
                return
            send_minute = last_dt + td(minutes=1)

        send_counts = {}

        while send_minute <= current_minute:
            minute_of_day = send_minute.hour * 60 + send_minute.minute
            try:
                rows = db_dailyInform.get_messages_by_time(minute_of_day)
            except Exception as e:
                print(f'dailyInform: DB error: {e}')
                break

            for row in rows:
                guild_id = row.guild
                channel_id = row.channel
                message = row.message
                if send_counts.get(guild_id, 0) >= 7:
                    continue
                if not message:
                    continue
                channel = self.bot.get_channel(channel_id)
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(channel_id)
                    except discord.Forbidden as e:
                        await self._notify_send_failure(guild_id, channel_id, 'fetch_forbidden', str(e))
                        continue
                    except discord.NotFound as e:
                        await self._notify_send_failure(guild_id, channel_id, 'channel_not_found', str(e))
                        continue
                    except Exception as e:
                        print(f'dailyInform: channel fetch failed: {e}')
                        continue
                if getattr(channel, 'guild', None) and channel.guild and channel.guild.id != guild_id:
                    continue
                try:
                    await channel.send(message)
                    send_counts[guild_id] = send_counts.get(guild_id, 0) + 1
                except discord.Forbidden as e:
                    await self._notify_send_failure(guild_id, channel_id, 'send_forbidden', str(e))
                except Exception as e:
                    if isinstance(e, discord.NotFound):
                        await self._notify_send_failure(guild_id, channel_id, 'channel_not_found', str(e))
                    else:
                        print(f'dailyInform: send failed: {e}')
                    continue

            self._last_sent_key = (send_minute.year, send_minute.month, send_minute.day, minute_of_day)
            send_minute += td(minutes=1)

        self._update_task_meta()

    def _update_task_meta(self):
        self.bot.daily_inform_count = self.daily_inform.current_loop + 1
        self.bot.daily_inform_next = (
            self.daily_inform.next_iteration.astimezone(tz=tz(td(hours=9)))
            if self.daily_inform.next_iteration is not None
            else None
        )

    def _should_alert(self, guild_id: int, channel_id: int, reason: str, now: dt) -> bool:
        key = (guild_id, channel_id, reason)
        last = self._alerted.get(key)
        if last and (now - last) < self._alert_cooldown:
            return False
        self._alerted[key] = now
        return True

    async def _get_guild_owner_user(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except Exception:
                return None
        owner_id = getattr(guild, 'owner_id', None)
        if owner_id is None:
            return None
        user = self.bot.get_user(owner_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(owner_id)
            except Exception:
                return None
        return user

    async def _notify_send_failure(self, guild_id: int, channel_id: int, reason: str, detail: str = None):
        now = dt.now(tz=tz(td(hours=9)))
        if not self._should_alert(guild_id, channel_id, reason, now):
            return
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except Exception:
                guild = None
        if guild is not None and getattr(guild, 'name', None):
            guild_name = guild.name
        else:
            guild_name = self._t(guild_id, 'dailyInform_guild_unknown', guild_id=guild_id)
        msg = self._t(
            guild_id,
            'dailyInform_send_failure',
            guild_name=guild_name,
            channel_id=channel_id,
            reason=self._fail_reason_label(guild_id, reason),
        )
        if detail:
            msg += self._t(guild_id, 'dailyInform_send_failure_detail', detail=detail)

        dm_sent = False
        owner = await self._get_guild_owner_user(guild_id)
        if owner is not None:
            try:
                await owner.send(msg)
                dm_sent = True
            except Exception:
                dm_sent = False

        if dm_sent:
            return

        try:
            log_channel_id = db_setting.get_setting(guild_id, 'bot_log_channel')
        except Exception:
            return
        if not log_channel_id:
            return
        channel = self.bot.get_channel(log_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(log_channel_id)
            except Exception:
                return
        try:
            await channel.send(msg)
        except Exception:
            return

    def _parse_time_min(self, time_value: int):
        if time_value < 0 or time_value > 2359:
            return None
        hour = time_value // 100
        minute = time_value % 100
        if hour > 23 or minute > 59:
            return None
        return hour * 60 + minute

    def _format_time_text(self, guild_id: int, time_min: int) -> str:
        return self._t(
            guild_id,
            'dailyInform_time_text',
            hour=time_min // 60,
            minute=time_min % 60,
        )

    def _format_time_clock(self, time_min: int) -> str:
        return f'{time_min // 60:02d}:{time_min % 60:02d}'

    def _guild_only(self, ctx) -> bool:
        return ctx.guild is not None

    async def _is_bot_admin(self, member: discord.Member) -> bool:
        try:
            admin_role_id = db_setting.get_setting(member.guild.id, 'bot_admin_role')
        except Exception:
            admin_role_id = None
        if member.id == member.guild.owner_id:
            return True
        if admin_role_id:
            role = member.guild.get_role(admin_role_id)
            return role is not None and role in member.roles
        permissions = getattr(member, 'guild_permissions', None)
        return bool(permissions and permissions.administrator)

    async def _can_manage_row(self, user, author_id: int) -> bool:
        if author_id and user.id == author_id:
            return True
        if isinstance(user, discord.Member):
            return await self._is_bot_admin(user)
        return False

    async def _author_label(self, guild: discord.Guild, author_id: int) -> str:
        guild_id = guild.id if guild is not None else 0
        if not author_id:
            return self._t(guild_id, 'dailyInform_author_unknown')
        member = None
        if guild is not None:
            member = guild.get_member(author_id)
            if member is None:
                try:
                    member = await guild.fetch_member(author_id)
                except Exception:
                    member = None
        user = member or self.bot.get_user(author_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(author_id)
            except Exception:
                user = None
        if user is None:
            return self._t(guild_id, 'dailyInform_author_id', author_id=author_id)

        return lib_member_label.format_user_label(user)

    def _user_mention(self, guild_id: int, user_id: int) -> str:
        if not user_id:
            return self._t(guild_id, 'dailyInform_author_unknown')
        return f'<@{user_id}>'

    def _format_list_authors(
        self,
        guild_id: int,
        row: db_dailyInform.DailyInformRow,
    ) -> str:
        author = self._user_mention(guild_id, row.author)
        if not row.last_editor:
            return self._t(guild_id, 'dailyInform_list_authors_only', author=author)
        editor = self._user_mention(guild_id, row.last_editor)
        return self._t(
            guild_id,
            'dailyInform_list_authors_with_editor',
            author=author,
            editor=editor,
        )

    def _format_list_line(
        self,
        guild_id: int,
        order: int,
        row: db_dailyInform.DailyInformRow,
    ) -> str:
        return self._t(
            guild_id,
            'dailyInform_list_line',
            order=order,
            id=row.id,
            message=row.message,
            time=self._format_time_clock(row.time_min),
            authors=self._format_list_authors(guild_id, row),
        )

    async def _respond_missing_guild(self, ctx):
        guild_id = ctx.guild.id if ctx.guild else 0
        await ctx.respond(self._t(guild_id, 'dailyInform_guild_only'), ephemeral=True)

    async def _respond_invalid_time(self, ctx):
        guild_id = ctx.guild.id if ctx.guild else 0
        await ctx.respond(self._t(guild_id, 'dailyInform_invalid_time'), ephemeral=True)

    async def _get_manage_target(self, ctx, row_id: int, verb: str):
        if not self._guild_only(ctx):
            await self._respond_missing_guild(ctx)
            return None

        guild_id = ctx.guild.id
        row = db_dailyInform.get_message_by_id(guild_id, row_id)
        if row is None:
            await ctx.respond(self._t(guild_id, 'dailyInform_not_found'), ephemeral=True)
            return None

        if not await self._can_manage_row(ctx.author, row.author):
            owner = await self._author_label(ctx.guild, row.author)
            await ctx.respond(
                self._t(guild_id, 'dailyInform_perm_denied', owner=owner, verb=verb),
                ephemeral=True,
            )
            return None
        return row

    daily_inform_commands = discord.SlashCommandGroup(
        name='알림',
        description=db_tone.render_default_message('dailyInform_group_desc'),
    )

    @daily_inform_commands.command(
        name='등록',
        description=db_tone.render_default_message('dailyInform_add_desc'),
    )
    async def add_daily_inform(
        self,
        ctx,
        time_value: Annotated[
            int,
            discord.Option(
                int,
                name=db_tone.render_default_message('dailyInform_add_option1_name'),
                description=db_tone.render_default_message('dailyInform_add_option1_desc'),
                min_value=0,
                max_value=2359,
            ),
        ],
        message: Annotated[
            str,
            discord.Option(
                str,
                name=db_tone.render_default_message('dailyInform_add_option_message_name'),
                description=db_tone.render_default_message('dailyInform_add_option_message_desc'),
            ),
        ],
    ):
        if not self._guild_only(ctx):
            await self._respond_missing_guild(ctx)
            return

        guild_id = ctx.guild.id
        time_min = self._parse_time_min(time_value)
        if time_min is None:
            await self._respond_invalid_time(ctx)
            return

        message = message.strip()
        if not message:
            await ctx.respond(self._t(guild_id, 'dailyInform_add_empty_message'), ephemeral=True)
            return

        try:
            db_dailyInform.add_message(
                guild_id,
                time_min,
                ctx.channel.id,
                ctx.author.id,
                message,
            )
        except db_dailyInform.DuplicateDailyInformError:
            await ctx.respond(
                self._t(
                    guild_id,
                    'dailyInform_add_duplicate',
                    time=self._format_time_text(guild_id, time_min),
                ),
                ephemeral=True,
            )
            return

        await ctx.respond(
            self._t(
                guild_id,
                'dailyInform_add_success',
                time=self._format_time_text(guild_id, time_min),
                message=message,
            ),
            ephemeral=True,
        )

    @daily_inform_commands.command(
        name='조회',
        description=db_tone.render_default_message('dailyInform_list_desc'),
    )
    async def list_daily_inform(
        self,
        ctx,
        page: Annotated[
            int,
            discord.Option(
                int,
                name=db_tone.render_default_message('dailyInform_list_option1_name'),
                description=db_tone.render_default_message('dailyInform_list_option1_desc'),
                min_value=1,
                default=1,
            ),
        ] = 1,
    ):
        if not self._guild_only(ctx):
            await self._respond_missing_guild(ctx)
            return

        guild_id = ctx.guild.id
        rows = db_dailyInform.get_messages_by_guild(guild_id)
        total = len(rows)
        if total == 0:
            await ctx.respond(self._t(guild_id, 'dailyInform_list_empty'), ephemeral=True)
            return

        start = (page - 1) * self._ALERTS_PER_PAGE
        end = min(start + self._ALERTS_PER_PAGE, total)
        if start >= total:
            await ctx.respond(
                self._t(guild_id, 'dailyInform_list_page_empty', page=page),
                ephemeral=True,
            )
            return

        lines = [
            self._format_list_line(guild_id, index, row)
            for index, row in enumerate(rows[start:end], start=start + 1)
        ]
        content = (
            self._t(
                guild_id,
                'dailyInform_list_header',
                total=total,
                start=start + 1,
                end=end,
            )
            + '\n'
            + '\n'.join(lines)
        )
        await ctx.respond(content, ephemeral=True)

    @daily_inform_commands.command(
        name='시간수정',
        description=db_tone.render_default_message('dailyInform_edit_desc_time'),
    )
    async def update_daily_inform_time(
        self,
        ctx,
        row_id: Annotated[
            int,
            discord.Option(
                int,
                name=db_tone.render_default_message('dailyInform_edit_option1_name'),
                description=db_tone.render_default_message('dailyInform_edit_option1_desc'),
                min_value=1,
            ),
        ],
        time_value: Annotated[
            int,
            discord.Option(
                int,
                name=db_tone.render_default_message('dailyInform_edit_option2_time_name'),
                description=db_tone.render_default_message('dailyInform_edit_option2_time_desc'),
                min_value=0,
                max_value=2359,
            ),
        ],
    ):
        guild_id = ctx.guild.id
        row = await self._get_manage_target(
            ctx,
            row_id,
            self._t(guild_id, 'dailyInform_btn_edit'),
        )
        if row is None:
            return

        time_min = self._parse_time_min(time_value)
        if time_min is None:
            await self._respond_invalid_time(ctx)
            return

        if any(
            item.time_min == time_min and item.id != row.id
            for item in db_dailyInform.get_messages_by_guild(guild_id)
        ):
            await ctx.respond(
                self._t(
                    guild_id,
                    'dailyInform_add_duplicate',
                    time=self._format_time_text(guild_id, time_min),
                ),
                ephemeral=True,
            )
            return

        view = _DailyInformConfirmView(
            self,
            ctx.author.id,
            row,
            action='time',
            new_time_min=time_min,
        )
        await ctx.respond(
            self._t(
                guild_id,
                'dailyInform_edit_time_confirm',
                message=row.message,
                time=self._format_time_text(guild_id, row.time_min),
                new_time=self._format_time_text(guild_id, time_min),
            ),
            view=view,
            ephemeral=True,
        )

    @daily_inform_commands.command(
        name='내용수정',
        description=db_tone.render_default_message('dailyInform_edit_desc_msg'),
    )
    async def update_daily_inform_message(
        self,
        ctx,
        row_id: Annotated[
            int,
            discord.Option(
                int,
                name=db_tone.render_default_message('dailyInform_edit_option1_name'),
                description=db_tone.render_default_message('dailyInform_edit_option1_desc'),
                min_value=1,
            ),
        ],
        message: Annotated[
            str,
            discord.Option(
                str,
                name=db_tone.render_default_message('dailyInform_edit_option2_msg_name'),
                description=db_tone.render_default_message('dailyInform_edit_option2_msg_desc'),
            ),
        ],
    ):
        guild_id = ctx.guild.id
        row = await self._get_manage_target(
            ctx,
            row_id,
            self._t(guild_id, 'dailyInform_btn_edit'),
        )
        if row is None:
            return

        message = message.strip()
        if not message:
            await ctx.respond(self._t(guild_id, 'dailyInform_edit_msg_empty'), ephemeral=True)
            return

        view = _DailyInformConfirmView(
            self,
            ctx.author.id,
            row,
            action='message',
            new_message=message,
        )
        await ctx.respond(
            self._t(
                guild_id,
                'dailyInform_edit_msg_confirm',
                time=self._format_time_text(guild_id, row.time_min),
                message=row.message,
                new_message=message,
            ),
            view=view,
            ephemeral=True,
        )

    @daily_inform_commands.command(
        name='삭제',
        description=db_tone.render_default_message('dailyInform_delete_desc'),
    )
    async def delete_daily_inform(
        self,
        ctx,
        row_id: Annotated[
            int,
            discord.Option(
                int,
                name=db_tone.render_default_message('dailyInform_delete_option1_name'),
                description=db_tone.render_default_message('dailyInform_delete_option1_desc'),
                min_value=1,
            ),
        ],
    ):
        guild_id = ctx.guild.id
        row = await self._get_manage_target(
            ctx,
            row_id,
            self._t(guild_id, 'dailyInform_btn_delete'),
        )
        if row is None:
            return

        view = _DailyInformConfirmView(
            self,
            ctx.author.id,
            row,
            action='delete',
        )
        await ctx.respond(
            self._t(
                guild_id,
                'dailyInform_delete_confirm',
                time=self._format_time_text(guild_id, row.time_min),
                message=row.message,
            ),
            view=view,
            ephemeral=True,
        )

    def _make_key(self, when: dt):
        minute_of_day = when.hour * 60 + when.minute
        return (when.year, when.month, when.day, minute_of_day)

    def _key_to_dt(self, key):
        year, month, day, minute_of_day = key
        hour = minute_of_day // 60
        minute = minute_of_day % 60
        return dt(year, month, day, hour, minute, tzinfo=tz(td(hours=9)))

    @daily_inform.before_loop
    async def _before_daily_inform(self):
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(dailyInform(bot))
