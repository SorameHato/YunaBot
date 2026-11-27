# coding: utf-8
import calendar
from datetime import datetime
from typing import List, NamedTuple, Optional

from Library.lib_schedule import KST, Schedule

from .db import _connectDB_raw, execute_upsert


class DailyInformRow(NamedTuple):
    id: int
    guild: int
    time_min: int
    channel: int
    author: int
    message: str
    last_editor: int = 0
    schedule: Schedule = Schedule()
    next_retry: int = 0
    revision: int = 0
    once_at: int | None = None


class DuplicateDailyInformError(Exception):
    pass


MESSAGE_MAX_LEN = 256


class DailyInformValidationError(ValueError):
    pass


def validate_message(message: str) -> None:
    if len(message) > MESSAGE_MAX_LEN:
        raise DailyInformValidationError(
            f'message must be at most {MESSAGE_MAX_LEN} characters',
        )


class _connectDB(_connectDB_raw):
    def __init__(self):
        super().__init__('dailyInform')

    def ensure_schema(self) -> None:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {self.db_prefix}_dailyInform ('
                f'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                f'guild INTEGER NOT NULL, '
                f'time_min INTEGER NOT NULL, '
                f'channel INTEGER NOT NULL, '
                f'author INTEGER NOT NULL DEFAULT 0, '
                f'last_editor INTEGER NOT NULL DEFAULT 0, '
                f'message TEXT NOT NULL'
                f');'
            )
        else:
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {self.db_prefix}_dailyInform ('
                f'id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, '
                f'guild BIGINT NOT NULL, '
                f'time_min INTEGER NOT NULL, '
                f'channel BIGINT NOT NULL, '
                f'author BIGINT NOT NULL DEFAULT 0, '
                f'last_editor BIGINT NOT NULL DEFAULT 0, '
                f'message VARCHAR(256) NOT NULL'
                f');'
            )
        self._ensure_last_editor_column()
        self._ensure_schedule_columns()
        self._migrate_once_times()
        self._ensure_scheduler_table()
        self._ensure_delivery_queue()
        self._ensure_query_indexes()

    def _ensure_delivery_queue(self) -> None:
        self.cur.execute(
            f'CREATE TABLE IF NOT EXISTS {self.db_prefix}_dailyInform_pending ('
            f'scope VARCHAR(64) NOT NULL, message_id BIGINT NOT NULL, '
            f'revision BIGINT NOT NULL, scheduled_at BIGINT NOT NULL, '
            f'lease_until BIGINT NOT NULL DEFAULT 0, '
            f'PRIMARY KEY (scope, scheduled_at, message_id, revision));'
        )

    def _ensure_query_indexes(self) -> None:
        table = f'{self.db_prefix}_dailyInform'
        indexes = {
            f'{self.db_prefix}_idx_dailyInform_time': 'time_min',
            f'{self.db_prefix}_idx_dailyInform_guild_time': 'guild, time_min, id',
            f'{self.db_prefix}_idx_dailyInform_once_due': 'schedule_type, next_retry, id',
        }
        if self.type == 'sqlite3':
            for name, columns in indexes.items():
                self.cur.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns});')
        else:
            self.cur.execute(f'SHOW INDEX FROM {table};')
            existing = {row[2] for row in self.cur.fetchall()}
            for name, columns in indexes.items():
                if name not in existing:
                    self.cur.execute(f'CREATE INDEX {name} ON {table} ({columns});')

    def _ensure_scheduler_table(self) -> None:
        table = f'{self.db_prefix}_dailyInform_scheduler'
        if self.type == 'sqlite3':
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {table} ('
                f'scope TEXT PRIMARY KEY, '
                f'last_year INTEGER NOT NULL, '
                f'last_month INTEGER NOT NULL, '
                f'last_day INTEGER NOT NULL, '
                f'last_minute_of_day INTEGER NOT NULL'
                f');'
            )
        else:
            self.cur.execute(
                f'CREATE TABLE IF NOT EXISTS {table} ('
                f'scope VARCHAR(64) NOT NULL PRIMARY KEY, '
                f'last_year INT NOT NULL, '
                f'last_month INT NOT NULL, '
                f'last_day INT NOT NULL, '
                f'last_minute_of_day INT NOT NULL'
                f');'
            )

    def get_scheduler_state(self, scope: str) -> Optional[tuple[int, int, int, int]]:
        table = f'{self.db_prefix}_dailyInform_scheduler'
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT last_year, last_month, last_day, last_minute_of_day '
                f'FROM {table} WHERE scope=:scope;',
                {'scope': scope},
            )
        else:
            self.cur.execute(
                f'SELECT last_year, last_month, last_day, last_minute_of_day '
                f'FROM {table} WHERE scope=%s;',
                (scope,),
            )
        row = self.cur.fetchone()
        if row is None:
            return None
        return (row[0], row[1], row[2], row[3])

    def set_scheduler_state(self, scope: str, key: tuple[int, int, int, int]) -> None:
        table = f'{self.db_prefix}_dailyInform_scheduler'
        year, month, day, minute_of_day = key
        execute_upsert(
            self,
            table=table,
            columns=(
                'scope',
                'last_year',
                'last_month',
                'last_day',
                'last_minute_of_day',
            ),
            values={
                'scope': scope,
                'last_year': year,
                'last_month': month,
                'last_day': day,
                'last_minute_of_day': minute_of_day,
            },
            conflict_columns=('scope',),
            update_columns=(
                'last_year',
                'last_month',
                'last_day',
                'last_minute_of_day',
            ),
        )

    def _ensure_last_editor_column(self) -> None:
        table = f'{self.db_prefix}_dailyInform'
        if self.type == 'sqlite3':
            self.cur.execute(f'PRAGMA table_info({table});')
            columns = {row[1] for row in self.cur.fetchall()}
            if 'last_editor' not in columns:
                self.cur.execute(
                    f'ALTER TABLE {table} ADD COLUMN last_editor INTEGER NOT NULL DEFAULT 0;'
                )
        else:
            self.cur.execute(
                f'SHOW COLUMNS FROM {table} LIKE %s;',
                ('last_editor',),
            )
            if self.cur.fetchone() is None:
                self.cur.execute(
                    f'ALTER TABLE {table} ADD COLUMN last_editor BIGINT NOT NULL DEFAULT 0;'
                )

    def _ensure_schedule_columns(self) -> None:
        table = f'{self.db_prefix}_dailyInform'
        columns = {
            'schedule_type': "VARCHAR(16) NOT NULL DEFAULT 'daily'",
            'weekdays': 'INTEGER NOT NULL DEFAULT 0',
            'month': 'INTEGER NOT NULL DEFAULT 0',
            'day': 'INTEGER NOT NULL DEFAULT 0',
            'year': 'INTEGER NOT NULL DEFAULT 0',
            'next_retry': 'BIGINT NOT NULL DEFAULT 0',
            'revision': 'BIGINT NOT NULL DEFAULT 0',
            'once_at': 'BIGINT DEFAULT NULL',
        }
        if self.type == 'sqlite3':
            # Keep DDL and the copy in one transaction, including rollback on failure.
            self.cur.execute('BEGIN IMMEDIATE;')
            self.cur.execute(f'PRAGMA table_info({table});')
            existing = {row[1] for row in self.cur.fetchall()}
            for name, definition in columns.items():
                if name not in existing:
                    self.cur.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition};')
            self.cur.execute(f'PRAGMA index_list({table});')
            indexes = self.cur.fetchall()
            for index in indexes:
                if not index[2]:
                    continue
                name = index[1].replace('"', '""')
                self.cur.execute(f'PRAGMA index_info("{name}");')
                if [row[2] for row in self.cur.fetchall()] != ['guild', 'time_min']:
                    continue
                # SQLite autoindexes for UNIQUE constraints require a table rebuild.
                self.cur.execute(f'SELECT seq FROM sqlite_sequence WHERE name=?;', (table,))
                sequence = self.cur.fetchone()
                self.cur.execute(
                    f'CREATE TABLE {table}_migration ('
                    f'id INTEGER PRIMARY KEY AUTOINCREMENT, guild INTEGER NOT NULL, '
                    f'time_min INTEGER NOT NULL, channel INTEGER NOT NULL, '
                    f'author INTEGER NOT NULL DEFAULT 0, last_editor INTEGER NOT NULL DEFAULT 0, '
                    f'message TEXT NOT NULL, '
                    + ', '.join(f'{name} {definition}' for name, definition in columns.items())
                    + ');'
                )
                names = self._SELECT_COLUMNS
                self.cur.execute(f'INSERT INTO {table}_migration ({names}) SELECT {names} FROM {table};')
                self.cur.execute(f'DROP TABLE {table};')
                self.cur.execute(f'ALTER TABLE {table}_migration RENAME TO {table};')
                if sequence is not None:
                    self.cur.execute('UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name=?;', (sequence[0], table))
                break
        else:
            self.cur.execute(f'SHOW COLUMNS FROM {table};')
            existing = {row[0] for row in self.cur.fetchall()}
            for name, definition in columns.items():
                if name not in existing:
                    self.cur.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition};')
            self.cur.execute(f'SHOW INDEX FROM {table};')
            unique_indexes = {}
            for row in self.cur.fetchall():
                if row[1] == 0 and row[2] != 'PRIMARY':
                    unique_indexes.setdefault(row[2], []).append((row[3], row[4]))
            for name, fields in unique_indexes.items():
                if [field for _, field in sorted(fields)] == ['guild', 'time_min']:
                    quoted_name = name.replace('`', '``')
                    self.cur.execute(f'ALTER TABLE {table} DROP INDEX `{quoted_name}`;')

    def _migrate_once_times(self) -> None:
        table = f'{self.db_prefix}_dailyInform'
        # NULL marks unconverted rows, so interrupted MySQL migrations can resume.
        while True:
            self._execute(
                f'SELECT id, year, month, day, time_min FROM {table} '
                f"WHERE schedule_type='once' AND once_at IS NULL ORDER BY id LIMIT 500;", (),
            )
            rows = self.cur.fetchall()
            if not rows:
                return
            for row_id, year, month, day, time_min in rows:
                once_at = _once_timestamp(Schedule('once', month=month, day=day, year=year), time_min)
                self._execute(
                    f'UPDATE {table} SET once_at=%s, '
                    f'next_retry=CASE WHEN next_retry>%s THEN next_retry ELSE %s END '
                    f"WHERE id=%s AND schedule_type='once' AND once_at IS NULL;",
                    (once_at, once_at, once_at, row_id),
                )

    _SELECT_COLUMNS = (
        'id, guild, time_min, channel, author, message, last_editor, '
        'schedule_type, weekdays, month, day, year, next_retry, revision, once_at'
    )

    @staticmethod
    def _row(row) -> DailyInformRow:
        return DailyInformRow(
            *row[:7], schedule=Schedule(*row[7:12]), next_retry=row[12], revision=row[13], once_at=row[14],
        )

    def _execute(self, query: str, params: tuple) -> None:
        if self.type == 'sqlite3':
            query = query.replace('%s', '?')
        self.cur.execute(query, params)

    def has_time(self, guild: int, time_min: int, exclude_id: Optional[int] = None) -> bool:
        if self.type == 'sqlite3':
            params = {'guild': guild, 'time_min': time_min}
            query = (
                f'SELECT 1 FROM {self.db_prefix}_dailyInform '
                f'WHERE guild=:guild AND time_min=:time_min'
            )
            if exclude_id is not None:
                query += ' AND id!=:exclude_id'
                params['exclude_id'] = exclude_id
            self.cur.execute(query + ' LIMIT 1;', params)
        else:
            params = [guild, time_min]
            query = (
                f'SELECT 1 FROM {self.db_prefix}_dailyInform '
                f'WHERE guild=%s AND time_min=%s'
            )
            if exclude_id is not None:
                query += ' AND id!=%s'
                params.append(exclude_id)
            self.cur.execute(query + ' LIMIT 1;', tuple(params))
        return self.cur.fetchone() is not None

    def get_by_time(self, time_min: int) -> List[DailyInformRow]:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {self._SELECT_COLUMNS} '
                f'FROM {self.db_prefix}_dailyInform WHERE time_min=:time_min;',
                {'time_min': time_min},
            )
        else:
            self.cur.execute(
                f'SELECT {self._SELECT_COLUMNS} '
                f'FROM {self.db_prefix}_dailyInform WHERE time_min=%s;',
                (time_min,),
            )
        return [self._row(row) for row in self.cur.fetchall()]

    def get_by_guild(self, guild: int) -> List[DailyInformRow]:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {self._SELECT_COLUMNS} '
                f'FROM {self.db_prefix}_dailyInform WHERE guild=:guild '
                f'ORDER BY time_min ASC, id ASC;',
                {'guild': guild},
            )
        else:
            self.cur.execute(
                f'SELECT {self._SELECT_COLUMNS} '
                f'FROM {self.db_prefix}_dailyInform WHERE guild=%s '
                f'ORDER BY time_min ASC, id ASC;',
                (guild,),
            )
        return [self._row(row) for row in self.cur.fetchall()]

    def get_by_id(self, guild: int, row_id: int) -> Optional[DailyInformRow]:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {self._SELECT_COLUMNS} '
                f'FROM {self.db_prefix}_dailyInform WHERE guild=:guild AND id=:id;',
                {'guild': guild, 'id': row_id},
            )
        else:
            self.cur.execute(
                f'SELECT {self._SELECT_COLUMNS} '
                f'FROM {self.db_prefix}_dailyInform WHERE guild=%s AND id=%s;',
                (guild, row_id),
            )
        row = self.cur.fetchone()
        return self._row(row) if row is not None else None

    def add(self, guild: int, time_min: int, channel: int, author: int, message: str) -> int:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'INSERT INTO {self.db_prefix}_dailyInform '
                f'(guild, time_min, channel, author, message) '
                f'VALUES(:guild, :time_min, :channel, :author, :message);',
                {
                    'guild': guild,
                    'time_min': time_min,
                    'channel': channel,
                    'author': author,
                    'message': message,
                },
            )
        else:
            self.cur.execute(
                f'INSERT INTO {self.db_prefix}_dailyInform '
                f'(guild, time_min, channel, author, message) '
                f'VALUES(%s, %s, %s, %s, %s);',
                (guild, time_min, channel, author, message),
            )
        return self.cur.lastrowid

    def update(self, guild: int, time_min: int, channel: int, message: str) -> None:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {self.db_prefix}_dailyInform SET message=:message, revision=revision+1, next_retry=COALESCE(once_at, 0) '
                f'WHERE guild=:guild AND time_min=:time_min AND channel=:channel;',
                {
                    'guild': guild,
                    'time_min': time_min,
                    'channel': channel,
                    'message': message,
                },
            )
        else:
            self.cur.execute(
                f'UPDATE {self.db_prefix}_dailyInform SET message=%s, revision=revision+1, next_retry=COALESCE(once_at, 0) '
                f'WHERE guild=%s AND time_min=%s AND channel=%s;',
                (message, guild, time_min, channel),
            )

    def update_time_by_id(self, guild: int, row_id: int, time_min: int, *, last_editor: int = 0) -> None:
        if not 0 <= time_min < 1440:
            raise DailyInformValidationError('invalid time')
        # Assign time_min last so MySQL expressions use the original minute value.
        self._execute(
            f'UPDATE {self.db_prefix}_dailyInform '
            f'SET next_retry=COALESCE(once_at+(%s-time_min)*60, 0), '
            f'once_at=once_at+(%s-time_min)*60, time_min=%s, '
            f'last_editor=%s, revision=revision+1 WHERE guild=%s AND id=%s;',
            (time_min, time_min, time_min, last_editor, guild, row_id),
        )

    def update_channel_by_id(
        self,
        guild: int,
        row_id: int,
        channel: int,
        *,
        last_editor: int = 0,
    ) -> None:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {self.db_prefix}_dailyInform '
                f'SET channel=:channel, last_editor=:last_editor, revision=revision+1, next_retry=COALESCE(once_at, 0) '
                f'WHERE guild=:guild AND id=:id;',
                {
                    'guild': guild,
                    'id': row_id,
                    'channel': channel,
                    'last_editor': last_editor,
                },
            )
        else:
            self.cur.execute(
                f'UPDATE {self.db_prefix}_dailyInform '
                f'SET channel=%s, last_editor=%s, revision=revision+1, next_retry=COALESCE(once_at, 0) '
                f'WHERE guild=%s AND id=%s;',
                (channel, last_editor, guild, row_id),
            )

    def update_message_by_id(
        self,
        guild: int,
        row_id: int,
        message: str,
        *,
        last_editor: int = 0,
    ) -> None:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {self.db_prefix}_dailyInform '
                f'SET message=:message, last_editor=:last_editor, revision=revision+1, next_retry=COALESCE(once_at, 0) '
                f'WHERE guild=:guild AND id=:id;',
                {
                    'guild': guild,
                    'id': row_id,
                    'message': message,
                    'last_editor': last_editor,
                },
            )
        else:
            self.cur.execute(
                f'UPDATE {self.db_prefix}_dailyInform '
                f'SET message=%s, last_editor=%s, revision=revision+1, next_retry=COALESCE(once_at, 0) '
                f'WHERE guild=%s AND id=%s;',
                (message, last_editor, guild, row_id),
            )

    def delete(self, guild: int, time_min: int, channel: int) -> None:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'DELETE FROM {self.db_prefix}_dailyInform '
                f'WHERE guild=:guild AND time_min=:time_min AND channel=:channel;',
                {'guild': guild, 'time_min': time_min, 'channel': channel},
            )
        else:
            self.cur.execute(
                f'DELETE FROM {self.db_prefix}_dailyInform '
                f'WHERE guild=%s AND time_min=%s AND channel=%s;',
                (guild, time_min, channel),
            )

    def delete_by_id(self, guild: int, row_id: int) -> None:
        if self.type == 'sqlite3':
            self.cur.execute(
                f'DELETE FROM {self.db_prefix}_dailyInform '
                f'WHERE guild=:guild AND id=:id;',
                {'guild': guild, 'id': row_id},
            )
        else:
            self.cur.execute(
                f'DELETE FROM {self.db_prefix}_dailyInform '
                f'WHERE guild=%s AND id=%s;',
                (guild, row_id),
            )


