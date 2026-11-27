"""Opt-in integration checks against a disposable MySQL/MariaDB database."""
import os
import uuid
from datetime import datetime, timedelta

import pymysql
import pytest

from DB import db_dailyInform as db
from Library.lib_schedule import KST, Schedule

pytestmark = pytest.mark.skipif(not os.getenv('MYSQL_TEST_DATABASE'), reason='disposable MySQL test database not configured')


@pytest.fixture
def mysql(monkeypatch):
    prefix = 'test_' + uuid.uuid4().hex[:12]

    def connect(self):
        self.type = 'mysql'
        self.db_prefix = prefix
        self.con = pymysql.connect(
            host=os.getenv('MYSQL_TEST_HOST', '127.0.0.1'),
            port=int(os.getenv('MYSQL_TEST_PORT', '3306')),
            user=os.getenv('MYSQL_TEST_USER', 'root'),
            password=os.environ['MYSQL_TEST_PASSWORD'],
            database=os.environ['MYSQL_TEST_DATABASE'], charset='utf8mb4',
        )
        self.cur = self.con.cursor()

    monkeypatch.setattr(db._connectDB, '__init__', connect)
    yield prefix
    with db._connectDB() as connection:
        for suffix in ('_dailyInform_pending', '_dailyInform_scheduler', '_dailyInform'):
            connection.cur.execute(f'DROP TABLE IF EXISTS {prefix}{suffix}')


@pytest.mark.parametrize('has_editor', [False, True])
def test_mysql_legacy_migration_preserves_data_and_sequence(mysql, has_editor):
    table = mysql + '_dailyInform'
    with db._connectDB() as connection:
        editor = ', last_editor BIGINT NOT NULL DEFAULT 0' if has_editor else ''
        connection.cur.execute(
            f'CREATE TABLE {table} (id BIGINT AUTO_INCREMENT PRIMARY KEY, guild BIGINT NOT NULL, '
            'time_min INT NOT NULL, channel BIGINT NOT NULL, author BIGINT NOT NULL DEFAULT 0, '
            f'message VARCHAR(256) NOT NULL{editor}, UNIQUE KEY guild_time (guild,time_min))'
        )
        connection.cur.execute(f"INSERT INTO {table} (id,guild,time_min,channel,author,message) VALUES (5,1,600,2,3,'legacy'),(50,1,601,2,3,'removed')")
        connection.cur.execute(f'DELETE FROM {table} WHERE id=50')
        if has_editor:
            connection.cur.execute(f'UPDATE {table} SET last_editor=4')
    db.ensure_schema()
    db.set_scheduler_state('bot', (2026, 11, 16, 600))
    db.ensure_schema()
    assert db.get_message_by_id(1, 5) == db.DailyInformRow(5, 1, 600, 2, 3, 'legacy', 4 if has_editor else 0)
    assert db.get_scheduler_state('bot') == (2026, 11, 16, 600)
    assert db.add_message(1, 600, 2, 3, 'same time') > 50


def test_mysql_intermediate_once_migration_preserves_retry(mysql):
    db.ensure_schema()
    schedule = Schedule('once', year=2026, month=11, day=16)
    row_id = db.add_message(1, 600, 2, 3, 'once', schedule=schedule)
    retry = int(schedule.once_at(600).timestamp()) + 600
    with db._connectDB() as connection:
        connection.cur.execute(f'UPDATE {mysql}_dailyInform SET next_retry=%s', (retry,))
        connection.cur.execute(f'ALTER TABLE {mysql}_dailyInform DROP COLUMN once_at')
    db.ensure_schema()
    db.ensure_schema()
    row = db.get_message_by_id(1, row_id)
    assert row.once_at == int(schedule.once_at(600).timestamp())
    assert row.next_retry == retry
    assert row.message == 'once'


def test_mysql_delivery_claims_filters_and_edits(mysql):
    db.ensure_schema()
    now = datetime(2026, 11, 16, 10, tzinfo=KST)
    recurring = db.add_message(1, 600, 2, 3, 'daily')
    db.add_message(2, 600, 2, 3, 'other guild')
    db.enqueue_recurring_messages('bot', now, db.get_due_recurring_messages(now))
    db.enqueue_recurring_messages('bot', now, db.get_due_recurring_messages(now))
    pending = db.get_pending_recurring_messages('bot', now, guild_ids=(1,), limit=10)
    assert len(pending) == 1
    row, scheduled_at = pending[0]
    assert row.id == recurring
    assert db.claim_recurring_message('bot', row, scheduled_at, now)
    assert not db.claim_recurring_message('bot', row, scheduled_at, now)
    db.finish_recurring_message('bot', row, scheduled_at)
    assert not db.get_pending_recurring_messages('bot', now, guild_ids=(1,))
    schedule = Schedule('once', year=2026, month=11, day=16)
    once = db.add_message(1, 600, 2, 3, 'once', schedule=schedule)
    row = db.get_due_once_messages(now, guild_ids=(1,))[0]
    assert row.id == once
    assert not db.get_due_once_messages(now, guild_ids=())
    assert db.claim_once_message(row, now, now + timedelta(minutes=5))
    assert not db.claim_once_message(row, now, now + timedelta(minutes=5))
    assert not db.get_due_once_messages(now)
    assert db.update_scheduled_message(1, once, 660, 2, 'edited', schedule=schedule, last_editor=9)
    db.delete_sent_once_message(row)
    edited = db.get_message_by_id(1, once)
    assert edited.message == 'edited' and edited.last_editor == 9
    assert edited.revision == row.revision + 1
