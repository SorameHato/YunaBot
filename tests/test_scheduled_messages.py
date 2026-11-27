import asyncio
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import discord

from Cogs.c_dailyInform import _DailyInformFormModal, dailyInform
from DB import db_dailyInform as db
from Library.lib_schedule import KST, Schedule, parse_schedule
from Library import lib_slash_guild_sync, lib_slash_tone_sync
from tone.default import LANG_PACK


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / 'scheduled.db'

    def connect(self):
        self.type = 'sqlite3'
        self.db_prefix = 'test'
        self.con = sqlite3.connect(path)
        self.cur = self.con.cursor()

    monkeypatch.setattr(db._connectDB, '__init__', connect)
    return path


def make_cog():
    cog = dailyInform.__new__(dailyInform)
    cog._sent_once_pending_cleanup = {}
    cog._recurring_pending_cleanup = {}
    cog._prepare_tone = AsyncMock()
    cog._last_sent_key = None
    cog._scheduler_scope = None
    cog._is_allowed_guild = lambda guild_id: guild_id == 1
    cog._t = lambda guild_id, key, **values: LANG_PACK[key].format(**values)
    cog._update_task_meta = lambda: None
    cog.bot = SimpleNamespace(get_guild=lambda guild_id: None, guilds=[SimpleNamespace(id=1), SimpleNamespace(id=2)])
    return cog


@pytest.mark.parametrize('last_editor', [False, True])
def test_migrate_legacy_rows_and_sequence(database, last_editor):
    with sqlite3.connect(database) as con:
        editor_column = ', last_editor INTEGER NOT NULL DEFAULT 0' if last_editor else ''
        con.execute(
            'CREATE TABLE test_dailyInform (id INTEGER PRIMARY KEY AUTOINCREMENT, '
            'guild INTEGER NOT NULL, time_min INTEGER NOT NULL, channel INTEGER NOT NULL, '
            'author INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL'
            + editor_column + ', UNIQUE(guild, time_min));'
        )
        con.execute("INSERT INTO test_dailyInform (id,guild,time_min,channel,author,message) VALUES (5,1,600,2,3,'legacy');")
        con.execute("INSERT INTO test_dailyInform (id,guild,time_min,channel,author,message) VALUES (50,1,601,2,3,'removed');")
        con.execute('DELETE FROM test_dailyInform WHERE id=50;')
        if last_editor:
            con.execute('UPDATE test_dailyInform SET last_editor=4;')
    db.ensure_schema()
    db.set_scheduler_state('bot', (2026, 11, 15, 600))
    db.ensure_schema()
    row = db.get_message_by_id(1, 5)
    assert row == db.DailyInformRow(5, 1, 600, 2, 3, 'legacy', 4 if last_editor else 0)
    assert db.get_scheduler_state('bot') == (2026, 11, 15, 600)
    new_id = db.add_message(1, 600, 8, 3, 'same time', schedule=Schedule('monthly', day=31))
    assert new_id > 50
    assert len(db.get_messages_by_time(600)) == 2


@pytest.mark.parametrize('day', [29, 30, 31])
def test_monthly_month_end_and_return_to_original_day(day):
    schedule = parse_schedule('monthly', str(day))
    assert schedule.matches(date(2027, 2, 28))
    assert not schedule.matches(date(2027, 2, 27))
    assert schedule.matches(date(2028, 2, 29))
    assert schedule.matches(date(2027, 4, min(day, 30)))
    assert schedule.matches(date(2027, 3, day))
    assert schedule.day == day


def test_yearly_leap_day_and_weekdays():
    schedule = parse_schedule('yearly', '02-29')
    assert schedule.matches(date(2027, 2, 28))
    assert schedule.matches(date(2028, 2, 29))
    assert not schedule.matches(date(2028, 2, 28))
    assert not schedule.matches(date(2027, 3, 29))
    monday = parse_schedule('weekly', weekdays=['0'])
    assert monday.matches(date(2026, 11, 16))
    assert not monday.matches(date(2026, 11, 15))
    every_day = parse_schedule('weekly', weekdays=list(map(str, range(7))))
    assert every_day.weekdays == 127
    assert all(every_day.matches(date(2026, 11, day)) for day in range(15, 22))


