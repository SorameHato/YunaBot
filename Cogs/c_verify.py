# coding: utf-8

from datetime import datetime as dt
from datetime import timedelta as td
from datetime import timezone as tz
from typing import Annotated, Optional

import discord
from discord.ext import commands

from DB import db_setting, db_tone, db_verify
from Library import (
    lib_cog_scope,
    lib_bot_admin,
    lib_channel_check,
    lib_embed_fields,
    lib_interaction_defer,
    lib_member_label,
    lib_premium,
)

_PANEL_BUTTON_CUSTOM_ID = 'verify:apply'
_REVIEW_APPROVE_CUSTOM_ID = 'verify:approve'
_REVIEW_REJECT_CUSTOM_ID = 'verify:reject'
_REVIEW_THREAD_CUSTOM_ID = 'verify:thread'
_REVIEW_THREAD_DELETE_CUSTOM_ID = 'verify:thread:delete'

_BTN_APPLY_DEFAULT = db_tone.render_default_message('verify_btn_apply')
_BTN_APPROVE_DEFAULT = db_tone.render_default_message('verify_btn_approve')
_BTN_REJECT_DEFAULT = db_tone.render_default_message('verify_btn_reject')
_BTN_THREAD_DEFAULT = db_tone.render_default_message('verify_btn_thread')
_BTN_THREAD_DELETE_DEFAULT = db_tone.render_default_message('verify_btn_thread_delete')
_BTN_CONTINUE_DEFAULT = db_tone.render_default_message('verify_btn_apply_continue')


_QUESTIONS_PER_PAGE = 2


class _VerifyApplyModal(discord.ui.DesignerModal):
    def __init__(
        self,
        cog: 'verify',
        guild_id: int,
        *,
        all_questions: list[dict],
        page_questions: list[dict],
        start_index: int,
        prior_answers: list[str],
        is_final: bool,
    ):
        self.cog = cog
        self.guild_id = guild_id
        self.all_questions = all_questions
        self.page_questions = page_questions
        self.start_index = start_index
        self.prior_answers = prior_answers
        self.is_final = is_final
        self._answer_inputs: list[discord.ui.InputText] = []
        modal_items: list[discord.ui.Item] = []
        answer_placeholder = cog._t(guild_id, 'verify_modal_answer_placeholder')
        for offset, question in enumerate(page_questions):
            question_index = start_index + offset
            question_text = (question['question'] or cog._t(guild_id, 'verify_question_empty')).strip()
            modal_items.append(
                discord.ui.TextDisplay(
                    question_text or cog._t(guild_id, 'verify_question_empty')
                )
            )
            input_item = discord.ui.InputText(
                custom_id=f'verify:apply:answer:{question_index + 1}',
                placeholder=answer_placeholder,
                required=True,
                min_length=1,
                max_length=512,
                style=discord.InputTextStyle.long,
            )
            self._answer_inputs.append(input_item)
            modal_items.append(
                discord.ui.Label(
                    cog._t(guild_id, 'verify_modal_answer_label'),
                    item=input_item,
                    description=cog._t(guild_id, 'verify_modal_answer_description'),
                )
            )
        super().__init__(
            *modal_items,
            title=cog._t(guild_id, 'verify_modal_title'),
        )

    async def callback(self, interaction: discord.Interaction):
        page_answers = [(item.value or '').strip() for item in self._answer_inputs]
        all_answers = self.prior_answers + page_answers
        if self.is_final:
            await self.cog._handle_apply_submit(
                interaction,
                questions=self.all_questions,
                answers=all_answers,
            )
            return
        await self.cog._handle_apply_partial(
            interaction,
            all_questions=self.all_questions,
            answers_so_far=all_answers,
            next_start_index=self.start_index + len(self.page_questions),
        )


class _VerifyApplyContinueView(discord.ui.View):
    def __init__(
        self,
        cog: 'verify',
        *,
        guild_id: int,
        requester_id: int,
        all_questions: list[dict],
        page_index: int,
        prior_answers: list[str],
    ):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.all_questions = all_questions
        self.page_index = page_index
        self.prior_answers = prior_answers
        self.continue_button.label = cog._t(guild_id, 'verify_btn_apply_continue')

    async def on_timeout(self) -> None:
        self.disable_all_items()
        target = self.parent or self.message
        if target is None:
            return
        try:
            await target.edit(
                content=self.cog._t(self.guild_id, 'verify_apply_continue_expired'),
                view=self,
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    @discord.ui.button(label=_BTN_CONTINUE_DEFAULT, style=discord.ButtonStyle.primary)
    async def continue_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    self.guild_id,
                    '명령어 실행자 이외의 사람이 조작',
                ),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            self.cog._build_apply_modal(
                self.guild_id,
                self.all_questions,
                page_index=self.page_index,
                prior_answers=self.prior_answers,
            )
        )