def ensure_schema() -> None:
    # Primary: lib_bot_lifecycle.ensure_core_db_schemas() (부트)
    with _connectDB() as db:
        db.ensure_schema()


def get_messages_by_time(time_min: int) -> List[DailyInformRow]:
    with _connectDB() as db:
        return db.get_by_time(time_min)


def get_due_recurring_messages(when: datetime) -> List[DailyInformRow]:
    """Select recurring messages for the scheduled minute, including month-end rules."""
    when = when.astimezone(KST)
    time_min = when.hour * 60 + when.minute
    weekday_bit = 1 << when.weekday()
    is_month_end = int(when.day == calendar.monthrange(when.year, when.month)[1])
    with _connectDB() as db:
        db._execute(
            f'SELECT {db._SELECT_COLUMNS} FROM {db.db_prefix}_dailyInform '
            f'WHERE time_min=%s AND ('
            f"schedule_type='daily' "
            f"OR (schedule_type='weekly' AND (weekdays & %s)<>0) "
            f"OR (schedule_type='monthly' AND (day=%s OR (%s=1 AND day>%s))) "
            f"OR (schedule_type='yearly' AND month=%s "
            f'AND (day=%s OR (%s=1 AND day>%s)))) '
            f'ORDER BY id;',
            (
                time_min, weekday_bit,
                when.day, is_month_end, when.day,
                when.month, when.day, is_month_end, when.day,
            ),
        )
        return [db._row(row) for row in db.cur.fetchall()]