@pytest.mark.parametrize('target', [
    date(2027, 2, 27), date(2027, 2, 28), date(2028, 2, 28), date(2028, 2, 29),
    date(2027, 3, 31), date(2027, 4, 29), date(2027, 4, 30),
    date(2026, 12, 31), date(2027, 1, 1),
])
def test_sql_selects_only_due_recurring_messages(database, target):
    db.ensure_schema()
    schedules = [
        Schedule(),
        *(Schedule('weekly', weekdays=1 << weekday) for weekday in range(7)),
        Schedule('weekly', weekdays=127),
        *(Schedule('monthly', day=day) for day in range(1, 32)),
        Schedule('yearly', month=2, day=28), Schedule('yearly', month=2, day=29),
        Schedule('yearly', month=3, day=31), Schedule('yearly', month=4, day=30),
        Schedule('yearly', month=12, day=31), Schedule('yearly', month=1, day=1),
        Schedule('once', month=target.month, day=target.day, year=target.year),
    ]
    expected_ids = []
    for schedule in schedules:
        row_id = db.add_message(1, 600, 2, 3, schedule.kind, schedule=schedule)
        if schedule.kind != 'once' and schedule.matches(target):
            expected_ids.append(row_id)
    db.add_message(1, 601, 2, 3, 'different time')
    when = datetime(target.year, target.month, target.day, 10, tzinfo=KST)
    assert [row.id for row in db.get_due_recurring_messages(when)] == expected_ids
    assert [row.id for row in db.get_due_recurring_messages(when.astimezone(timezone.utc))] == expected_ids


@pytest.mark.parametrize(('kind', 'raw', 'days'), [
    ('weekly', '', []), ('weekly', '', ['7']),
    ('monthly', '0', None), ('monthly', '32', None), ('monthly', '1,2', None),
    ('yearly', '04-31', None), ('yearly', '13-01', None), ('yearly', '2-30', None),
    ('once', '2027-02-29', None), ('once', '0000-01-01', None),
    ('once', '2027-01-01,2027-01-02', None),
])
def test_invalid_schedule_inputs(kind, raw, days):
    with pytest.raises(ValueError):
        parse_schedule(kind, raw, days)


def test_once_retry_survives_reload_and_atomic_edit(database):
    db.ensure_schema()
    schedule = parse_schedule('once', '2026-11-15')
    row_id = db.add_message(1, 600, 2, 3, 'once', schedule=schedule)
    now = datetime(2026, 11, 16, 10, tzinfo=KST)
    row = db.get_due_once_messages(now)[0]
    assert db.claim_once_message(row, now, now + timedelta(minutes=5))
    assert not db.claim_once_message(row, now, now + timedelta(minutes=5))
    db.ensure_schema()
    assert not db.get_due_once_messages(now + timedelta(minutes=4))
    assert db.get_due_once_messages(now + timedelta(minutes=5))[0].id == row_id
    assert db.update_scheduled_message(1, row_id, 601, 4, 'edited', schedule=Schedule(), last_editor=5)
    db.delete_sent_once_message(row)
    edited = db.get_message_by_id(1, row_id)
    assert (edited.time_min, edited.channel, edited.message, edited.last_editor) == (601, 4, 'edited', 5)
    assert edited.schedule == Schedule()
    assert edited.next_retry == 0
    with pytest.raises(db.DailyInformValidationError):
        db.update_scheduled_message(1, row_id, 900, 8, 'x' * 257, schedule=schedule)
    assert db.get_message_by_id(1, row_id) == edited


def test_once_failure_then_success_and_send_limit(database):
    db.ensure_schema()
    schedule = parse_schedule('once', '2026-11-15')
    for index in range(9):
        db.add_message(1, 600, 2, 3, str(index), schedule=schedule)
    cog = make_cog()
    cog._send_message = AsyncMock(return_value=False)
    now = datetime(2026, 11, 16, 10, tzinfo=KST)
    asyncio.run(cog._send_due_once_messages(now, {}))
    assert cog._send_message.await_count == 7
    assert len(db.get_messages_by_guild(1)) == 9
    assert len(db.get_due_once_messages(now)) == 2
    # A fresh cog models a process restart. Retry state lives in the DB.
    cog = make_cog()
    cog._send_message = AsyncMock(return_value=True)
    asyncio.run(cog._send_due_once_messages(now + timedelta(minutes=5), {}))
    assert cog._send_message.await_count == 7
    assert len(db.get_messages_by_guild(1)) == 2
    asyncio.run(cog._send_due_once_messages(now + timedelta(minutes=6), {}))
    assert not db.get_messages_by_guild(1)