class _VerifyPanelView(discord.ui.View):
    def __init__(self, cog: 'verify', guild_id: int | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.apply_button.label = (
            cog._t(guild_id, 'verify_btn_apply') if guild_id is not None else _BTN_APPLY_DEFAULT
        )

    @discord.ui.button(
        label=_BTN_APPLY_DEFAULT,
        style=discord.ButtonStyle.primary,
        custom_id=_PANEL_BUTTON_CUSTOM_ID,
    )
    async def apply_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog._handle_apply_button(interaction)


class _VerifyReviewView(discord.ui.View):
    def __init__(self, cog: 'verify', guild_id: int | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.approve_button.label = (
            cog._t(guild_id, 'verify_btn_approve') if guild_id is not None else _BTN_APPROVE_DEFAULT
        )
        self.reject_button.label = (
            cog._t(guild_id, 'verify_btn_reject') if guild_id is not None else _BTN_REJECT_DEFAULT
        )
        self.thread_button.label = (
            cog._t(guild_id, 'verify_btn_thread') if guild_id is not None else _BTN_THREAD_DEFAULT
        )

    @discord.ui.button(
        label=_BTN_APPROVE_DEFAULT,
        style=discord.ButtonStyle.success,
        custom_id=_REVIEW_APPROVE_CUSTOM_ID,
    )
    async def approve_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog._handle_review_decision(interaction, approved=True)

    @discord.ui.button(
        label=_BTN_REJECT_DEFAULT,
        style=discord.ButtonStyle.danger,
        custom_id=_REVIEW_REJECT_CUSTOM_ID,
    )
    async def reject_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog._handle_review_decision(interaction, approved=False)

    @discord.ui.button(
        label=_BTN_THREAD_DEFAULT,
        style=discord.ButtonStyle.secondary,
        custom_id=_REVIEW_THREAD_CUSTOM_ID,
    )
    async def thread_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog._handle_review_thread_toggle(interaction)


class _VerifyThreadDeleteView(discord.ui.View):
    def __init__(self, cog: 'verify', guild_id: int | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.delete_button.label = (
            cog._t(guild_id, 'verify_btn_thread_delete') if guild_id is not None else _BTN_THREAD_DELETE_DEFAULT
        )

    @discord.ui.button(
        label=_BTN_THREAD_DELETE_DEFAULT,
        style=discord.ButtonStyle.danger,
        custom_id=_REVIEW_THREAD_DELETE_CUSTOM_ID,
    )
    async def delete_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog._handle_thread_delete_button(interaction)


class verify(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self._persistent_views_registered = False
        self._apply_continue_messages: dict[tuple[int, int], discord.Message] = {}
        try:
            db_verify.ensure_schema()
        except Exception as exc:
            print(f'verify: schema init failed: {exc}')

    def _register_persistent_views(self) -> None:
        if self._persistent_views_registered:
            return
        self.bot.add_view(_VerifyPanelView(self))
        self.bot.add_view(_VerifyReviewView(self))
        self.bot.add_view(_VerifyThreadDeleteView(self))
        self._persistent_views_registered = True

    def _t(self, guild_id: int, message_key: str, **kwargs) -> str:
        return db_tone.render_message(guild_id, message_key, **kwargs)

    def _format_cooldown(self, guild_id: int, remain_ms: int) -> str:
        remain_sec = max(1, int((remain_ms + 999) // 1000))
        minutes, seconds = divmod(remain_sec, 60)
        return self._t(guild_id, 'verify_cooldown_remain', minutes=minutes, seconds=seconds)

    def _status_text(self, guild_id: int, status: str) -> str:
        status_keys = {
            'pending': 'verify_status_pending',
            'approved': 'verify_status_approved',
            'rejected': 'verify_status_rejected',
        }
        key = status_keys.get(status)
        if key is None:
            return status
        return self._t(guild_id, key)

    def _is_premium_context(self, guild_id: int) -> bool:
        return lib_premium.is_premium_context(self.bot, guild_id)

    def _is_allowed_guild(self, guild_id: int | None) -> bool:
        return lib_cog_scope.is_cog_allowed_guild(self.bot, self, guild_id)

    def _is_feature_enabled(self, guild_id: int) -> bool:
        return bool(db_setting.get_setting(guild_id, 'verify_enable'))

    def _is_repass_enabled(self, guild_id: int) -> bool:
        return bool(db_setting.get_setting(guild_id, 'verify_repass_enable'))

    def _is_auto_reject_wrong_enabled(self, guild_id: int) -> bool:
        return bool(db_setting.get_setting(guild_id, 'verify_auto_reject_wrong'))

    async def _is_bot_admin(self, member: discord.Member) -> bool:
        return lib_bot_admin.is_bot_admin(member, include_bot_owner=True)

    def _apply_continue_key(self, guild_id: int, user_id: int) -> tuple[int, int]:
        return guild_id, user_id

    async def _track_apply_continue_message(
        self,
        interaction: discord.Interaction,
        *,
        guild_id: int,
        user_id: int,
    ) -> None:
        try:
            message = await interaction.original_response()
        except Exception:
            return
        self._apply_continue_messages[self._apply_continue_key(guild_id, user_id)] = message

    async def _clear_apply_continue_message(self, guild_id: int, user_id: int) -> None:
        message = self._apply_continue_messages.pop(self._apply_continue_key(guild_id, user_id), None)
        if message is None:
            return
        try:
            await message.edit(view=None)
        except Exception as exc:
            print(f'verify apply continue message clear failed: {exc}')

    async def _resolve_channel(self, channel_id: int) -> Optional[discord.TextChannel]:
        return await lib_channel_check.resolve_text_channel(self.bot, channel_id)

    async def _resolve_member(self, guild: discord.Guild, user_id: int) -> Optional[discord.Member]:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            return None
        return member

    async def _resolve_thread(self, guild: discord.Guild, thread_id: int) -> Optional[discord.Thread]:
        thread = guild.get_thread(thread_id)
        if thread is not None:
            return thread
        try:
            fetched = await self.bot.fetch_channel(thread_id)
        except Exception:
            return None
        return fetched if isinstance(fetched, discord.Thread) else None

    def _thread_delete_view_for(self, guild_id: int) -> _VerifyThreadDeleteView:
        return _VerifyThreadDeleteView(self, guild_id=guild_id)

    async def _notify_review_thread_completed(
        self,
        guild: discord.Guild,
        request: db_verify.VerifyApplication,
    ) -> None:
        if not request.review_thread_id:
            return
        thread = await self._resolve_thread(guild, request.review_thread_id)
        if thread is None:
            return
        try:
            await thread.send(
                self._t(guild.id, 'verify_thread_completed_notice'),
                view=self._thread_delete_view_for(guild.id),
            )
        except Exception as exc:
            print(f'verify thread completion notice failed: {exc}')

    async def _handle_thread_delete_button(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return
        guild_id = interaction.guild.id
        if not self._is_allowed_guild(guild_id):
            return
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                db_tone.render_validation_error(guild_id, '스레드가 아닌 채널에서 스레드 삭제 버튼이 사용됨'),
                ephemeral=True,
            )
            return
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                db_tone.render_validation_error(guild_id, '길드 멤버 정보를 확인할 수 없음'),
                ephemeral=True,
            )
            return
        if not await self._is_bot_admin(interaction.user):
            await interaction.response.send_message(
                self._t(guild_id, 'verify_perm_denied'),
                ephemeral=True,
            )
            return

        if not await lib_interaction_defer.defer_component(interaction, ephemeral=True):
            return
        thread = interaction.channel
        request = db_verify.get_application_by_review_thread(thread.id)
        try:
            await thread.delete()
        except Exception as exc:
            await interaction.followup.send(
                self._t(guild_id, 'verify_thread_delete_failed', detail=exc),
                ephemeral=True,
            )
            return
        if request is not None:
            db_verify.bind_review_thread(request.id, None)
        await interaction.followup.send(
            self._t(guild_id, 'verify_thread_delete_done'),
            ephemeral=True,
        )

    def _load_questions(self, guild_id: int) -> list[dict]:
        return db_setting.get_verify_questions(guild_id)

    def _format_qa_for_storage(self, questions: list[dict], answers: list[str]) -> tuple[str, str]:
        q_lines = []
        a_lines = []
        for index, item in enumerate(questions):
            q_lines.append(f'Q{index + 1}. {item["question"]}')
            a_lines.append(f'A{index + 1}. {(answers[index] if index < len(answers) else "").strip()}')
        return '\n'.join(q_lines), '\n'.join(a_lines)

    def _parse_stored_qa(self, question_text: str, answer_text: str) -> tuple[list[str], list[str]]:
        questions: list[str] = []
        answers: list[str] = []
        for line in (question_text or '').splitlines():
            if line.startswith('Q') and '. ' in line:
                questions.append(line.split('. ', 1)[1])
        for line in (answer_text or '').splitlines():
            if line.startswith('A') and '. ' in line:
                answers.append(line.split('. ', 1)[1])
        return questions, answers

    def _split_question_pages(self, questions: list[dict]) -> list[list[dict]]:
        if len(questions) <= _QUESTIONS_PER_PAGE:
            return [questions]
        return [questions[:_QUESTIONS_PER_PAGE], questions[_QUESTIONS_PER_PAGE:]]

    def _build_apply_modal(
        self,
        guild_id: int,
        questions: list[dict],
        *,
        page_index: int,
        prior_answers: list[str],
    ) -> _VerifyApplyModal:
        pages = self._split_question_pages(questions)
        page_questions = pages[page_index]
        start_index = 0 if page_index == 0 else _QUESTIONS_PER_PAGE
        return _VerifyApplyModal(
            self,
            guild_id=guild_id,
            all_questions=questions,
            page_questions=page_questions,
            start_index=start_index,
            prior_answers=prior_answers,
            is_final=page_index >= len(pages) - 1,
        )

    def _resolve_apply_resume(self, guild_id: int, user_id: int, questions: list[dict]) -> tuple[int, list[str]]:
        if len(questions) <= _QUESTIONS_PER_PAGE:
            db_verify.delete_draft(guild_id, user_id)
            return 0, []

        existing = db_verify.get_application(guild_id, user_id)
        if existing is None or existing.status != 'draft':
            return 0, []

        _, prior_answers = self._parse_stored_qa(existing.question, existing.answer)
        if not prior_answers:
            db_verify.delete_draft(guild_id, user_id)
            return 0, []

        if len(prior_answers) >= _QUESTIONS_PER_PAGE:
            return 1, prior_answers[:_QUESTIONS_PER_PAGE]

        db_verify.delete_draft(guild_id, user_id)
        return 0, []

    def _grade_answers(self, questions: list[dict], answers: list[str]) -> tuple[list[bool | None], bool]:
        results: list[bool | None] = []
        for index, item in enumerate(questions):
            answer = (answers[index] if index < len(answers) else '').strip().casefold()
            keys = [str(x).strip().casefold() for x in (item.get('answers') or []) if str(x).strip()]
            if not keys:
                results.append(None)
                continue
            results.append(answer in keys)
        all_have_keys = all(bool(item.get('answers')) for item in questions)
        all_correct = all(result is True for result in results) if all_have_keys else False
        return results, all_correct

    def _has_graded_wrong_answer(self, grade_results: list[bool | None]) -> bool:
        return any(result is False for result in grade_results)

    def _format_grade_status_lines(
        self,
        guild_id: int,
        grade_results: list[bool | None],
    ) -> list[str]:
        status_lines = []
        for index, result in enumerate(grade_results):
            if result is None:
                status_lines.append(
                    self._t(guild_id, 'verify_grade_status_descriptive', index=index + 1)
                )
            elif result:
                status_lines.append(
                    self._t(guild_id, 'verify_grade_status_correct', index=index + 1)
                )
            else:
                status_lines.append(
                    self._t(guild_id, 'verify_grade_status_wrong', index=index + 1)
                )
        return status_lines

    def _append_grade_results_field(
        self,
        guild_id: int,
        embed: discord.Embed,
        grade_results: list[bool | None],
    ) -> None:
        if not grade_results:
            return
        lib_embed_fields.add_embed_field_safe(
            embed,
            self._t(guild_id, 'verify_grade_field_name'),
            '\n'.join(self._format_grade_status_lines(guild_id, grade_results)),
            inline=False,
        )

    async def _grant_thread_chat_permissions(
        self,
        thread: discord.Thread,
        member: discord.Member,
        *,
        guild_id: int,
    ) -> None:
        overwrite = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages_in_threads=True,
            attach_files=True,
            embed_links=True,
        )
        await lib_channel_check.set_thread_permissions(
            thread,
            member,
            overwrite=overwrite,
            reason=self._t(guild_id, 'verify_thread_permission_reason'),
        )

    async def _grant_verify_role(self, guild: discord.Guild, member: discord.Member) -> tuple[bool, str | None]:
        guild_id = guild.id
        verify_role_id = db_setting.get_setting(guild_id, 'verify_role')
        if not verify_role_id:
            return False, self._t(guild_id, 'verify_role_not_set')
        role = guild.get_role(verify_role_id)
        if role is None:
            return False, self._t(guild_id, 'verify_role_not_found')
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return False, self._t(guild_id, 'verify_bot_no_manage_roles')
        if me.top_role <= role:
            return False, self._t(guild_id, 'verify_bot_role_too_low')
        if role not in member.roles:
            try:
                await member.add_roles(role, reason=self._t(guild_id, 'verify_role_reason_approve'))
            except Exception as exc:
                return False, self._t(guild_id, 'verify_role_grant_failed', detail=exc)
        return True, None

    def _review_embed(
        self,
        guild: discord.Guild,
        request: db_verify.VerifyApplication,
        *,
        applicant: discord.Member | discord.User | None,
        reviewer_id: int | None = None,
        decision_note: str | None = None,
    ) -> discord.Embed:
        guild_id = guild.id
        display = (
            lib_member_label.format_user_label(applicant)
            if applicant is not None
            else self._t(guild_id, 'verify_review_applicant_unknown', user_id=request.user_id)
        )
        status_text = self._status_text(guild_id, request.status)
        embed = discord.Embed(
            title=self._t(guild_id, 'verify_review_title'),
            color=db_setting.get_embed_color(guild_id),
            timestamp=dt.now(tz=tz(td(hours=9))),
        )
        lib_embed_fields.add_embed_field_safe(
            embed,
            self._t(guild_id, 'verify_review_field_applicant'),
            f'{display}\n<@{request.user_id}>',
            inline=False,
        )
        lib_embed_fields.add_embed_field_safe(
            embed,
            self._t(guild_id, 'verify_review_field_question'),
            request.question or self._t(guild_id, 'verify_question_empty'),
            inline=False,
        )
        lib_embed_fields.add_embed_field_safe(
            embed,
            self._t(guild_id, 'verify_review_field_answer'),
            request.answer or self._t(guild_id, 'verify_review_no_answer'),
            inline=False,
        )
        lib_embed_fields.add_embed_field_safe(
            embed,
            self._t(guild_id, 'verify_review_field_status'),
            status_text,
            inline=False,
        )
        if reviewer_id:
            lib_embed_fields.add_embed_field_safe(
                embed,
                self._t(guild_id, 'verify_review_field_reviewer'),
                f'<@{reviewer_id}>',
                inline=False,
            )
        if decision_note:
            lib_embed_fields.add_embed_field_safe(
                embed,
                self._t(guild_id, 'verify_review_field_decision'),
                decision_note,
                inline=False,
            )
        embed.set_footer(text=self._t(guild_id, 'verify_review_footer', request_id=request.id))
        return embed

    async def _invalidate_previous_review_card(
        self,
        guild: discord.Guild,
        log_channel: discord.TextChannel,
        request: db_verify.VerifyApplication | None,
    ) -> None:
        if request is None or request.status != 'pending' or not request.review_message_id:
            return
        try:
            message = await log_channel.fetch_message(request.review_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        except Exception as exc:
            print(f'verify invalidate old review card fetch failed: {exc}')
            return

        applicant = await self._resolve_member(guild, request.user_id)
        embed = self._review_embed(
            guild,
            request,
            applicant=applicant,
            decision_note=self._t(guild.id, 'verify_invalidate_decision_note'),
        )
        status_field = self._t(guild.id, 'verify_review_field_status')
        status_index = next(
            (index for index, field in enumerate(embed.fields) if field.name == status_field),
            None,
        )
        if status_index is not None:
            embed.set_field_at(
                status_index,
                name=status_field,
                value=self._t(guild.id, 'verify_status_invalid_reapply'),
                inline=False,
            )

        try:
            await message.edit(embed=embed, view=None)
        except Exception as exc:
            print(f'verify invalidate old review card edit failed: {exc}')

    def _panel_text(self, guild_id: int) -> str:
        return self._t(guild_id, 'verify_panel_text')

    def _panel_view_for(self, guild_id: int) -> _VerifyPanelView:
        return _VerifyPanelView(self, guild_id=guild_id)

    def _review_view_for(self, guild_id: int) -> _VerifyReviewView:
        return _VerifyReviewView(self, guild_id=guild_id)

    async def _restore_panel_if_possible(self, guild: discord.Guild) -> None:
        if not self._is_premium_context(guild.id):
            return
        try:
            settings = db_setting.get_all_settings(guild.id)
        except Exception:
            return
        if not settings.verify_enable:
            return
        if not settings.verify_panel_channel or not settings.verify_panel_message_id:
            return
        channel = await self._resolve_channel(settings.verify_panel_channel)
        if channel is None:
            return
        try:
            panel_message = await channel.fetch_message(settings.verify_panel_message_id)
        except Exception:
            return
        try:
            await panel_message.edit(
                content=self._panel_text(guild.id),
                view=self._panel_view_for(guild.id),
            )
        except Exception:
            return

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return False
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                db_tone.render_validation_error(
                    interaction.guild.id,
                    '길드 멤버 정보를 확인할 수 없음',
                ),
                ephemeral=True,
            )
            return False
        if not await self._is_bot_admin(interaction.user):
            await interaction.response.send_message(
                self._t(interaction.guild.id, 'verify_perm_denied'),
                ephemeral=True,
            )
            return False
        return True

    def _apply_feature_guard(self, guild_id: int) -> tuple[bool, str | None]:
        if not self._is_allowed_guild(guild_id):
            return False, None
        if not self._is_premium_context(guild_id):
            return False, self._t(guild_id, 'verify_premium_denied')
        if not lib_cog_scope.is_extension_enabled_for_guild(
            self.bot,
            lib_cog_scope.VERIFY_COG_MODULE,
            guild_id,
        ):
            return False, self._t(guild_id, 'verify_premium_denied')
        try:
            enabled = self._is_feature_enabled(guild_id)
        except Exception:
            return False, self._t(guild_id, 'verify_settings_load_failed')
        if not enabled:
            return False, self._t(guild_id, 'verify_feature_disabled')
        return True, None

    async def _handle_apply_button(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return
        guild_id = interaction.guild.id
        ok, error = self._apply_feature_guard(guild_id)
        if not ok:
            if error:
                await interaction.response.send_message(error, ephemeral=True)
            return
        blocked, remain_ms = db_verify.is_in_reject_cooldown(guild_id, interaction.user.id)
        if blocked:
            await interaction.response.send_message(
                self._t(
                    guild_id,
                    'verify_cooldown',
                    remain=self._format_cooldown(guild_id, remain_ms),
                ),
                ephemeral=True,
            )
            return
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if (
            self._is_repass_enabled(guild_id)
            and member is not None
            and db_verify.has_approved_history(guild_id, interaction.user.id)
        ):
            deferred = await lib_interaction_defer.defer_component(interaction, ephemeral=True)
            ok_role, role_error = await self._grant_verify_role(interaction.guild, member)
            content = (
                self._t(guild_id, 'verify_repass_success')
                if ok_role
                else role_error
            )
            if deferred:
                await lib_interaction_defer.followup_send(interaction, content, ephemeral=True)
            else:
                try:
                    await interaction.response.send_message(content, ephemeral=True)
                except (discord.InteractionResponded, discord.NotFound, discord.HTTPException) as exc:
                    print(f'verify repass response failed: {exc}')
            return
        questions = self._load_questions(guild_id)
        if not questions:
            await interaction.response.send_message(
                self._t(guild_id, 'verify_question_not_set'),
                ephemeral=True,
            )
            return
        page_index, prior_answers = self._resolve_apply_resume(
            guild_id,
            interaction.user.id,
            questions,
        )
        await self._clear_apply_continue_message(guild_id, interaction.user.id)
        await interaction.response.send_modal(
            self._build_apply_modal(
                guild_id,
                questions,
                page_index=page_index,
                prior_answers=prior_answers,
            )
        )

    async def _handle_apply_partial(
        self,
        interaction: discord.Interaction,
        *,
        all_questions: list[dict],
        answers_so_far: list[str],
        next_start_index: int,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return
        guild_id = interaction.guild.id
        ok, error = self._apply_feature_guard(guild_id)
        if not ok:
            if error:
                await interaction.response.send_message(error, ephemeral=True)
            return
        if not answers_so_far or any(not (answer or '').strip() for answer in answers_so_far):
            await interaction.response.send_message(
                db_tone.render_validation_error(guild_id, '답변이 비어있음'),
                ephemeral=True,
            )
            return
        blocked, remain_ms = db_verify.is_in_reject_cooldown(guild_id, interaction.user.id)
        if blocked:
            await interaction.response.send_message(
                self._t(
                    guild_id,
                    'verify_cooldown',
                    remain=self._format_cooldown(guild_id, remain_ms),
                ),
                ephemeral=True,
            )
            return

        partial_questions = all_questions[:len(answers_so_far)]
        packed_question, packed_answer = self._format_qa_for_storage(partial_questions, answers_so_far)
        try:
            db_verify.save_draft(
                guild_id,
                interaction.user.id,
                question=packed_question,
                answer=packed_answer,
            )
        except Exception as exc:
            print(f'verify apply partial save failed: {exc}')
            await interaction.response.send_message(
                self._t(guild_id, 'verify_apply_submit_failed'),
                ephemeral=True,
            )
            return

        pages = self._split_question_pages(all_questions)
        next_page_index = next_start_index // _QUESTIONS_PER_PAGE
        # 모달 제출 직후에는 다른 모달을 바로 열 수 없어 버튼으로 이어 받는다.
        await interaction.response.send_message(
            self._t(guild_id, 'verify_apply_partial_saved'),
            ephemeral=True,
            view=_VerifyApplyContinueView(
                self,
                guild_id=guild_id,
                requester_id=interaction.user.id,
                all_questions=all_questions,
                page_index=next_page_index,
                prior_answers=answers_so_far,
            ),
        )
        await self._track_apply_continue_message(
            interaction,
            guild_id=guild_id,
            user_id=interaction.user.id,
        )

    async def _handle_apply_submit(
        self,
        interaction: discord.Interaction,
        *,
        questions: list[dict],
        answers: list[str],
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return
        guild_id = interaction.guild.id
        ok, error = self._apply_feature_guard(guild_id)
        if not ok:
            if error:
                await interaction.response.send_message(error, ephemeral=True)
            return
        if not answers or any(not (answer or '').strip() for answer in answers):
            await interaction.response.send_message(
                db_tone.render_validation_error(guild_id, '답변이 비어있음'),
                ephemeral=True,
            )
            return
        blocked, remain_ms = db_verify.is_in_reject_cooldown(guild_id, interaction.user.id)
        if blocked:
            await interaction.response.send_message(
                self._t(
                    guild_id,
                    'verify_cooldown',
                    remain=self._format_cooldown(guild_id, remain_ms),
                ),
                ephemeral=True,
            )
            return

        settings = db_setting.get_all_settings(guild_id)
        if not settings.verify_log_channel:
            await interaction.response.send_message(
                self._t(guild_id, 'verify_log_channel_not_set'),
                ephemeral=True,
            )
            return
        log_channel = await self._resolve_channel(settings.verify_log_channel)
        if log_channel is None:
            await interaction.response.send_message(
                self._t(guild_id, 'verify_log_channel_not_found'),
                ephemeral=True,
            )
            return
        channel_issue = lib_channel_check.text_channel_send_issue(log_channel, interaction.guild)
        if channel_issue:
            await interaction.response.send_message(
                self._t(guild_id, 'verify_log_channel_issue', issue=channel_issue),
                ephemeral=True,
            )
            return

        if not await lib_interaction_defer.defer_component(interaction, ephemeral=True):
            return

        packed_question, packed_answer = self._format_qa_for_storage(questions, answers)
        grade_results, all_correct = self._grade_answers(questions, answers)

        # 정답이 있는 객관식 질문만 구성되어 있고 전부 맞으면 관리자 검토 없이 즉시 통과
        if all_correct:
            member = interaction.user if isinstance(interaction.user, discord.Member) else None
            if member is None:
                await interaction.followup.send(
                    db_tone.render_validation_error(guild_id, '길드 멤버 정보를 확인할 수 없음'),
                    ephemeral=True,
                )
                return
            ok_role, role_error = await self._grant_verify_role(interaction.guild, member)
            if not ok_role:
                await interaction.followup.send(role_error, ephemeral=True)
                return
            request = db_verify.create_or_replace_pending(
                guild_id,
                interaction.user.id,
                question=packed_question,
                answer=packed_answer,
            )
            db_verify.mark_approved(request.id, reviewer_id=0)
            await self._clear_apply_continue_message(guild_id, interaction.user.id)
            await interaction.followup.send(
                self._t(guild_id, 'verify_auto_approve_all_correct'),
                ephemeral=True,
            )
            return

        if (
            self._is_auto_reject_wrong_enabled(guild_id)
            and self._has_graded_wrong_answer(grade_results)
        ):
            existing = db_verify.get_application(guild_id, interaction.user.id)
            await self._invalidate_previous_review_card(
                interaction.guild,
                log_channel,
                existing,
            )
            try:
                request = db_verify.create_or_replace_pending(
                    guild_id,
                    interaction.user.id,
                    question=packed_question,
                    answer=packed_answer,
                )
                decided = db_verify.mark_rejected(request.id, reviewer_id=0)
                if decided is None:
                    raise RuntimeError('verify auto reject failed')
                embed = self._review_embed(
                    interaction.guild,
                    decided,
                    applicant=interaction.user,
                    decision_note=self._t(guild_id, 'verify_decision_auto_reject_wrong'),
                )
                self._append_grade_results_field(guild_id, embed, grade_results)
                await log_channel.send(embed=embed)
            except Exception as exc:
                print(f'verify auto reject wrong failed: {exc}')
                await interaction.followup.send(
                    self._t(guild_id, 'verify_apply_submit_failed'),
                    ephemeral=True,
                )
                return
            await self._clear_apply_continue_message(guild_id, interaction.user.id)
            await interaction.followup.send(
                self._t(guild_id, 'verify_auto_reject_wrong_answer'),
                ephemeral=True,
            )
            return

        existing = db_verify.get_application(guild_id, interaction.user.id)
        await self._invalidate_previous_review_card(
            interaction.guild,
            log_channel,
            existing,
        )

        request = None
        review_message = None
        try:
            request = db_verify.create_or_replace_pending(
                guild_id,
                interaction.user.id,
                question=packed_question,
                answer=packed_answer,
            )
            embed = self._review_embed(
                interaction.guild,
                request,
                applicant=interaction.user,
            )
            self._append_grade_results_field(guild_id, embed, grade_results)
            review_message = await log_channel.send(
                embed=embed,
                view=self._review_view_for(guild_id),
            )
            db_verify.bind_review_message(request.id, review_message.id)
        except Exception as exc:
            if review_message is not None:
                try:
                    await review_message.delete()
                except Exception:
                    pass
            if request is not None:
                db_verify.delete_if_pending_unbound(request.id)
            print(f'verify apply submit failed: {exc}')
            await interaction.followup.send(
                self._t(guild_id, 'verify_apply_submit_failed'),
                ephemeral=True,
            )
            return

        await self._clear_apply_continue_message(guild_id, interaction.user.id)
        await interaction.followup.send(
            self._t(guild_id, 'verify_apply_submitted'),
            ephemeral=True,
        )

    async def _handle_review_decision(self, interaction: discord.Interaction, *, approved: bool) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return
        guild_id = interaction.guild.id
        if not self._is_allowed_guild(guild_id):
            return
        if interaction.message is None:
            await interaction.response.send_message(
                self._t(guild_id, 'verify_review_message_not_found'),
                ephemeral=True,
            )
            return
        if not await self._require_admin(interaction):
            return

        request = db_verify.get_application_by_review_message(interaction.message.id)
        if request is None or request.guild != guild_id:
            await interaction.response.send_message(
                self._t(guild_id, 'verify_application_not_found'),
                ephemeral=True,
            )
            return
        if request.status != 'pending':
            await interaction.response.send_message(
                self._t(guild_id, 'verify_application_already_processed'),
                ephemeral=True,
            )
            return

        if not await lib_interaction_defer.defer_component(interaction, ephemeral=False):
            return

        reviewer_id = interaction.user.id
        applicant = await self._resolve_member(interaction.guild, request.user_id)

        if approved:
            if applicant is None:
                await interaction.followup.send(
                    self._t(guild_id, 'verify_applicant_not_in_guild'),
                    ephemeral=True,
                )
                return
            ok_role, role_error = await self._grant_verify_role(interaction.guild, applicant)
            if not ok_role:
                await interaction.followup.send(
                    role_error,
                    ephemeral=True,
                )
                return
            decided = db_verify.mark_approved(request.id, reviewer_id)
            decision_note = self._t(guild_id, 'verify_decision_approved')
        else:
            decided = db_verify.mark_rejected(request.id, reviewer_id)
            dm_note = self._t(guild_id, 'verify_decision_dm_skipped')
            kick_note = self._t(guild_id, 'verify_decision_kick_done')
            if applicant is not None:
                try:
                    await applicant.send(
                        self._t(
                            guild_id,
                            'verify_dm_reject',
                            guild_name=interaction.guild.name,
                        )
                    )
                    dm_note = self._t(guild_id, 'verify_decision_dm_sent')
                except Exception:
                    dm_note = self._t(guild_id, 'verify_decision_dm_failed')
                try:
                    await applicant.kick(
                        reason=self._t(guild_id, 'verify_role_reason_reject'),
                    )
                except Exception as exc:
                    kick_note = self._t(guild_id, 'verify_decision_kick_failed', detail=exc)
            else:
                kick_note = self._t(guild_id, 'verify_decision_kick_not_in_guild')
            decision_note = f'{dm_note}\n{kick_note}'

        if decided is None:
            await interaction.followup.send(
                self._t(guild_id, 'verify_decision_failed'),
                ephemeral=True,
            )
            return

        embed = self._review_embed(
            interaction.guild,
            decided,
            applicant=applicant,
            reviewer_id=reviewer_id,
            decision_note=decision_note,
        )
        try:
            await interaction.message.edit(embed=embed, view=None)
        except Exception as exc:
            print(f'verify review message edit failed: {exc}')
            await interaction.followup.send(
                self._t(guild_id, 'verify_review_edit_failed'),
                ephemeral=True,
            )
            return

        await self._notify_review_thread_completed(interaction.guild, decided)

    async def _handle_review_thread_toggle(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return
        guild_id = interaction.guild.id
        if not self._is_allowed_guild(guild_id):
            return
        if interaction.message is None:
            await interaction.response.send_message(
                self._t(guild_id, 'verify_review_message_not_found'),
                ephemeral=True,
            )
            return
        if not await self._require_admin(interaction):
            return
        request = db_verify.get_application_by_review_message(interaction.message.id)
        if request is None or request.guild != guild_id:
            await interaction.response.send_message(
                self._t(guild_id, 'verify_application_not_found'),
                ephemeral=True,
            )
            return

        settings = db_setting.get_all_settings(guild_id)
        panel_channel = await self._resolve_channel(settings.verify_panel_channel)
        if panel_channel is None:
            await interaction.response.send_message(
                self._t(guild_id, 'verify_review_panel_channel_not_set'),
                ephemeral=True,
            )
            return
        channel_issue = lib_channel_check.text_channel_send_issue(panel_channel, interaction.guild)
        if channel_issue:
            await interaction.response.send_message(
                self._t(guild_id, 'verify_review_panel_channel_issue', issue=channel_issue),
                ephemeral=True,
            )
            return

        if not await lib_interaction_defer.defer_component(interaction, ephemeral=True):
            return
        existing = None
        if request.review_thread_id:
            existing = await self._resolve_thread(interaction.guild, request.review_thread_id)
        if existing is not None:
            try:
                await existing.delete()
            except Exception as exc:
                await interaction.followup.send(
                    self._t(guild_id, 'verify_thread_delete_failed', detail=exc),
                    ephemeral=True,
                )
                return
            db_verify.bind_review_thread(request.id, None)
            await interaction.followup.send(
                self._t(guild_id, 'verify_thread_delete_done'),
                ephemeral=True,
            )
            return

        applicant = await self._resolve_member(interaction.guild, request.user_id)
        thread_name = self._t(
            guild_id,
            'verify_review_thread_name',
            user_id=request.user_id,
        )
        try:
            thread = await panel_channel.create_thread(
                name=thread_name[:100],
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=1440,
            )
        except Exception as exc:
            await interaction.followup.send(
                self._t(guild_id, 'verify_thread_create_failed', detail=exc),
                ephemeral=True,
            )
            return
        review_link = interaction.message.jump_url
        try:
            await thread.send(
                self._t(
                    guild_id,
                    'verify_review_thread_intro',
                    user_id=request.user_id,
                    review_link=review_link,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            pass
        try:
            if applicant is not None:
                await thread.add_user(applicant)
                try:
                    await self._grant_thread_chat_permissions(
                        thread,
                        applicant,
                        guild_id=interaction.guild.id,
                    )
                except Exception as exc:
                    print(f'verify thread applicant permission grant failed: {exc}')
        except Exception:
            pass
        try:
            if isinstance(interaction.user, discord.Member):
                await thread.add_user(interaction.user)
                try:
                    await self._grant_thread_chat_permissions(
                        thread,
                        interaction.user,
                        guild_id=interaction.guild.id,
                    )
                except Exception as exc:
                    print(f'verify thread admin permission grant failed: {exc}')
        except Exception:
            pass
        db_verify.bind_review_thread(request.id, thread.id)
        await interaction.followup.send(
            self._t(guild_id, 'verify_thread_create_done', thread=thread.mention),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_ready(self):
        self._register_persistent_views()
        for guild in self.bot.guilds:
            if not self._is_allowed_guild(guild.id):
                continue
            await self._restore_panel_if_possible(guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = member.guild.id
        if not self._is_allowed_guild(guild_id):
            return
        if not self._is_feature_enabled(guild_id):
            return
        if not self._is_repass_enabled(guild_id):
            return
        if not db_verify.has_approved_history(guild_id, member.id):
            return
        await self._grant_verify_role(member.guild, member)

    verify_commands = discord.SlashCommandGroup(
        name='인증방',
        description=db_tone.render_default_message('verify_group_desc'),
    )

    @verify_commands.command(
        name='메세지-전송',
        description=db_tone.render_default_message('verify_post_panel_desc'),
    )
    async def post_panel(
        self,
        ctx,
        channel: Annotated[
            Optional[discord.TextChannel],
            discord.Option(
                discord.TextChannel,
                name=db_tone.render_default_message('verify_post_panel_option_channel_name'),
                description=db_tone.render_default_message('verify_post_panel_option_channel_desc'),
                required=False,
            ),
        ] = None,
    ):
        if ctx.guild is None:
            await ctx.respond(
                db_tone.render_validation_error(0, '서버 전용 명령어가 DM에서 사용됨'),
                ephemeral=True,
            )
            return
        guild_id = ctx.guild.id
        if not self._is_allowed_guild(guild_id):
            return
        if not isinstance(ctx.author, discord.Member) or not await self._is_bot_admin(ctx.author):
            await ctx.respond(self._t(guild_id, 'verify_perm_denied'), ephemeral=True)
            return
        ok, error = self._apply_feature_guard(guild_id)
        if not ok:
            if error:
                await ctx.respond(error, ephemeral=True)
            return

        if not await lib_interaction_defer.defer_slash(ctx, ephemeral=True):
            return

        settings = db_setting.get_all_settings(guild_id)
        target_channel = channel
        if target_channel is None and settings.verify_panel_channel:
            target_channel = await self._resolve_channel(settings.verify_panel_channel)
        if target_channel is None:
            if isinstance(ctx.channel, discord.TextChannel):
                target_channel = ctx.channel
            else:
                await ctx.followup.send(
                    self._t(guild_id, 'verify_post_panel_channel_required'),
                    ephemeral=True,
                )
                return

        issue = lib_channel_check.text_channel_send_issue(target_channel, ctx.guild)
        if issue:
            await ctx.followup.send(
                self._t(guild_id, 'verify_post_panel_channel_issue', issue=issue),
                ephemeral=True,
            )
            return

        panel_view = self._panel_view_for(guild_id)
        panel_message = None
        if settings.verify_panel_message_id and settings.verify_panel_channel == target_channel.id:
            try:
                panel_message = await target_channel.fetch_message(settings.verify_panel_message_id)
            except Exception:
                panel_message = None
        if panel_message is None:
            panel_message = await target_channel.send(
                self._panel_text(guild_id),
                view=panel_view,
            )
        else:
            await panel_message.edit(content=self._panel_text(guild_id), view=panel_view)

        db_setting.update_setting(guild_id, 'verify_panel_channel', target_channel.id)
        db_setting.update_setting(guild_id, 'verify_panel_message_id', panel_message.id)
        await ctx.followup.send(
            self._t(guild_id, 'verify_post_panel_success', channel=target_channel.mention),
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(verify(bot))
