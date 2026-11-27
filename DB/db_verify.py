# coding: utf-8
from __future__ import annotations

import time
from typing import Literal, NamedTuple, Optional

from .db import _connectDB_raw

VerifyStatus = Literal['draft', 'pending', 'approved', 'rejected']
REJECT_COOLDOWN_MS = 15 * 60 * 1000


class VerifyApplication(NamedTuple):
    id: int
    guild: int
    user_id: int
    question: str
    answer: str
    status: VerifyStatus
    review_message_id: Optional[int]
    review_thread_id: Optional[int]
    reviewer_id: Optional[int]
    created_at: int
    decided_at: Optional[int]
    rejected_at: Optional[int]


def _now_ms() -> int:
    return int(time.time() * 1000)


class _connectDB(_connectDB_raw):
    _columns = (
        'id',
        'guild',
        'user_id',
        'question',
        'answer',
        'status',
        'review_message_id',
        'review_thread_id',
        'reviewer_id',
        'created_at',
        'decided_at',
        'rejected_at',
    )
    _select_columns = ', '.join(_columns)

    def __init__(self):
        super().__init__('verify')

    def _table_name(self) -> str:
        return f'{self.db_prefix}_verify'

    def _row(self, row) -> VerifyApplication:
        return VerifyApplication(
            id=row[0],
            guild=row[1],
            user_id=row[2],
            question=row[3] or '',
            answer=row[4] or '',
            status=row[5],
            review_message_id=row[6],
            review_thread_id=row[7],
            reviewer_id=row[8],
            created_at=row[9],
            decided_at=row[10],
            rejected_at=row[11],
        )

    def _table_exists(self) -> bool:
        table = self._table_name()
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

    def _existing_columns(self) -> set[str]:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(f'PRAGMA table_info({table});')
            return {row[1] for row in self.cur.fetchall()}
        self.cur.execute(f'SHOW COLUMNS FROM {table};')
        return {row[0] for row in self.cur.fetchall()}

    def ensure_schema(self) -> None:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {table} ('
                f'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                f'guild INTEGER NOT NULL, '
                f'user_id INTEGER NOT NULL, '
                f'question TEXT NOT NULL DEFAULT "", '
                f'answer TEXT NOT NULL DEFAULT "", '
                f'status TEXT NOT NULL DEFAULT "pending", '
                f'review_message_id INTEGER, '
                f'review_thread_id INTEGER, '
                f'reviewer_id INTEGER, '
                f'created_at INTEGER NOT NULL DEFAULT 0, '
                f'decided_at INTEGER, '
                f'rejected_at INTEGER, '
                f'UNIQUE(guild, user_id)'
                f');'
            )
            self.cur.execute(
                f'CREATE INDEX IF NOT EXISTS {self.db_prefix}_verify_status_idx '
                f'ON {table}(guild, status);'
            )
        else:
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {table} ('
                f'id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, '
                f'guild BIGINT NOT NULL, '
                f'user_id BIGINT NOT NULL, '
                f'question TEXT NOT NULL, '
                f'answer TEXT NOT NULL, '
                f'status VARCHAR(16) NOT NULL DEFAULT "pending", '
                f'review_message_id BIGINT NULL, '
                f'review_thread_id BIGINT NULL, '
                f'reviewer_id BIGINT NULL, '
                f'created_at BIGINT NOT NULL DEFAULT 0, '
                f'decided_at BIGINT NULL, '
                f'rejected_at BIGINT NULL, '
                f'UNIQUE KEY uq_verify_guild_user (guild, user_id), '
                f'KEY idx_verify_guild_status (guild, status)'
                f');'
            )
        self._ensure_missing_columns()

    def _ensure_missing_columns(self) -> None:
        if not self._table_exists():
            return
        existing = self._existing_columns()
        table = self._table_name()

        sqlite_columns = {
            'question': 'question TEXT NOT NULL DEFAULT ""',
            'answer': 'answer TEXT NOT NULL DEFAULT ""',
            'status': 'status TEXT NOT NULL DEFAULT "pending"',
            'review_message_id': 'review_message_id INTEGER',
            'review_thread_id': 'review_thread_id INTEGER',
            'reviewer_id': 'reviewer_id INTEGER',
            'created_at': 'created_at INTEGER NOT NULL DEFAULT 0',
            'decided_at': 'decided_at INTEGER',
            'rejected_at': 'rejected_at INTEGER',
        }
        mysql_columns = {
            'question': 'question TEXT NOT NULL',
            'answer': 'answer TEXT NOT NULL',
            'status': 'status VARCHAR(16) NOT NULL DEFAULT "pending"',
            'review_message_id': 'review_message_id BIGINT NULL',
            'review_thread_id': 'review_thread_id BIGINT NULL',
            'reviewer_id': 'reviewer_id BIGINT NULL',
            'created_at': 'created_at BIGINT NOT NULL DEFAULT 0',
            'decided_at': 'decided_at BIGINT NULL',
            'rejected_at': 'rejected_at BIGINT NULL',
        }
        column_defs = sqlite_columns if self.type == 'sqlite3' else mysql_columns
        for name, definition in column_defs.items():
            if name in existing:
                continue
            self.cur.execute(f'ALTER TABLE {table} ADD COLUMN {definition};')

    def get_by_id(self, request_id: int) -> Optional[VerifyApplication]:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {self._select_columns} FROM {table} WHERE id=:id;',
                {'id': request_id},
            )
        else:
            self.cur.execute(
                f'SELECT {self._select_columns} FROM {table} WHERE id=%s;',
                (request_id,),
            )
        row = self.cur.fetchone()
        return self._row(row) if row is not None else None

    def get_by_user(self, guild: int, user_id: int) -> Optional[VerifyApplication]:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {self._select_columns} FROM {table} '
                f'WHERE guild=:guild AND user_id=:user_id;',
                {'guild': guild, 'user_id': user_id},
            )
        else:
            self.cur.execute(
                f'SELECT {self._select_columns} FROM {table} '
                f'WHERE guild=%s AND user_id=%s;',
                (guild, user_id),
            )
        row = self.cur.fetchone()
        return self._row(row) if row is not None else None

    def get_by_review_message(self, review_message_id: int) -> Optional[VerifyApplication]:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {self._select_columns} FROM {table} '
                f'WHERE review_message_id=:review_message_id;',
                {'review_message_id': review_message_id},
            )
        else:
            self.cur.execute(
                f'SELECT {self._select_columns} FROM {table} '
                f'WHERE review_message_id=%s;',
                (review_message_id,),
            )
        row = self.cur.fetchone()
        return self._row(row) if row is not None else None

    def get_by_review_thread(self, review_thread_id: int) -> Optional[VerifyApplication]:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {self._select_columns} FROM {table} '
                f'WHERE review_thread_id=:review_thread_id;',
                {'review_thread_id': review_thread_id},
            )
        else:
            self.cur.execute(
                f'SELECT {self._select_columns} FROM {table} '
                f'WHERE review_thread_id=%s;',
                (review_thread_id,),
            )
        row = self.cur.fetchone()
        return self._row(row) if row is not None else None

    def upsert_application(
        self,
        guild: int,
        user_id: int,
        question: str,
        answer: str,
        status: VerifyStatus,
        now_ms: int,
    ) -> VerifyApplication:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT id FROM {table} WHERE guild=:guild AND user_id=:user_id;',
                {'guild': guild, 'user_id': user_id},
            )
        else:
            self.cur.execute(
                f'SELECT id FROM {table} WHERE guild=%s AND user_id=%s;',
                (guild, user_id),
            )
        row = self.cur.fetchone()
        if row is None:
            if self.type == 'sqlite3':
                self.cur.execute(
                    f'INSERT INTO {table} '
                    f'(guild, user_id, question, answer, status, created_at) '
                    f'VALUES(:guild, :user_id, :question, :answer, :status, :created_at);',
                    {
                        'guild': guild,
                        'user_id': user_id,
                        'question': question,
                        'answer': answer,
                        'status': status,
                        'created_at': now_ms,
                    },
                )
                request_id = int(self.cur.lastrowid)
            else:
                self.cur.execute(
                    f'INSERT INTO {table} '
                    f'(guild, user_id, question, answer, status, created_at) '
                    f'VALUES(%s, %s, %s, %s, %s, %s);',
                    (guild, user_id, question, answer, status, now_ms),
                )
                request_id = int(self.cur.lastrowid)
        else:
            request_id = int(row[0])
            if self.type == 'sqlite3':
                self.cur.execute(
                    f'UPDATE {table} SET '
                    f'question=:question, '
                    f'answer=:answer, '
                    f'status=:status, '
                    f'review_message_id=:review_message_id, '
                    f'reviewer_id=:reviewer_id, '
                    f'review_thread_id=:review_thread_id, '
                    f'created_at=:created_at, '
                    f'decided_at=:decided_at, '
                    f'rejected_at=:rejected_at '
                    f'WHERE id=:id;',
                    {
                        'id': request_id,
                        'question': question,
                        'answer': answer,
                        'status': status,
                        'review_message_id': None,
                        'reviewer_id': None,
                        'review_thread_id': None,
                        'created_at': now_ms,
                        'decided_at': None,
                        'rejected_at': None,
                    },
                )
            else:
                self.cur.execute(
                    f'UPDATE {table} SET '
                    f'question=%s, '
                    f'answer=%s, '
                    f'status=%s, '
                    f'review_message_id=%s, '
                    f'reviewer_id=%s, '
                    f'review_thread_id=%s, '
                    f'created_at=%s, '
                    f'decided_at=%s, '
                    f'rejected_at=%s '
                    f'WHERE id=%s;',
                    (question, answer, status, None, None, None, now_ms, None, None, request_id),
                )
        result = self.get_by_id(request_id)
        if result is None:
            raise RuntimeError('verify upsert failed')
        return result

    def upsert_pending(self, guild: int, user_id: int, question: str, answer: str, now_ms: int) -> VerifyApplication:
        return self.upsert_application(guild, user_id, question, answer, 'pending', now_ms)

    def upsert_draft(self, guild: int, user_id: int, question: str, answer: str, now_ms: int) -> VerifyApplication:
        return self.upsert_application(guild, user_id, question, answer, 'draft', now_ms)

    def bind_review_message(self, request_id: int, message_id: int) -> None:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {table} SET review_message_id=:message_id WHERE id=:id;',
                {'id': request_id, 'message_id': message_id},
            )
        else:
            self.cur.execute(
                f'UPDATE {table} SET review_message_id=%s WHERE id=%s;',
                (message_id, request_id),
            )

    def delete_by_id(self, request_id: int) -> None:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(f'DELETE FROM {table} WHERE id=:id;', {'id': request_id})
        else:
            self.cur.execute(f'DELETE FROM {table} WHERE id=%s;', (request_id,))

    def bind_review_thread(self, request_id: int, thread_id: Optional[int]) -> None:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {table} SET review_thread_id=:thread_id WHERE id=:id;',
                {'id': request_id, 'thread_id': thread_id},
            )
        else:
            self.cur.execute(
                f'UPDATE {table} SET review_thread_id=%s WHERE id=%s;',
                (thread_id, request_id),
            )

    def decide(self, request_id: int, reviewer_id: int, approved: bool, now_ms: int) -> Optional[VerifyApplication]:
        current = self.get_by_id(request_id)
        if current is None or current.status != 'pending':
            return current
        table = self._table_name()
        status: VerifyStatus = 'approved' if approved else 'rejected'
        rejected_at = None if approved else now_ms
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {table} SET '
                f'status=:status, '
                f'reviewer_id=:reviewer_id, '
                f'decided_at=:decided_at, '
                f'rejected_at=:rejected_at '
                f'WHERE id=:id;',
                {
                    'id': request_id,
                    'status': status,
                    'reviewer_id': reviewer_id,
                    'decided_at': now_ms,
                    'rejected_at': rejected_at,
                },
            )
        else:
            self.cur.execute(
                f'UPDATE {table} SET '
                f'status=%s, '
                f'reviewer_id=%s, '
                f'decided_at=%s, '
                f'rejected_at=%s '
                f'WHERE id=%s;',
                (status, reviewer_id, now_ms, rejected_at, request_id),
            )
        return self.get_by_id(request_id)