def test_once_cleanup_failure_does_not_resend(database, monkeypatch):
    db.ensure_schema()
    db.add_message(1, 600, 2, 3, 'once', schedule=parse_schedule('once', '2026-11-15'))
    original = db.delete_sent_once_message
    monkeypatch.setattr(db, 'delete_sent_once_message', lambda row: (_ for _ in ()).throw(RuntimeError('DB down')))
    cog = make_cog()
    cog._send_message = AsyncMock(return_value=True)
    now = datetime(2026, 11, 16, 10, tzinfo=KST)
    asyncio.run(cog._send_due_once_messages(now, {}))
    asyncio.run(cog._send_due_once_messages(now + timedelta(minutes=6), {}))
    assert cog._send_message.await_count == 1
    monkeypatch.setattr(db, 'delete_sent_once_message', original)
    asyncio.run(cog._send_due_once_messages(now + timedelta(minutes=7), {}))
    assert not db.get_messages_by_guild(1)


@pytest.mark.parametrize('kind', ['daily', 'weekly', 'monthly', 'yearly', 'once'])
def test_modal_payload_and_edit_defaults(kind):
    schedule = {
        'daily': Schedule(), 'weekly': Schedule('weekly', weekdays=65),
        'monthly': Schedule('monthly', day=31), 'yearly': Schedule('yearly', month=2, day=29),
        'once': Schedule('once', month=2, day=28, year=2027),
    }[kind]

    async def check():
        cog = make_cog()
        row = db.DailyInformRow(1, 1, 600, 2, 3, 'test', schedule=schedule)
        modal = _DailyInformFormModal(cog, mode='edit', guild_id=1, requester_id=3, row=row)
        payload = modal.to_dict()
        assert len(payload['components']) == (3 if kind == 'daily' else 4)
        assert modal.time_input.value == '1000'
        assert modal.message_input.value == 'test'
        if kind == 'weekly':
            assert [option.value for option in modal.weekday_input.options if option.default] == ['0', '6']
        elif kind != 'daily':
            assert modal.date_input.value == schedule.date_input()
            assert modal.children[0].item is modal.date_input
            assert modal.children[1].item is modal.time_input
        label = cog._autocomplete_choice_label(row)
        assert label.startswith(cog._format_schedule(1, schedule, 600) + ' · ')
        assert len(label) <= 100
        added = _DailyInformFormModal(cog, mode='add', guild_id=1, requester_id=3, channel_id=2, period=kind)
        if kind in ('monthly', 'yearly', 'once'):
            assert added.children[0].item is added.date_input
            assert added.children[1].item is added.time_input
        changed = _DailyInformFormModal(cog, mode='edit', guild_id=1, requester_id=3, row=row, period='yearly')
        if kind != 'yearly':
            assert not changed.date_input.value

    asyncio.run(check())


@pytest.mark.parametrize('raw', ['10시 31분', '1031', '10:31'])
def test_existing_time_formats(raw):
    assert make_cog()._parse_time_min(raw) == 631


def test_catchup_uses_scheduled_day_and_does_not_repeat(database, monkeypatch):
    db.ensure_schema()
    # Sunday before midnight, processed after Monday begins.
    db.add_message(1, 1439, 2, 3, 'sunday', schedule=Schedule('weekly', weekdays=64))
    db.add_message(1, 1439, 2, 3, 'monday', schedule=Schedule('weekly', weekdays=1))
    now = datetime(2026, 11, 16, 0, 1, tzinfo=KST)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr('Cogs.c_dailyInform.dt', Clock)
    cog = make_cog()
    cog._last_sent_key = (2026, 11, 15, 1438)
    cog._send_message = AsyncMock(return_value=True)
    asyncio.run(cog._daily_inform_once())
    assert [call.args[0].message for call in cog._send_message.await_args_list] == ['sunday']
    asyncio.run(cog._daily_inform_once())
    assert cog._send_message.await_count == 1