def enqueue_recurring_messages(scope: str, when: datetime, rows: List[DailyInformRow]) -> None:
    """Commit pending deliveries and the scan cursor together."""
    when = when.astimezone(KST)
    with _connectDB() as db:
        for row in rows:
            execute_upsert(
                db, table=f'{db.db_prefix}_dailyInform_pending',
                columns=('scope', 'scheduled_at', 'message_id', 'revision'),
                values={'scope': scope, 'scheduled_at': int(when.timestamp()),
                        'message_id': row.id, 'revision': row.revision},
                conflict_columns=('scope', 'scheduled_at', 'message_id', 'revision'),
                update_columns=('message_id',),
            )
        db.set_scheduler_state(scope, (when.year, when.month, when.day, when.hour * 60 + when.minute))


def _delivery_filter(guild_column: str, excluded_guilds: tuple[int, ...], guild_ids: tuple[int, ...] | None):
    clauses = ''
    params = ()
    if guild_ids is not None:
        if not guild_ids:
            return ' AND 1=0', ()
        clauses += f" AND {guild_column} IN ({', '.join(['%s'] * len(guild_ids))})"
        params += guild_ids
    if excluded_guilds:
        clauses += f" AND {guild_column} NOT IN ({', '.join(['%s'] * len(excluded_guilds))})"
        params += excluded_guilds
    return clauses, params


