import csv
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

from DB.db_exp import EXP_TZ, exp_day_index, getTimeStamp
from tools import recalc_chat_cooltime as repair
from tools.daily_stats_from_log import collect, collect_day_user_exp


def test_global_chat_replays_cooltime_and_current_points_for_the_whole_log(tmp_path):
    start = datetime(2026, 11, 24, 6, tzinfo=EXP_TZ)
    rows = []

    def add(when, task, *value, guild=0, uid=42):
        rows.append((getTimeStamp(when), guild, uid, task, *value))

    def chat(when, *global_events, in_voice=False):
        add(when, 60, in_voice, guild=2)
        for task, *value in global_events:
            add(when, task, *value)
        add(when, 61, 0, guild=2)

    chat(start - timedelta(minutes=1))  # Before global tracking existed.
    chat(start, (170, False), (120, 42))
    chat(start + timedelta(seconds=49))  # Qualifies for 45s even without old task 120.
    chat(start + timedelta(seconds=75), (110,), (120, 44))
    add(start + timedelta(seconds=90), 50, 600, guild=1)
    add(start + timedelta(seconds=90), 120, 45)
    chat(start + timedelta(seconds=100), (110, True), (120, 47))
    chat(start + timedelta(seconds=120), (110, False), in_voice=True)
    chat(start + timedelta(seconds=164), in_voice=True)
    chat(start + timedelta(seconds=165))  # Exact 45s boundary with the legacy fallback.

    day_two = start + timedelta(days=1)
    chat(day_two, (111, 1), (120, 89))  # Ignore the historical +42 points.

    path = tmp_path / 'activity.csv'
    with path.open('w', newline='', encoding='utf-8') as stream:
        csv.writer(stream).writerows(rows)
    first = exp_day_index(start)
    days, _, _ = collect(path, start_idx=first, end_idx=first + 1, guild=None, cool=45)
    assert [day.total_chat for day in days.values()] == [7, 1]
    assert [day.counted_chat for day in days.values()] == [4, 1]
    assert [day.voice_tenths for day in days.values()] == [600, 0]
    assert [day.exp_delta for day in days.values()] == [63, 53]
    replay = repair.replay_log(path, 45)
    assert replay.global_[42].chat_count == sum(day.counted_chat for day in days.values())
    assert replay.global_[42].total_chat == sum(day.total_chat for day in days.values())

    for idx, day in days.items():
        _, global_exp = collect_day_user_exp(path, day_idx=idx, cool=45)
        assert sum(global_exp.values()) == day.exp_delta

    days_75, _, _ = collect(path, start_idx=first, end_idx=first, guild=None, cool=75)
    assert days_75[first].counted_chat == 3

    guild_days, _, _ = collect(path, start_idx=first, end_idx=first + 1, guild=2, cool=45)
    assert [day.counted_chat for day in guild_days.values()] == [5, 1]


def test_user_filter_keeps_global_context_and_can_be_combined_with_guild(tmp_path):
    now = datetime(2026, 11, 24, 6, tzinfo=EXP_TZ)
    ts = getTimeStamp(now)
    rows = [
        (ts, 2, 99, 60, False),
        (ts, 0, 99, 110, False),
        (ts, 2, 99, 61, 0),
        (ts + 1000, 2, 42, 60, False),
        (ts + 1000, 2, 42, 61, 0),
        (ts + 2000, 3, 42, 60, False),
        (ts + 2000, 3, 42, 61, 0),
        (ts + 3000, 3, 42, 50, 150),
    ]
    path = tmp_path / 'activity.csv'
    with path.open('w', newline='', encoding='utf-8') as stream:
        csv.writer(stream).writerows(rows)
    day = exp_day_index(now)

    global_days, _, _ = collect(path, start_idx=day, end_idx=day, guild=None, cool=45, user_id=42)
    assert (global_days[day].total_chat, global_days[day].counted_chat) == (2, 1)
    assert global_days[day].attend_uids == {42}
    assert global_days[day].voice_tenths == 150

    guild_days, _, _ = collect(path, start_idx=day, end_idx=day, guild=2, cool=45, user_id=42)
    assert (guild_days[day].total_chat, guild_days[day].counted_chat) == (1, 1)
    assert guild_days[day].voice_tenths == 0


def test_repair_only_updates_selected_global_chat_count_and_exp(monkeypatch):
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute(
            'CREATE TABLE test_global_exp (uid INTEGER PRIMARY KEY, chat_count INTEGER, '
            'exp INTEGER, last_api_call INTEGER, voice_count INTEGER, day_count INTEGER, '
            'last_call INTEGER, total_chat INTEGER)'
        )
        stored_rows = [
            (1, 309, 4206, 100, 600, 2, 95, 400),
            (2, 4, 62, 90, 0, 1, 80, 20),
            (3, 1, 53, 110, 0, 1, 110, 1),
        ]
        connection.executemany('INSERT INTO test_global_exp VALUES (?, ?, ?, ?, ?, ?, ?, ?)', stored_rows)
        connection.commit()

        @contextmanager
        def connect():
            with connection:
                yield SimpleNamespace(db_prefix='test', type='sqlite3', cur=connection.cursor())

        monkeypatch.setattr(repair, '_connectDB', connect)
        result = repair.ReplayResult(global_={
            1: repair.UserState(chat_count=323),
            2: repair.UserState(chat_count=5),
            3: repair.UserState(chat_count=2),
        }, last_ts=100)

        assert repair.repair_global_chat_from_replay(result, {1, 3}, apply=False) == 1
        assert connection.execute('SELECT * FROM test_global_exp ORDER BY uid').fetchall() == stored_rows
        assert repair.repair_global_chat_from_replay(result, {1, 3}, apply=True) == 1
        assert repair.repair_global_chat_from_replay(result, {1}, apply=True) == 0
        assert connection.execute('SELECT * FROM test_global_exp ORDER BY uid').fetchall() == [
            (1, 323, 1070, 100, 600, 2, 95, 400),
            stored_rows[1],
            stored_rows[2],
        ]

        class ConcurrentUpdateCursor(sqlite3.Cursor):
            def execute(self, sql, parameters=()):
                if sql.startswith('UPDATE'):
                    connection.execute('UPDATE test_global_exp SET voice_count=600 WHERE uid=2')
                return super().execute(sql, parameters)

        @contextmanager
        def connect_with_concurrent_update():
            with connection:
                yield SimpleNamespace(
                    db_prefix='test', type='sqlite3',
                    cur=connection.cursor(factory=ConcurrentUpdateCursor),
                )

        monkeypatch.setattr(repair, '_connectDB', connect_with_concurrent_update)
        assert repair.repair_global_chat_from_replay(result, {2}, apply=True) == 1
        assert connection.execute('SELECT * FROM test_global_exp WHERE uid=2').fetchone() == (
            2, 4, 62, 90, 600, 1, 80, 20,
        )
    finally:
        connection.close()