def test_registration_through_guild_command_sync(monkeypatch):
    async def check():
        bot = discord.Bot()
        cog = make_cog()
        cog.bot = bot
        bot.add_cog(cog)
        monkeypatch.setattr(lib_slash_guild_sync, '_is_command_allowed_for_guild', lambda *args: True)
        monkeypatch.setattr(lib_slash_tone_sync, '_t', lambda guild_id, key: LANG_PACK[key])
        groups = lib_slash_guild_sync._clone_feature_commands(bot, 1)
        assert len(groups) == 1
        group = groups[0]
        assert group.name == '알림'
        commands = {command.name: command for command in group.subcommands}
        assert set(commands) == {'등록', '조회', '수정', '삭제'}
        add_options = commands['등록'].options
        assert len(add_options) == 1
        assert add_options[0].name == '주기' and add_options[0].required
        assert [choice.value for choice in add_options[0].choices] == ['daily', 'weekly', 'monthly', 'yearly', 'once']
        edit_options = commands['수정'].options
        assert [option.name for option in edit_options] == [LANG_PACK['dailyInform_edit_option_name'], LANG_PACK['dailyInform_period_option_name']]
        assert not edit_options[1].required
        await bot.close()

    asyncio.run(check())


@pytest.mark.parametrize('raw', ['2026-11-14', '2026-11-15', '2026-11-16'])
def test_once_modal_accepts_only_future_times(raw, monkeypatch):
    now = datetime(2026, 11, 15, 10, 0, 30, tzinfo=KST)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr('Cogs.c_dailyInform.dt', Clock)

    async def check():
        cog = make_cog()
        modal = _DailyInformFormModal(cog, mode='add', guild_id=1, requester_id=3, channel_id=2, period='once')
        modal.date_input.value = raw
        modal.time_input.value = '1000'
        modal.message_input.value = 'message'
        interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock(), is_done=lambda: False))
        parsed = await cog._parse_modal_values(interaction, modal)
        if raw == '2026-11-16':
            assert parsed == (600, 'message', 2, parse_schedule('once', raw))
            interaction.response.send_message.assert_not_awaited()
        else:
            assert parsed is None
            interaction.response.send_message.assert_awaited_once_with(LANG_PACK['dailyInform_once_past'], ephemeral=True)

    asyncio.run(check())


def test_crud_submission_and_author_permissions(database):
    db.ensure_schema()

    async def check():
        cog = make_cog()
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=3), guild=SimpleNamespace(id=1),
            response=SimpleNamespace(send_message=AsyncMock(), is_done=lambda: False),
        )
        modal = _DailyInformFormModal(cog, mode='add', guild_id=1, requester_id=3, channel_id=2, period='weekly')
        modal.time_input.value = '15시 반'
        modal.message_input.value = 'weekly message'
        modal.weekday_input._selected_values = ['0', '6']
        await cog._handle_add_modal_submit(interaction, modal)
        row = db.get_messages_by_guild(1)[0]
        assert row.schedule == Schedule('weekly', weekdays=65)
        assert row.time_min == 930
        assert '매주 월요일, 일요일' in interaction.response.send_message.await_args.args[0]
        edit = _DailyInformFormModal(cog, mode='edit', guild_id=1, requester_id=3, row=row, period='monthly')
        edit.date_input.value = '31'
        edit.channel_select = SimpleNamespace(values=[SimpleNamespace(id=4, guild=SimpleNamespace(id=1))])
        edit.message_input.value = 'monthly message'
        await cog._handle_edit_modal_submit(interaction, edit)
        row = db.get_message_by_id(1, row.id)
        assert (row.schedule, row.channel, row.message) == (Schedule('monthly', day=31), 4, 'monthly message')
        assert not await cog._can_manage_row(SimpleNamespace(id=9), row.author)
        assert await cog._can_manage_row(interaction.user, row.author)
        await cog._handle_delete_modal_submit(interaction, SimpleNamespace(
            guild_id=1, row_id=row.id, row_message=row.message,
        ))
        assert not db.get_messages_by_guild(1)

    asyncio.run(check())