def ensure_schema() -> None:
    # Primary: lib_bot_lifecycle.ensure_core_db_schemas() (부트)
    with _connectDB() as db:
        db.ensure_schema()


def get_application(guild: int, user_id: int) -> Optional[VerifyApplication]:
    with _connectDB() as db:
        return db.get_by_user(guild, user_id)


def get_application_by_id(request_id: int) -> Optional[VerifyApplication]:
    with _connectDB() as db:
        return db.get_by_id(request_id)


def get_application_by_review_message(review_message_id: int) -> Optional[VerifyApplication]:
    with _connectDB() as db:
        return db.get_by_review_message(review_message_id)


def get_application_by_review_thread(review_thread_id: int) -> Optional[VerifyApplication]:
    with _connectDB() as db:
        return db.get_by_review_thread(review_thread_id)


def create_or_replace_pending(guild: int, user_id: int, question: str, answer: str) -> VerifyApplication:
    with _connectDB() as db:
        return db.upsert_pending(guild, user_id, (question or '').strip(), (answer or '').strip(), _now_ms())


def save_draft(guild: int, user_id: int, question: str, answer: str) -> VerifyApplication:
    with _connectDB() as db:
        return db.upsert_draft(guild, user_id, (question or '').strip(), (answer or '').strip(), _now_ms())