def get_pending_recurring_messages(
    scope: str, now: datetime, *, limit: int | None = None,
    excluded_guilds: tuple[int, ...] = (), guild_ids: tuple[int, ...] | None = None,
) -> list[tuple[DailyInformRow, int]]:
    with _connectDB() as db:
        pending = f'{db.db_prefix}_dailyInform_pending'
        messages = f'{db.db_prefix}_dailyInform'
        # Edited or deleted reservations invalidate their old pending deliveries.
        db._execute(
            f'DELETE FROM {pending} WHERE scope=%s AND NOT EXISTS ('
            f'SELECT 1 FROM {messages} m WHERE m.id={pending}.message_id '
            f"AND m.revision={pending}.revision AND m.schedule_type<>'once');", (scope,),
        )
        filters, filter_params = _delivery_filter('m.guild', excluded_guilds, guild_ids)
        limit_sql = ' LIMIT %s' if limit is not None else ''
        limit_params = (limit,) if limit is not None else ()
        columns = ', '.join('m.' + column.strip() for column in db._SELECT_COLUMNS.split(','))
        db._execute(
            f'SELECT {columns}, p.scheduled_at FROM {pending} p '
            f'JOIN {messages} m ON m.id=p.message_id AND m.revision=p.revision '
            f'WHERE p.scope=%s AND p.lease_until<=%s{filters} '
            f'ORDER BY p.scheduled_at, p.message_id{limit_sql};',
            (scope, int(now.timestamp()), *filter_params, *limit_params),
        )
        return [(db._row(row[:-1]), row[-1]) for row in db.cur.fetchall()]