def test_long_weekly_list_fits_discord_message_limit(database):
    db.ensure_schema()
    for index in range(5):
        row_id = db.add_message(1, 600, 2, 123456789012345678, 'x' * 256)
        db.update_scheduled_message(
            1, row_id, 600, 2, 'x' * 256, schedule=Schedule('weekly', weekdays=127),
            last_editor=234567890123456789,
        )

    async def check():
        cog = make_cog()
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=1), respond=AsyncMock(),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        await dailyInform.list_daily_inform.callback(cog, ctx, page=1)
        payload = ctx.respond.await_args.kwargs
        contents = ([payload['content']] if payload['content'] else []) + [
            embed.description for embed in payload['embeds']
        ]
        assert all(len(content) <= 2000 for content in contents)
        assert ''.join(contents).count('x' * 256) == 5
        ctx.followup.send.assert_not_awaited()

    asyncio.run(check())


def test_alert_list_pagination_and_timeout():
    from Cogs.c_dailyInform import _DailyInformListView

    async def check():
        cog = make_cog()
        cog._format_list_line = lambda guild_id, order, row: f'{order}: {row}'
        rows = list(range(11))
        view = _DailyInformListView(cog, guild_id=1, rows=rows, page=1, requester_id=3)
        interaction = SimpleNamespace(user=SimpleNamespace(id=9), response=SimpleNamespace(
            send_message=AsyncMock(), edit_message=AsyncMock(),
        ))
        await view._goto(interaction, 2)
        assert view.page == 1
        interaction.response.edit_message.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()
        assert view.prev_button.disabled and not view.next_button.disabled
        interaction.user.id = 3
        await view._goto(interaction, 2)
        content = interaction.response.edit_message.await_args.kwargs['content']
        assert '6: 5' in content and '10: 9' in content and '11: 10' not in content
        assert not view.prev_button.disabled and not view.next_button.disabled
        await view._goto(interaction, 3)
        assert view.next_button.disabled
        assert '11: 10' in interaction.response.edit_message.await_args.kwargs['content']
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        view.message.edit.assert_awaited_once_with(view=None)
        view.stop()

    asyncio.run(check())


def test_two_daily_alerts_at_0515_are_both_sent(database, monkeypatch):
    db.ensure_schema()
    ids = [db.add_message(1, 315, 2, 3, message) for message in ('first', 'second')]
    now = datetime(2026, 11, 16, 5, 15, tzinfo=KST)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr('Cogs.c_dailyInform.dt', Clock)
    cog = make_cog()
    channel = SimpleNamespace(guild=SimpleNamespace(id=1), send=AsyncMock())
    cog.bot = SimpleNamespace(get_channel=lambda channel_id: channel, guilds=[SimpleNamespace(id=1)])
    assert [row.id for row in db.get_due_recurring_messages(now)] == ids
    asyncio.run(cog._daily_inform_once())
    assert [call.args[0] for call in channel.send.await_args_list] == ['first', 'second']
    assert not db.get_pending_recurring_messages('default', now)
    asyncio.run(cog._daily_inform_once())
    assert channel.send.await_count == 2


def test_recurring_overflow_survives_restart_and_shares_limit_with_once(database, monkeypatch):
    db.ensure_schema()
    for index in range(9):
        db.add_message(1, 600, 2, 3, f'recurring-{index}')
    db.add_message(1, 600, 2, 3, 'once', schedule=parse_schedule('once', '2026-11-16'))
    now = datetime(2026, 11, 16, 10, tzinfo=KST)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr('Cogs.c_dailyInform.dt', Clock)
    cog = make_cog()
    cog._scheduler_scope = 'bot'
    cog._send_message = AsyncMock(return_value=True)
    asyncio.run(cog._daily_inform_once())
    assert cog._send_message.await_count == 7
    assert len(db.get_pending_recurring_messages('bot', now)) == 2
    assert len(db.get_due_once_messages(now)) == 1
    # Restore the durable cursor in a new cog, more than 15 minutes later.
    now += timedelta(minutes=30)
    restored = make_cog()
    restored._scheduler_scope = 'bot'
    restored._last_sent_key = db.get_scheduler_state('bot')
    restored._send_message = AsyncMock(return_value=True)
    asyncio.run(restored._daily_inform_once())
    assert [call.args[0].message for call in restored._send_message.await_args_list] == [
        'recurring-7', 'recurring-8', 'once',
    ]
    assert not db.get_pending_recurring_messages('bot', now)
    asyncio.run(restored._daily_inform_once())
    assert restored._send_message.await_count == 3