def delete_draft(guild: int, user_id: int) -> None:
    with _connectDB() as db:
        app = db.get_by_user(guild, user_id)
        if app is None or app.status != 'draft':
            return
        db.delete_by_id(app.id)


def bind_review_message(request_id: int, message_id: int) -> None:
    with _connectDB() as db:
        db.bind_review_message(request_id, message_id)


def bind_review_thread(request_id: int, thread_id: Optional[int]) -> None:
    with _connectDB() as db:
        db.bind_review_thread(request_id, thread_id)


def delete_if_pending_unbound(request_id: int) -> None:
    '''검토 메시지가 아직 없는 pending row만 롤백용으로 삭제한다.'''
    with _connectDB() as db:
        app = db.get_by_id(request_id)
        if app is None or app.status != 'pending' or app.review_message_id is not None:
            return
        db.delete_by_id(request_id)


def mark_approved(request_id: int, reviewer_id: int) -> Optional[VerifyApplication]:
    with _connectDB() as db:
        return db.decide(request_id, reviewer_id, approved=True, now_ms=_now_ms())


def mark_rejected(request_id: int, reviewer_id: int) -> Optional[VerifyApplication]:
    with _connectDB() as db:
        return db.decide(request_id, reviewer_id, approved=False, now_ms=_now_ms())


def is_in_reject_cooldown(
    guild: int,
    user_id: int,
    *,
    cooldown_ms: int = REJECT_COOLDOWN_MS,
    now_ms: Optional[int] = None,
) -> tuple[bool, int]:
    application = get_application(guild, user_id)
    if application is None or application.status != 'rejected' or application.rejected_at is None:
        return False, 0
    if now_ms is None:
        now_ms = _now_ms()
    elapsed = now_ms - application.rejected_at
    if elapsed >= cooldown_ms:
        return False, 0
    remain = cooldown_ms - max(0, elapsed)
    return True, remain


def has_approved_history(guild: int, user_id: int) -> bool:
    app = get_application(guild, user_id)
    return app is not None and app.status == 'approved'