def claim_recurring_message(scope: str, row: DailyInformRow, scheduled_at: int, now: datetime) -> bool:
    with _connectDB() as db:
        db._execute(
            f'UPDATE {db.db_prefix}_dailyInform_pending SET lease_until=%s '
            f'WHERE scope=%s AND scheduled_at=%s AND message_id=%s AND revision=%s '
            f'AND lease_until<=%s AND EXISTS ('
            f'SELECT 1 FROM {db.db_prefix}_dailyInform m WHERE m.id=%s AND m.revision=%s);',
            (int(now.timestamp()) + 300, scope, scheduled_at, row.id, row.revision,
             int(now.timestamp()), row.id, row.revision),
        )
        return db.cur.rowcount > 0


def finish_recurring_message(scope: str, row: DailyInformRow, scheduled_at: int) -> None:
    with _connectDB() as db:
        db._execute(
            f'DELETE FROM {db.db_prefix}_dailyInform_pending '
            f'WHERE scope=%s AND scheduled_at=%s AND message_id=%s AND revision=%s;',
            (scope, scheduled_at, row.id, row.revision),
        )


def get_messages_by_guild(guild: int) -> List[DailyInformRow]:
    with _connectDB() as db:
        return db.get_by_guild(guild)


def get_message_by_id(guild: int, row_id: int) -> Optional[DailyInformRow]:
    with _connectDB() as db:
        return db.get_by_id(guild, row_id)


