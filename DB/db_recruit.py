# coding: utf-8
from __future__ import annotations

import time
from typing import Literal, NamedTuple

from .db import _connectDB_raw

RecruitStatus = Literal['active', 'ended']


class RecruitSession(NamedTuple):
    id: int
    guild: int
    host_id: int
    channel_id: int
    message_id: int
    title: str
    max_slots: int
    ends_at: int
    create_thread: bool
    status: RecruitStatus
    thread_id: int | None
    created_at: int
    participant_ids: tuple[int, ...]


def _now_sec() -> int:
    return int(time.time())


class _connectDB(_connectDB_raw):
    def __init__(self):
        super().__init__('setting')

    def _recruit_table(self) -> str:
        return f'{self.db_prefix}_recruit'

    def _participant_table(self) -> str:
        return f'{self.db_prefix}_recruit_participant'

    def _table_exists(self, table: str) -> bool:
        if self.type == 'sqlite3':
            self.cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;",
                (table,),
            )
        else:
            self.cur.execute(
                'SELECT 1 FROM information_schema.tables '
                'WHERE table_schema=DATABASE() AND table_name=%s;',
                (table,),
            )
        return self.cur.fetchone() is not None

    def ensure_schema(self) -> None:
        recruit_table = self._recruit_table()
        participant_table = self._participant_table()
        sqlite = self.type == 'sqlite3'

        if not self._table_exists(recruit_table):
            if sqlite:
                self.cur.execute(
                    f'CREATE TABLE {recruit_table} ('
                    'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                    'guild INTEGER NOT NULL, '
                    'host_id INTEGER NOT NULL, '
                    'channel_id INTEGER NOT NULL, '
                    'message_id INTEGER NOT NULL UNIQUE, '
                    'title TEXT NOT NULL, '
                    'max_slots INTEGER NOT NULL, '
                    'ends_at INTEGER NOT NULL, '
                    'create_thread INTEGER NOT NULL DEFAULT 0, '
                    "status TEXT NOT NULL DEFAULT 'active', "
                    'thread_id INTEGER, '
                    'created_at INTEGER NOT NULL'
                    ');'
                )
                self.cur.execute(
                    f'CREATE INDEX idx_{recruit_table}_guild_status '
                    f'ON {recruit_table} (guild, status);'
                )
                self.cur.execute(
                    f'CREATE INDEX idx_{recruit_table}_host_status '
                    f'ON {recruit_table} (host_id, status);'
                )
            else:
                self.cur.execute(
                    f'CREATE TABLE {recruit_table} ('
                    'id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, '
                    'guild BIGINT NOT NULL, '
                    'host_id BIGINT NOT NULL, '
                    'channel_id BIGINT NOT NULL, '
                    'message_id BIGINT NOT NULL, '
                    'title TEXT NOT NULL, '
                    'max_slots INT NOT NULL, '
                    'ends_at BIGINT NOT NULL, '
                    'create_thread TINYINT(1) NOT NULL DEFAULT 0, '
                    "status VARCHAR(16) NOT NULL DEFAULT 'active', "
                    'thread_id BIGINT NULL, '
                    'created_at BIGINT NOT NULL, '
                    'UNIQUE KEY uq_recruit_message (message_id), '
                    'KEY idx_recruit_guild_status (guild, status), '
                    'KEY idx_recruit_host_status (host_id, status)'
                    ');'
                )

        if not self._table_exists(participant_table):
            if sqlite:
                self.cur.execute(
                    f'CREATE TABLE {participant_table} ('
                    'recruit_id INTEGER NOT NULL, '
                    'user_id INTEGER NOT NULL, '
                    'joined_at INTEGER NOT NULL, '
                    f'PRIMARY KEY (recruit_id, user_id), '
                    f'FOREIGN KEY (recruit_id) REFERENCES {recruit_table}(id) ON DELETE CASCADE'
                    ');'
                )
            else:
                self.cur.execute(
                    f'CREATE TABLE {participant_table} ('
                    'recruit_id BIGINT NOT NULL, '
                    'user_id BIGINT NOT NULL, '
                    'joined_at BIGINT NOT NULL, '
                    'PRIMARY KEY (recruit_id, user_id), '
                    f'CONSTRAINT fk_recruit_participant FOREIGN KEY (recruit_id) '
                    f'REFERENCES {recruit_table}(id) ON DELETE CASCADE'
                    ');'
                )

    def _participant_ids(self, recruit_id: int) -> tuple[int, ...]:
        participant_table = self._participant_table()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT user_id FROM {participant_table} '
                'WHERE recruit_id=:recruit_id ORDER BY joined_at ASC, user_id ASC;',
                {'recruit_id': recruit_id},
            )
        else:
            self.cur.execute(
                f'SELECT user_id FROM {participant_table} '
                'WHERE recruit_id=%s ORDER BY joined_at ASC, user_id ASC;',
                (recruit_id,),
            )
        return tuple(int(row[0]) for row in self.cur.fetchall())

    def _row_to_session(self, row, participant_ids: tuple[int, ...] | None = None) -> RecruitSession:
        recruit_id = int(row[0])
        if participant_ids is None:
            participant_ids = self._participant_ids(recruit_id)
        return RecruitSession(
            id=recruit_id,
            guild=int(row[1]),
            host_id=int(row[2]),
            channel_id=int(row[3]),
            message_id=int(row[4]),
            title=str(row[5]),
            max_slots=int(row[6]),
            ends_at=int(row[7]),
            create_thread=bool(row[8]),
            status=row[9],
            thread_id=int(row[10]) if row[10] is not None else None,
            created_at=int(row[11]),
            participant_ids=participant_ids,
        )

    def _select_columns(self) -> str:
        return (
            'id, guild, host_id, channel_id, message_id, title, max_slots, '
            'ends_at, create_thread, status, thread_id, created_at'
        )

    def create_recruit(
        self,
        *,
        guild: int,
        host_id: int,
        channel_id: int,
        message_id: int,
        title: str,
        max_slots: int,
        ends_at: int,
        create_thread: bool,
    ) -> RecruitSession:
        recruit_table = self._recruit_table()
        participant_table = self._participant_table()
        now = _now_sec()
        payload = {
            'guild': guild,
            'host_id': host_id,
            'channel_id': channel_id,
            'message_id': message_id,
            'title': title,
            'max_slots': max_slots,
            'ends_at': ends_at,
            'create_thread': 1 if create_thread else 0,
            'status': 'active',
            'thread_id': None,
            'created_at': now,
        }
        if self.type == 'sqlite3':
            self.cur.execute(
                f'INSERT INTO {recruit_table} ('
                'guild, host_id, channel_id, message_id, title, max_slots, '
                'ends_at, create_thread, status, thread_id, created_at'
                ') VALUES ('
                ':guild, :host_id, :channel_id, :message_id, :title, :max_slots, '
                ':ends_at, :create_thread, :status, :thread_id, :created_at'
                ');',
                payload,
            )
            recruit_id = int(self.cur.lastrowid)
            self.cur.execute(
                f'INSERT INTO {participant_table} (recruit_id, user_id, joined_at) '
                'VALUES (:recruit_id, :user_id, :joined_at);',
                {'recruit_id': recruit_id, 'user_id': host_id, 'joined_at': now},
            )
        else:
            self.cur.execute(
                f'INSERT INTO {recruit_table} ('
                'guild, host_id, channel_id, message_id, title, max_slots, '
                'ends_at, create_thread, status, thread_id, created_at'
                ') VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);',
                (
                    payload['guild'],
                    payload['host_id'],
                    payload['channel_id'],
                    payload['message_id'],
                    payload['title'],
                    payload['max_slots'],
                    payload['ends_at'],
                    payload['create_thread'],
                    payload['status'],
                    payload['thread_id'],
                    payload['created_at'],
                ),
            )
            self.cur.execute('SELECT LAST_INSERT_ID();')
            recruit_id = int(self.cur.fetchone()[0])
            self.cur.execute(
                f'INSERT INTO {participant_table} (recruit_id, user_id, joined_at) '
                'VALUES (%s, %s, %s);',
                (recruit_id, host_id, now),
            )
        return self.get_by_id(recruit_id)

    def get_by_id(self, recruit_id: int) -> RecruitSession | None:
        recruit_table = self._recruit_table()
        cols = self._select_columns()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {cols} FROM {recruit_table} WHERE id=:id;',
                {'id': recruit_id},
            )
        else:
            self.cur.execute(
                f'SELECT {cols} FROM {recruit_table} WHERE id=%s;',
                (recruit_id,),
            )
        row = self.cur.fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def get_by_message_id(self, message_id: int) -> RecruitSession | None:
        recruit_table = self._recruit_table()
        cols = self._select_columns()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {cols} FROM {recruit_table} WHERE message_id=:message_id;',
                {'message_id': message_id},
            )
        else:
            self.cur.execute(
                f'SELECT {cols} FROM {recruit_table} WHERE message_id=%s;',
                (message_id,),
            )
        row = self.cur.fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def list_active_by_host(self, guild: int, host_id: int) -> list[RecruitSession]:
        recruit_table = self._recruit_table()
        cols = self._select_columns()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {cols} FROM {recruit_table} '
                "WHERE guild=:guild AND host_id=:host_id AND status='active' "
                'ORDER BY created_at DESC;',
                {'guild': guild, 'host_id': host_id},
            )
        else:
            self.cur.execute(
                f'SELECT {cols} FROM {recruit_table} '
                "WHERE guild=%s AND host_id=%s AND status='active' "
                'ORDER BY created_at DESC;',
                (guild, host_id),
            )
        return [self._row_to_session(row) for row in self.cur.fetchall()]

    def list_active_expired(self, now: int | None = None) -> list[RecruitSession]:
        recruit_table = self._recruit_table()
        cols = self._select_columns()
        cutoff = now if now is not None else _now_sec()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {cols} FROM {recruit_table} '
                "WHERE status='active' AND ends_at<=:cutoff "
                'ORDER BY ends_at ASC;',
                {'cutoff': cutoff},
            )
        else:
            self.cur.execute(
                f'SELECT {cols} FROM {recruit_table} '
                "WHERE status='active' AND ends_at<=%s "
                'ORDER BY ends_at ASC;',
                (cutoff,),
            )
        return [self._row_to_session(row) for row in self.cur.fetchall()]

    def add_participant(self, recruit_id: int, user_id: int) -> RecruitSession | Literal[False] | None:
        session = self.get_by_id(recruit_id)
        if session is None or session.status != 'active':
            return None
        if user_id in session.participant_ids:
            return session

        recruit_table = self._recruit_table()
        participant_table = self._participant_table()
        now = _now_sec()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'INSERT INTO {participant_table} (recruit_id, user_id, joined_at) '
                'SELECT :recruit_id, :user_id, :joined_at '
                f'FROM {recruit_table} AS r '
                "WHERE r.id = :recruit_id AND r.status = 'active' "
                f'AND (SELECT COUNT(*) FROM {participant_table} WHERE recruit_id = r.id) < r.max_slots '
                f'AND NOT EXISTS ('
                f'SELECT 1 FROM {participant_table} '
                'WHERE recruit_id = :recruit_id AND user_id = :user_id'
                ');',
                {'recruit_id': recruit_id, 'user_id': user_id, 'joined_at': now},
            )
        else:
            self.cur.execute(
                f'INSERT INTO {participant_table} (recruit_id, user_id, joined_at) '
                'SELECT %s, %s, %s '
                f'FROM {recruit_table} AS r '
                "WHERE r.id = %s AND r.status = 'active' "
                f'AND (SELECT COUNT(*) FROM {participant_table} WHERE recruit_id = r.id) < r.max_slots '
                f'AND NOT EXISTS ('
                f'SELECT 1 FROM {participant_table} '
                'WHERE recruit_id = %s AND user_id = %s'
                ');',
                (recruit_id, user_id, now, recruit_id, recruit_id, user_id),
            )

        if (self.cur.rowcount or 0) > 0:
            return self.get_by_id(recruit_id)

        session = self.get_by_id(recruit_id)
        if session is None or session.status != 'active':
            return None
        if user_id in session.participant_ids:
            return session
        return False

    def remove_participant(self, recruit_id: int, user_id: int) -> RecruitSession | None:
        session = self.get_by_id(recruit_id)
        if session is None or session.status != 'active':
            return None
        if user_id == session.host_id:
            return session
        participant_table = self._participant_table()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'DELETE FROM {participant_table} '
                'WHERE recruit_id=:recruit_id AND user_id=:user_id;',
                {'recruit_id': recruit_id, 'user_id': user_id},
            )
        else:
            self.cur.execute(
                f'DELETE FROM {participant_table} '
                'WHERE recruit_id=%s AND user_id=%s;',
                (recruit_id, user_id),
            )
        return self.get_by_id(recruit_id)

    def mark_ended(self, recruit_id: int, *, thread_id: int | None = None) -> RecruitSession | None:
        recruit_table = self._recruit_table()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {recruit_table} '
                "SET status='ended', thread_id=:thread_id "
                "WHERE id=:id AND status='active';",
                {'id': recruit_id, 'thread_id': thread_id},
            )
        else:
            self.cur.execute(
                f'UPDATE {recruit_table} '
                "SET status='ended', thread_id=%s "
                "WHERE id=%s AND status='active';",
                (thread_id, recruit_id),
            )
        return self.get_by_id(recruit_id)

    def update_recruit(
        self,
        recruit_id: int,
        *,
        title: str,
        max_slots: int,
        ends_at: int,
        create_thread: bool,
    ) -> RecruitSession | None:
        session = self.get_by_id(recruit_id)
        if session is None or session.status != 'active':
            return None
        recruit_table = self._recruit_table()
        payload = {
            'id': recruit_id,
            'title': title,
            'max_slots': max_slots,
            'ends_at': ends_at,
            'create_thread': 1 if create_thread else 0,
        }
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {recruit_table} '
                'SET title=:title, max_slots=:max_slots, ends_at=:ends_at, create_thread=:create_thread '
                "WHERE id=:id AND status='active';",
                payload,
            )
        else:
            self.cur.execute(
                f'UPDATE {recruit_table} '
                'SET title=%s, max_slots=%s, ends_at=%s, create_thread=%s '
                "WHERE id=%s AND status='active';",
                (
                    payload['title'],
                    payload['max_slots'],
                    payload['ends_at'],
                    payload['create_thread'],
                    payload['id'],
                ),
            )
        return self.get_by_id(recruit_id)