def test_pending_edits_deletes_claims_and_cursor_transaction(database, monkeypatch):
    db.ensure_schema()
    ids = [db.add_message(1, 600, 2, 3, str(index)) for index in range(3)]
    now = datetime(2026, 11, 16, 10, tzinfo=KST)
    rows = db.get_due_recurring_messages(now)
    db.enqueue_recurring_messages('bot', now, rows)
    db.enqueue_recurring_messages('bot', now, rows)
    assert len(db.get_pending_recurring_messages('bot', now)) == 3
    db.update_scheduled_message(1, ids[0], 601, 2, 'edited', schedule=Schedule())
    db.delete_message_by_id(1, ids[1])
    pending = db.get_pending_recurring_messages('bot', now)
    assert len(pending) == 1
    row, scheduled_at = pending[0]
    assert db.claim_recurring_message('bot', row, scheduled_at, now)
    assert not db.claim_recurring_message('bot', row, scheduled_at, now)
    assert not db.get_pending_recurring_messages('bot', now)
    assert len(db.get_pending_recurring_messages('bot', now + timedelta(minutes=5))) == 1
    original_cursor = db.get_scheduler_state('bot')

    def fail_cursor(*args):
        raise RuntimeError('cursor write failed')

    monkeypatch.setattr(db._connectDB, 'set_scheduler_state', fail_cursor)
    with pytest.raises(RuntimeError):
        db.enqueue_recurring_messages('bot', now + timedelta(days=1), rows)
    assert db.get_scheduler_state('bot') == original_cursor
    with sqlite3.connect(database) as con:
        assert con.execute('SELECT COUNT(*) FROM test_dailyInform_pending').fetchone()[0] == 1


def test_query_indexes_are_idempotent_and_used(database):
    db.ensure_schema()
    db.ensure_schema()
    with sqlite3.connect(database) as con:
        for query in (
            'SELECT * FROM test_dailyInform WHERE time_min=600 ORDER BY id',
            'SELECT * FROM test_dailyInform WHERE guild=1 ORDER BY time_min, id',
        ):
            plan = con.execute('EXPLAIN QUERY PLAN ' + query).fetchall()
            assert any('SEARCH' in row[3] and 'INDEX' in row[3] for row in plan)


@pytest.mark.parametrize('kind', ['daily', 'once'])
def test_failures_are_bounded_and_other_guilds_progress(database, kind):
    db.ensure_schema()
    schedule = Schedule() if kind == 'daily' else parse_schedule('once', '2026-11-16')
    for index in range(30):
        db.add_message(1, 600, 2, 3, str(index), schedule=schedule)
    db.add_message(2, 600, 2, 3, 'healthy', schedule=schedule)
    now = datetime(2026, 11, 16, 10, tzinfo=KST)
    if kind == 'daily':
        db.enqueue_recurring_messages('bot', now, db.get_due_recurring_messages(now))
    cog = make_cog()
    cog._is_allowed_guild = lambda guild_id: True
    cog._send_message = AsyncMock(side_effect=lambda row: row.guild == 2)
    counts = {}
    if kind == 'daily':
        asyncio.run(cog._send_pending_recurring_messages('bot', now, counts))
        assert len(db.get_pending_recurring_messages('bot', now)) == 23
    else:
        asyncio.run(cog._send_due_once_messages(now, counts))
        assert len(db.get_due_once_messages(now)) == 23
    assert counts == {1: 7, 2: 1}
    assert cog._send_message.await_count == 8