def _validate_values(time_min: int, message: str, schedule: Schedule) -> None:
    validate_message(message)
    if not 0 <= time_min < 1440 or not message.strip():
        raise DailyInformValidationError('invalid time or empty message')
    try:
        schedule.validate()
    except ValueError as exc:
        raise DailyInformValidationError(str(exc)) from exc


def _once_timestamp(schedule: Schedule, time_min: int) -> int | None:
    if schedule.kind != 'once':
        return None
    return int(schedule.once_at(time_min).timestamp())


def add_message(
    guild: int, time_min: int, channel: int, author: int, message: str,
    *, schedule: Schedule = Schedule(),
) -> int:
    _validate_values(time_min, message, schedule)
    once_at = _once_timestamp(schedule, time_min)
    with _connectDB() as db:
        db._execute(
            f'INSERT INTO {db.db_prefix}_dailyInform '
            f'(guild, time_min, channel, author, message, schedule_type, weekdays, month, day, year, once_at, next_retry) '
            f'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);',
            (guild, time_min, channel, author, message, *schedule, once_at, once_at or 0),
        )
        return db.cur.lastrowid


def update_scheduled_message(
    guild: int, row_id: int, time_min: int, channel: int, message: str,
    *, schedule: Schedule, last_editor: int = 0,
) -> bool:
    _validate_values(time_min, message, schedule)
    once_at = _once_timestamp(schedule, time_min)
    with _connectDB() as db:
        db._execute(
            f'UPDATE {db.db_prefix}_dailyInform SET time_min=%s, channel=%s, message=%s, '
            f'schedule_type=%s, weekdays=%s, month=%s, day=%s, year=%s, last_editor=%s, '
            f'once_at=%s, next_retry=%s, revision=revision+1 WHERE guild=%s AND id=%s;',
            (time_min, channel, message, *schedule, last_editor, once_at, once_at or 0, guild, row_id),
        )
        return db.cur.rowcount > 0