def now_sec() -> int:
    return _now_sec()


def ensure_schema() -> None:
    with _connectDB() as db:
        db.ensure_schema()


def create_recruit(**kwargs) -> RecruitSession:
    with _connectDB() as db:
        return db.create_recruit(**kwargs)


def get_by_id(recruit_id: int) -> RecruitSession | None:
    with _connectDB() as db:
        return db.get_by_id(recruit_id)


def get_by_message_id(message_id: int) -> RecruitSession | None:
    with _connectDB() as db:
        return db.get_by_message_id(message_id)


def list_active_by_host(guild: int, host_id: int) -> list[RecruitSession]:
    with _connectDB() as db:
        return db.list_active_by_host(guild, host_id)


def list_active_expired(now: int | None = None) -> list[RecruitSession]:
    with _connectDB() as db:
        return db.list_active_expired(now)


def add_participant(recruit_id: int, user_id: int) -> RecruitSession | Literal[False] | None:
    with _connectDB() as db:
        return db.add_participant(recruit_id, user_id)


def remove_participant(recruit_id: int, user_id: int) -> RecruitSession | None:
    with _connectDB() as db:
        return db.remove_participant(recruit_id, user_id)


def mark_ended(recruit_id: int, *, thread_id: int | None = None) -> RecruitSession | None:
    with _connectDB() as db:
        return db.mark_ended(recruit_id, thread_id=thread_id)


def update_recruit(
    recruit_id: int,
    *,
    title: str,
    max_slots: int,
    ends_at: int,
    create_thread: bool,
) -> RecruitSession | None:
    with _connectDB() as db:
        return db.update_recruit(
            recruit_id,
            title=title,
            max_slots=max_slots,
            ends_at=ends_at,
            create_thread=create_thread,
        )
