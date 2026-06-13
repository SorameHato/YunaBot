# coding: utf-8
from typing import List, NamedTuple, Optional

try:
    from . db import _connectDB_raw
except ImportError:
    from db import _connectDB_raw

# Table schema (example):
# CREATE TABLE IF NOT EXISTS "<prefix>_dailyInform" (
#     "id" INTEGER PRIMARY KEY AUTOINCREMENT,
#     "guild" INTEGER NOT NULL,
#     "time_min" INTEGER NOT NULL,
#     "channel" INTEGER NOT NULL,
#     "author" INTEGER NOT NULL DEFAULT 0,
#     "last_editor" INTEGER NOT NULL DEFAULT 0,
#     "message" VARCHAR(256) NOT NULL,  # utf8mb4: 256자(한글 포함), 최대 약 1024바이트
#     UNIQUE(guild, time_min)
# );


class DailyInformRow(NamedTuple):
    id: int
    guild: int
    time_min: int
    channel: int
    author: int
    message: str
    last_editor: int = 0


class DuplicateDailyInformError(Exception):
    pass


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
                f'message TEXT NOT NULL, '
                f'UNIQUE(guild, time_min)'
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
                f'message VARCHAR(256) NOT NULL, '
                f'UNIQUE KEY uq_dailyInform_guild_time (guild, time_min)'
                f');'
            )
        self._ensure_last_editor_column()

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

    _SELECT_COLUMNS = 'id, guild, time_min, channel, author, message, last_editor'

    @staticmethod
    def _row(row) -> DailyInformRow:
        return DailyInformRow(
            id=row[0],
            guild=row[1],
            time_min=row[2],
            channel=row[3],
            author=row[4],
            message=row[5],
            last_editor=row[6] if len(row) > 6 else 0,
        )

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
        if self.has_time(guild, time_min):
            raise DuplicateDailyInformError()
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
                f'UPDATE {self.db_prefix}_dailyInform SET message=:message '
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
                f'UPDATE {self.db_prefix}_dailyInform SET message=%s '
                f'WHERE guild=%s AND time_min=%s AND channel=%s;',
                (message, guild, time_min, channel),
            )

    def update_time_by_id(self, guild: int, row_id: int, time_min: int, *, last_editor: int = 0) -> None:
        if self.has_time(guild, time_min, exclude_id=row_id):
            raise DuplicateDailyInformError()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {self.db_prefix}_dailyInform '
                f'SET time_min=:time_min, last_editor=:last_editor '
                f'WHERE guild=:guild AND id=:id;',
                {
                    'guild': guild,
                    'id': row_id,
                    'time_min': time_min,
                    'last_editor': last_editor,
                },
            )
        else:
            self.cur.execute(
                f'UPDATE {self.db_prefix}_dailyInform '
                f'SET time_min=%s, last_editor=%s '
                f'WHERE guild=%s AND id=%s;',
                (time_min, last_editor, guild, row_id),
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
                f'SET message=:message, last_editor=:last_editor '
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
                f'SET message=%s, last_editor=%s '
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
    with _connectDB() as db:
        db.ensure_schema()


def get_messages_by_time(time_min: int) -> List[DailyInformRow]:
    with _connectDB() as db:
        return db.get_by_time(time_min)


def get_messages_by_guild(guild: int) -> List[DailyInformRow]:
    with _connectDB() as db:
        return db.get_by_guild(guild)


def get_message_by_id(guild: int, row_id: int) -> Optional[DailyInformRow]:
    with _connectDB() as db:
        return db.get_by_id(guild, row_id)


def add_message(guild: int, time_min: int, channel: int, author: int, message: str) -> int:
    with _connectDB() as db:
        return db.add(guild, time_min, channel, author, message)


def update_message(guild: int, time_min: int, channel: int, message: str) -> None:
    with _connectDB() as db:
        db.update(guild, time_min, channel, message)


def update_message_time(guild: int, row_id: int, time_min: int, *, last_editor: int = 0) -> None:
    with _connectDB() as db:
        db.update_time_by_id(guild, row_id, time_min, last_editor=last_editor)


def update_message_text(guild: int, row_id: int, message: str, *, last_editor: int = 0) -> None:
    with _connectDB() as db:
        db.update_message_by_id(guild, row_id, message, last_editor=last_editor)


def delete_message(guild: int, time_min: int, channel: int) -> None:
    with _connectDB() as db:
        db.delete(guild, time_min, channel)


def delete_message_by_id(guild: int, row_id: int) -> None:
    with _connectDB() as db:
        db.delete_by_id(guild, row_id)