def test_batch_overflow_is_retained_for_next_pass(database):
    db.ensure_schema()
    for guild_id in range(1, 21):
        db.add_message(guild_id, 600, 2, 3, str(guild_id), schedule=parse_schedule('once', '2026-11-16'))
    now = datetime(2026, 11, 16, 10, tzinfo=KST)
    cog = make_cog()
    cog.bot.guilds = [SimpleNamespace(id=value) for value in range(1, 21)]
    cog._MAX_ATTEMPTS_PER_SOURCE = 10
    cog._is_allowed_guild = lambda guild_id: True
    cog._send_message = AsyncMock(return_value=True)
    asyncio.run(cog._send_due_once_messages(now, {}))
    assert cog._send_message.await_count == 10
    assert len(db.get_due_once_messages(now)) == 10
    asyncio.run(cog._send_due_once_messages(now + timedelta(minutes=1), {}))
    assert cog._send_message.await_count == 20
    assert not db.get_due_once_messages(now)


def test_delivery_candidates_filters_policy_and_empty_guilds():
    async def check():
        cog = make_cog()
        query = Mock(return_value=[])
        assert [row async for row in cog._delivery_candidates(query, (), {})] == []
        assert query.call_args.kwargs['guild_ids'] == (1,)
        query.reset_mock()
        cog._is_allowed_guild = lambda guild_id: False
        assert [row async for row in cog._delivery_candidates(query, (), {})] == []
        query.assert_not_called()
        cog.bot.guilds = []
        assert [row async for row in cog._delivery_candidates(query, (), {})] == []
        query.assert_not_called()
    asyncio.run(check())


def test_slow_database_does_not_block_event_loop(monkeypatch):
    import threading
    entered = threading.Event()
    release = threading.Event()
    main_thread = threading.get_ident()
    worker_threads = []

    def slow_query(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
        return []

    monkeypatch.setattr(db, 'get_due_once_messages', slow_query)

    async def check():
        cog = make_cog()
        task = asyncio.create_task(cog._send_due_once_messages(datetime.now(KST), {}))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 1), timeout=2)
            assert not task.done()
        finally:
            release.set()
        await task
        assert worker_threads and all(thread != main_thread for thread in worker_threads)

    asyncio.run(check())


