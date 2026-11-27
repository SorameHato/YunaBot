import asyncio
import csv
from datetime import datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from DB import exp_log as log
from Cogs.c_expFE import expFE
from DB.db_exp import exp_day_index, getTimeStamp
from tools import daily_stats_from_log as stats, manual_daily_init, migrate_exp_log, recalc_chat_cooltime


ROLLOVER = time(5, 15)
MONTH_START = datetime(2026, 11, 1, tzinfo=log.KST)
FIRST_RESET = MONTH_START.replace(hour=5, minute=15)


def test_conversion_resume_and_rollback_keep_original_order(tmp_path, monkeypatch):
    source = tmp_path / 'legacy.csv'
    rows = [
        [getTimeStamp(MONTH_START - timedelta(milliseconds=1)), 2**64 - 1, 2**63 + 1, 61, -(2**63)],
        [getTimeStamp(MONTH_START), 0, 8, 93, '한글, 닉네임\n두 줄', '001', ''],
        [getTimeStamp(MONTH_START - timedelta(seconds=1)), 0, 0, 91, 'ok', '001'],
    ]
    with source.open('w', encoding='utf-8', newline='') as stream:
        csv.writer(stream).writerows(rows)
    source.write_bytes(source.read_bytes().rstrip(b'\r\n'))
    original = source.read_bytes()
    dest = tmp_path / 'store'
    replace = log.os.replace

    def interrupt_publish(src, dst):
        if dst == dest:
            raise OSError('interrupted migration')
        replace(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(log.os, 'replace', interrupt_publish)
        with pytest.raises(OSError, match='interrupted migration'):
            migrate_exp_log.migrate(source, dest, now=FIRST_RESET)
    assert not dest.exists()
    manifest = migrate_exp_log.migrate(source, dest, now=FIRST_RESET)
    events = list(log.iter_events(dest))
    assert manifest['months'] == {'2026-10': 2, '2026-11': 1}
    assert [e.seq for e in events] == [1, 2, 3]
    assert [e.csv_row() for e in events] == [[str(value) for value in row] for row in rows]
    assert events[0].fields == (-(2**63),)
    assert events[2].fields == ('ok', '001')
    assert (dest / '2026-10.bin.gz').exists()
    assert (dest / '2026-11.bin').exists()
    assert list(log.iter_events(dest, start_ts=getTimeStamp(MONTH_START))) == [events[1]]
    assert manual_daily_init._last_daily_init_from_log(dest) == (MONTH_START - timedelta(seconds=1), 91)

    log.append(dest, getTimeStamp(FIRST_RESET), 0, 0, 92, (1, 'manual'))
    assert migrate_exp_log.migrate(source, dest, now=FIRST_RESET) == manifest
    restored = tmp_path / 'restored.csv'
    assert migrate_exp_log.export_rollback(source, dest, restored) == 1
    assert source.read_bytes() == original
    assert [event.csv_row() for event in log.iter_events(restored)] == [
        event.csv_row() for event in log.iter_events(dest)
    ]


def test_archive_publication_recovers_and_keeps_late_writes(tmp_path, monkeypatch):
    store = tmp_path / 'store'
    old_ts = getTimeStamp(MONTH_START - timedelta(milliseconds=1))
    new_ts = getTimeStamp(MONTH_START)
    log.append(store, old_ts, 1, 8, 60, (False,))
    log.append(store, new_ts, 1, 8, 61, (-1,))
    log.archive_closed(store, FIRST_RESET - timedelta(milliseconds=1), ROLLOVER)
    assert not list(store.glob('*.gz'))

    # Simulate a writer adding a late old-month event during compression.
    compress, write_json = log._compress, log.write_json

    def compress_with_late_append(events, target):
        blocks = compress(events, target)
        log.append(store, old_ts - 8, 0, 0, 92, (2, 'late'))
        return blocks

    def interrupt_index(path, data):
        if path.suffix == '.idx':
            raise OSError('interrupted index publish')
        write_json(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(log, '_compress', compress_with_late_append)
        patch.setattr(log, 'write_json', interrupt_index)
        with pytest.raises(OSError, match='interrupted index publish'):
            log.archive_closed(store, FIRST_RESET, ROLLOVER)

    assert (store / '2026-10.bin').exists()
    assert (store / '2026-10.bin.gz').exists()
    assert not (store / '2026-10.bin.idx').exists()
    assert [event.seq for event in log.iter_events(store)] == [1, 2, 3]
    assert log.latest_init(store).seq == 3
    # The next start is several months later.
    later = datetime(2027, 1, 6, tzinfo=log.KST)
    log.archive_closed(store, later, ROLLOVER)
    log.archive_closed(store, later, ROLLOVER)
    assert not list(store.glob('*.bin'))
    assert [event.seq for event in log.iter_events(store)] == [1, 2, 3]
    assert log.latest_init(store).seq == 3


def test_torn_active_tail_is_recoverable(tmp_path):
    ts = getTimeStamp(MONTH_START)
    log.append(tmp_path, ts, 1, 8, 50, (600,))
    with (tmp_path / '2026-11.bin').open('ab') as stream:
        stream.write(b'\x30\x00\x00\x00incomplete')
    assert [event.seq for event in log.iter_events(tmp_path)] == [1]
    log.append(tmp_path, ts, 1, 8, 50, (600,))
    assert [event.seq for event in log.iter_events(tmp_path)] == [1, 2]


def test_daily_loop_archives_for_both_bot_scopes(monkeypatch):
    reset = Mock(return_value=False)
    monkeypatch.setattr('Cogs.c_expFE.db_exp.dailyDBInit', reset)
    cog = SimpleNamespace(_owns_global_daily_init=Mock(return_value=False), _archive_exp_logs=AsyncMock())
    asyncio.run(expFE._daily_init_exp_once(cog))
    reset.assert_not_called()
    cog._archive_exp_logs.assert_awaited_once()

    cog._owns_global_daily_init.return_value = True
    asyncio.run(expFE._daily_init_exp_once(cog))
    reset.assert_called_once()
    assert cog._archive_exp_logs.await_count == 2


def test_daily_checkpoint_matches_csv_across_month_and_exp_day(tmp_path, monkeypatch):
    source = tmp_path / 'legacy.csv'
    store = tmp_path / 'store'
    uid = 2**64 - 1
    day = exp_day_index(FIRST_RESET)
    seen = []

    def add(when, task, *fields, guild=0):
        ts = getTimeStamp(when)
        log.append(store, ts, guild, uid, task, fields)
        seen.append((ts, guild, uid, task, *fields))

    def as_csv():
        with source.open('w', encoding='utf-8', newline='') as stream:
            csv.writer(stream).writerows(seen)

    def compare(cool):
        as_csv()
        for guild, user in [(None, None), (2, None), (None, uid), (2, uid)]:
            args = dict(start_idx=day - 1, end_idx=day, guild=guild, cool=cool, user_id=user)
            assert stats.collect(store, **args) == stats.collect(source, **args)
            for index in (day - 1, day):
                args2 = dict(day_idx=index, cool=cool, guild=guild)
                assert stats.collect_day_user_exp(store, **args2) == stats.collect_day_user_exp(source, **args2)

    add(MONTH_START - timedelta(seconds=1), 60, False, guild=2)
    add(MONTH_START, 110, False)
    add(MONTH_START, 170, False)
    compare(45)  # Checkpoint contains a chat that ends in a different month.
    add(MONTH_START, 61, 0, guild=2)
    add(FIRST_RESET - timedelta(seconds=45), 60, False, guild=2)
    add(FIRST_RESET - timedelta(seconds=45), 110, False)
    add(FIRST_RESET - timedelta(seconds=45), 61, 0, guild=2)
    add(FIRST_RESET - timedelta(milliseconds=1), 50, 599, guild=2)
    add(FIRST_RESET, 60, False, guild=2)
    add(FIRST_RESET, 110, True)
    add(FIRST_RESET, 61, 1, guild=2)
    add(FIRST_RESET, 50, 1, guild=2)
    add(FIRST_RESET, 113, 1)
    log.archive_closed(store, FIRST_RESET, ROLLOVER)
    compare(45)
    compare(75)
    assert recalc_chat_cooltime.replay_log(store, 45) == recalc_chat_cooltime.replay_log(source, 45)

    path_open = Path.open

    def reject_archive(self, *args, **kwargs):
        assert self.suffix != '.gz', f'unnecessary archive read: {self}'
        return path_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', reject_archive)
    add(FIRST_RESET + timedelta(seconds=1), 50, 600, guild=2)
    compare(45)