def get_due_once_messages(
    now: datetime, *, limit: int | None = None, excluded_guilds: tuple[int, ...] = (),
    guild_ids: tuple[int, ...] | None = None,
) -> List[DailyInformRow]:
    now = now.astimezone(KST)
    filters, filter_params = _delivery_filter('guild', excluded_guilds, guild_ids)
    limit_sql = ' LIMIT %s' if limit is not None else ''
    limit_params = (limit,) if limit is not None else ()
    with _connectDB() as db:
        db._execute(
            f'SELECT {db._SELECT_COLUMNS} FROM {db.db_prefix}_dailyInform '
            f"WHERE schedule_type='once' AND next_retry<=%s{filters} "
            f'ORDER BY next_retry, id{limit_sql};',
            (int(now.timestamp()), *filter_params, *limit_params),
        )
        return [db._row(row) for row in db.cur.fetchall()]


def claim_once_message(row: DailyInformRow, now: datetime, retry_at: datetime) -> bool:
    """Persist the retry delay before sending, and reject stale or concurrent claims."""
    with _connectDB() as db:
        db._execute(
            f'UPDATE {db.db_prefix}_dailyInform SET next_retry=%s '
            f"WHERE guild=%s AND id=%s AND revision=%s AND schedule_type='once' AND next_retry<=%s;",
            (int(retry_at.timestamp()), row.guild, row.id, row.revision, int(now.timestamp())),
        )
        return db.cur.rowcount > 0


def delete_sent_once_message(row: DailyInformRow) -> None:
    # An edit while Discord is sending creates a new revision and must survive.
    with _connectDB() as db:
        db._execute(
            f'DELETE FROM {db.db_prefix}_dailyInform '
            f"WHERE guild=%s AND id=%s AND revision=%s AND schedule_type='once';",
            (row.guild, row.id, row.revision),
        )


def update_message(guild: int, time_min: int, channel: int, message: str) -> None:
    validate_message(message)
    with _connectDB() as db:
        db.update(guild, time_min, channel, message)


def update_message_time(guild: int, row_id: int, time_min: int, *, last_editor: int = 0) -> None:
    with _connectDB() as db:
        db.update_time_by_id(guild, row_id, time_min, last_editor=last_editor)


def update_message_text(guild: int, row_id: int, message: str, *, last_editor: int = 0) -> None:
    validate_message(message)
    with _connectDB() as db:
        db.update_message_by_id(guild, row_id, message, last_editor=last_editor)


def update_message_channel(guild: int, row_id: int, channel: int, *, last_editor: int = 0) -> None:
    with _connectDB() as db:
        db.update_channel_by_id(guild, row_id, channel, last_editor=last_editor)


def delete_message(guild: int, time_min: int, channel: int) -> None:
    with _connectDB() as db:
        db.delete(guild, time_min, channel)


def delete_message_by_id(guild: int, row_id: int) -> None:
    with _connectDB() as db:
        db.delete_by_id(guild, row_id)


def get_scheduler_state(scope: str) -> Optional[tuple[int, int, int, int]]:
    with _connectDB() as db:
        return db.get_scheduler_state(scope)


def set_scheduler_state(scope: str, key: tuple[int, int, int, int]) -> None:
    with _connectDB() as db:
        db.set_scheduler_state(scope, key)