def test_deferred_modal_response_uses_followup():
    async def check():
        cog = make_cog()
        interaction = SimpleNamespace(
            response=SimpleNamespace(is_done=lambda: True, send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        await cog._respond(interaction, 'saved')
        interaction.followup.send.assert_awaited_once_with('saved', ephemeral=True)
        interaction.response.send_message.assert_not_awaited()
    asyncio.run(check())


def test_once_timestamp_migration_preserves_retries(database):
    with sqlite3.connect(database) as con:
        con.execute(
            'CREATE TABLE test_dailyInform ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, guild BIGINT NOT NULL, time_min INTEGER NOT NULL, '
            'channel BIGINT NOT NULL, author BIGINT NOT NULL DEFAULT 0, message TEXT NOT NULL, '
            "last_editor BIGINT NOT NULL DEFAULT 0, schedule_type VARCHAR(16) NOT NULL DEFAULT 'daily', "
            'weekdays INTEGER NOT NULL DEFAULT 0, month INTEGER NOT NULL DEFAULT 0, '
            'day INTEGER NOT NULL DEFAULT 0, year INTEGER NOT NULL DEFAULT 0, '
            'next_retry BIGINT NOT NULL DEFAULT 0, revision BIGINT NOT NULL DEFAULT 0);'
        )
        future_at = int(datetime(2027, 2, 28, 10, tzinfo=KST).timestamp())
        retry_at = future_at + 300
        for row_id, retry in enumerate((0, future_at - 300, retry_at), start=1):
            con.execute(
                "INSERT INTO test_dailyInform (id,guild,time_min,channel,author,message,schedule_type,month,day,year,next_retry,revision) "
                "VALUES (?,1,600,2,3,'old','once',2,28,2027,?,4);", (row_id, retry),
            )
        con.execute("INSERT INTO test_dailyInform (id,guild,time_min,channel,author,message) VALUES (4,1,600,2,3,'daily');")
    db.ensure_schema()
    db.ensure_schema()
    rows = db.get_messages_by_guild(1)
    assert [row.once_at for row in rows] == [future_at, future_at, future_at, None]
    assert [row.next_retry for row in rows] == [future_at, future_at, retry_at, 0]
    assert [row.revision for row in rows] == [4, 4, 4, 0]
    assert not db.get_due_once_messages(datetime(2027, 2, 28, 9, 59, tzinfo=KST))
    assert [row.id for row in db.get_due_once_messages(datetime(2027, 2, 28, 10, tzinfo=KST))] == [1, 2]


def test_once_timestamp_edits_and_due_index(database):
    db.ensure_schema()
    schedule = parse_schedule('once', '2027-02-28')
    row_id = db.add_message(1, 600, 2, 3, 'once', schedule=schedule)
    at = int(schedule.once_at(600).timestamp())
    row = db.get_message_by_id(1, row_id)
    assert row.once_at == row.next_retry == at
    assert not db.claim_once_message(row, schedule.once_at(599), schedule.once_at(605))
    assert db.claim_once_message(row, schedule.once_at(600), schedule.once_at(605))
    assert db.get_message_by_id(1, row_id).once_at == at
    db.update_message_time(1, row_id, 660)
    row = db.get_message_by_id(1, row_id)
    assert row.once_at == row.next_retry == at + 3600
    db.update_message_channel(1, row_id, 9)
    assert db.get_message_by_id(1, row_id).next_retry == at + 3600
    db.update_message_text(1, row_id, 'edited')
    assert not db.get_due_once_messages(schedule.once_at(600))
    assert len(db.get_due_once_messages(schedule.once_at(660), limit=1, guild_ids=(1,))) == 1
    assert not db.get_due_once_messages(schedule.once_at(660), excluded_guilds=(1,))
    db.update_scheduled_message(1, row_id, 700, 9, 'daily', schedule=Schedule())
    row = db.get_message_by_id(1, row_id)
    assert row.once_at is None and row.next_retry == 0
    with sqlite3.connect(database) as con:
        plan = con.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM test_dailyInform WHERE schedule_type='once' "
            'AND next_retry<=? ORDER BY next_retry,id LIMIT 7;', (at,),
        ).fetchall()
        assert any('idx_dailyInform_once_due' in step[3] and 'SEARCH' in step[3] for step in plan)
        assert not any('TEMP B-TREE' in step[3] for step in plan)


@pytest.mark.parametrize('raw', ['1031', '10-31', '10/31', '10.31', '10.31.', ' 10 . 31. ', '2/9', '02-09'])
def test_yearly_flexible_date_formats(raw):
    expected = Schedule('yearly', month=2, day=9) if raw in ('2/9', '02-09') else Schedule('yearly', month=10, day=31)
    assert parse_schedule('yearly', raw) == expected


@pytest.mark.parametrize('raw', [
    '20271031', '2027-10-31', '2027/10/31', '2027.10.31', '2027.10.31.',
    ' 2027 . 10 . 31 . ', '2027/2/9', '2027-02-09',
])
def test_once_flexible_date_formats(raw):
    expected = Schedule('once', month=2, day=9, year=2027) if raw in ('2027/2/9', '2027-02-09') else Schedule('once', month=10, day=31, year=2027)
    assert parse_schedule('once', raw) == expected


@pytest.mark.parametrize(('kind','raw'), [
    ('yearly','131'), ('yearly','13/1'), ('yearly','04.31.'), ('yearly','10/31/11'),
    ('once','271031'), ('once','2027.02.29.'), ('once','2027/02-29'),
    ('once','2027/10/31/2028/01/01'), ('once','2027.10.31..'),
])
def test_flexible_dates_reject_invalid_or_multiple_dates(kind, raw):
    with pytest.raises(ValueError):
        parse_schedule(kind, raw)


@pytest.mark.parametrize('first', ['-', '/', '.'])
@pytest.mark.parametrize('second', ['-', '/', '.'])
def test_once_date_accepts_mixed_separators(first, second):
    expected = Schedule('once', month=10, day=31, year=2027)
    assert parse_schedule('once', f'2027{first}10{second}31') == expected
    assert parse_schedule('once', f' 2027 {first} 10 {second} 31. ') == expected
