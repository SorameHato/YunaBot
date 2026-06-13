from typing import Literal, Any, Optional, Tuple, NamedTuple

try:
    from .db import _connectDB_raw
except ImportError:
    from db import _connectDB_raw

'''
DB 명세
guild, 각 설정의 n행
guild : guild의 ID (조회의 기준이 됨)

## 기본
bot_enable (BOOL DEFAULT FALSE) : 해당 서버의 초기 설정이 완료되었는지
bot_admin_role (INT, NULL이어도 됨) : 해당 서버의 관리자 역할, 없으면 관리자 권한을 가지고 있는지로 판단
bot_log_channel (INT) : 해당 서버에서 오류 메세지 등을 보낼 채널

## 활동점수
exp_enable (BOOL DEFAULT FALSE) : 활동점수 기능이 enable되었는지
exp_role (INT, NULL이어도 됨) : 기본적으로 주어지는 멤버의 역할 (이 역할이 있는 사람만 활동점수를 체크) / NULL이면 모든 멤버의 활동점수를 체크
exp_channel (INT, NULL이어도 됨) : 출석 메세지를 전송할 채널 / NULL이면 출석 메세지를 보내지 않음

## 톤/대사 프로필
tone_profile (VARCHAR(64) DEFAULT 'default') : 서버 별 대사/톤 프로필 키
'''

SettingItemBool = Literal['bot_enable', 'exp_enable']
SettingItemInt = Literal['bot_admin_role', 'bot_log_channel', 'exp_role', 'exp_channel']
SettingItemStr = Literal['tone_profile']
SettingItems = SettingItemBool | SettingItemInt | SettingItemStr

# (kind, nullable, default[, char_len]) — kind: int | bool | text; text+char_len → VARCHAR(n)
_SETTING_SCHEMA: dict[str, Tuple] = {
    'guild': ('int', False, None),
    'bot_enable': ('bool', False, 0),
    'bot_admin_role': ('int', True, None),
    'bot_log_channel': ('int', True, None),
    'exp_enable': ('bool', False, 0),
    'exp_role': ('int', True, None),
    'exp_channel': ('int', True, None),
    'tone_profile': ('text', False, 'default', 64),
}

_NULLABLE_INT_ITEMS: frozenset[str] = frozenset({
    'bot_admin_role',
    'bot_log_channel',
    'exp_role',
    'exp_channel',
})


class GuildSettings(NamedTuple):
    guild: int
    bot_enable: int
    bot_admin_role: Optional[int]
    bot_log_channel: Optional[int]
    exp_enable: int
    exp_role: Optional[int]
    exp_channel: Optional[int]
    tone_profile: str


class SettingValidationError(ValueError):
    pass


def _parse_schema(spec: Tuple):
    kind, nullable, default = spec[0], spec[1], spec[2]
    char_len = spec[3] if len(spec) > 3 else None
    return kind, nullable, default, char_len


def _column_sql(
    name: str,
    kind: str,
    nullable: bool,
    default: Optional[Any],
    sqlite: bool,
    char_len: Optional[int] = None,
) -> str:
    if kind == 'int':
        base = 'INTEGER' if sqlite else 'BIGINT'
    elif kind == 'bool':
        base = 'INTEGER' if sqlite else 'TINYINT(1)'
    elif char_len is not None and sqlite:
        base = f'VARCHAR({char_len})'
    else:
        base = 'TEXT'

    parts = [name, base]
    if not nullable and name != 'guild':
        parts.append('NOT NULL')
    if default is not None:
        if isinstance(default, str):
            parts.append(f"DEFAULT '{default}'")
        else:
            parts.append(f'DEFAULT {default}')
    return ' '.join(parts)


def _valid_tone_profiles() -> set[str]:
    import db_tone
    return set(db_tone.PROFILE_TEMPLATES.keys())


def _normalize_bool(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if value in (0, 1, '0', '1'):
        return int(value)
    raise SettingValidationError('부울 설정값은 0 또는 1이어야 해요.')


def _normalize_int(value: Any, *, nullable: bool) -> Optional[int]:
    if value is None:
        if nullable:
            return None
        raise SettingValidationError('값이 비어 있어요.')
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SettingValidationError('정수 설정값이 올바르지 않아요.') from exc
    if parsed < 0:
        raise SettingValidationError('0 이상의 값만 설정할 수 있어요.')
    return parsed


def validate_setting(item: SettingItems, data: Any) -> Any:
    if item in ('bot_enable', 'exp_enable'):
        return _normalize_bool(data)
    if item in _NULLABLE_INT_ITEMS:
        return _normalize_int(data, nullable=True)
    if item == 'tone_profile':
        profile = str(data).strip()
        if not profile:
            raise SettingValidationError('언어팩 프로필 키가 비어 있어요.')
        if len(profile) > 64:
            raise SettingValidationError('언어팩 프로필 키는 64자 이하여야 해요.')
        if profile not in _valid_tone_profiles():
            raise SettingValidationError(f'알 수 없는 언어팩 프로필이에요: {profile}')
        return profile
    raise SettingValidationError(f'알 수 없는 설정 항목이에요: {item}')


class _connectDB(_connectDB_raw):
    '''
    db의 _connectDB_raw를 상속했으므로 자세한 건 해당 class의 주석을 참고할 것
    con, cur은 db.con, db.cur 로 접근 가능
    '''
    def __init__(self):
        super().__init__('setting')

    def _table_name(self) -> str:
        return f'{self.db_prefix}_setting'

    def _existing_columns(self) -> set[str]:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(f'PRAGMA table_info({table});')
            return {row[1] for row in self.cur.fetchall()}
        self.cur.execute(f'SHOW COLUMNS FROM {table};')
        return {row[0] for row in self.cur.fetchall()}

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

    def ensure_schema(self) -> None:
        sqlite = self.type == 'sqlite3'
        table = self._table_name()

        if not self._table_exists():
            cols = []
            for name, spec in _SETTING_SCHEMA.items():
                kind, nullable, default, char_len = _parse_schema(spec)
                cols.append(_column_sql(name, kind, nullable, default, sqlite, char_len))
            pk = 'guild INTEGER PRIMARY KEY' if sqlite else 'guild BIGINT NOT NULL PRIMARY KEY'
            cols[0] = pk
            self.cur.execute(f'CREATE TABLE {table} ({", ".join(cols)});')
            return

        existing = self._existing_columns()
        for name, spec in _SETTING_SCHEMA.items():
            if name == 'guild' or name in existing:
                continue
            kind, nullable, default, char_len = _parse_schema(spec)
            col_def = _column_sql(name, kind, nullable, default, sqlite, char_len)
            self.cur.execute(f'ALTER TABLE {table} ADD COLUMN {col_def};')

    def has_guild(self, guild: int) -> bool:
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT 1 FROM {table} WHERE guild=:guild LIMIT 1;',
                {'guild': guild},
            )
        else:
            self.cur.execute(
                f'SELECT 1 FROM {table} WHERE guild=%s LIMIT 1;',
                (guild,),
            )
        return self.cur.fetchone() is not None

    def ensure_guild(self, guild: int) -> None:
        if self.has_guild(guild):
            return
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'INSERT OR IGNORE INTO {table} (guild) VALUES (:guild);',
                {'guild': guild},
            )
        else:
            self.cur.execute(
                f'INSERT IGNORE INTO {table} (guild) VALUES (%s);',
                (guild,),
            )

    def get(self, guild: int, item: SettingItems):
        self.ensure_guild(guild)
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {item} FROM {self.db_prefix}_setting WHERE guild=:guild;',
                {'guild': guild},
            )
        else:
            self.cur.execute(
                f'SELECT {item} FROM {self.db_prefix}_setting WHERE guild=%s;',
                (guild,),
            )
        result = self.cur.fetchone()
        return result[0]

    def get_all(self, guild: int) -> GuildSettings:
        self.ensure_guild(guild)
        columns = (
            'bot_enable',
            'bot_admin_role',
            'bot_log_channel',
            'exp_enable',
            'exp_role',
            'exp_channel',
            'tone_profile',
        )
        joined = ', '.join(columns)
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {joined} FROM {self.db_prefix}_setting WHERE guild=:guild;',
                {'guild': guild},
            )
        else:
            self.cur.execute(
                f'SELECT {joined} FROM {self.db_prefix}_setting WHERE guild=%s;',
                (guild,),
            )
        row = self.cur.fetchone()
        return GuildSettings(guild, *row)

    def set(self, guild: int, item: SettingItems, amount: Any):
        self.ensure_guild(guild)
        if self.type == 'sqlite3':
            self.cur.execute(
                f'UPDATE {self.db_prefix}_setting SET {item}=:amount WHERE guild=:guild;',
                {'guild': guild, 'amount': amount},
            )
        else:
            self.cur.execute(
                f'UPDATE {self.db_prefix}_setting SET {item}=%s WHERE guild=%s',
                (amount, guild),
            )


def ensure_schema() -> None:
    with _connectDB() as db:
        db.ensure_schema()


def ensure_guild(guild: int) -> None:
    with _connectDB() as db:
        db.ensure_guild(guild)


def get_setting(guild: int, item: SettingItems):
    with _connectDB() as db:
        return db.get(guild, item)


def get_all_settings(guild: int) -> GuildSettings:
    with _connectDB() as db:
        return db.get_all(guild)


def is_setup_ready(guild: int) -> bool:
    settings = get_all_settings(guild)
    return bool(settings.bot_log_channel)


_tone_profile_listeners: list = []
_bot_enable_listeners: list = []


def register_tone_profile_listener(callback) -> None:
    _tone_profile_listeners.append(callback)


def register_bot_enable_listener(callback) -> None:
    _bot_enable_listeners.append(callback)


def update_setting(guild: int, item: SettingItems, data: Any):
    normalized = validate_setting(item, data)
    with _connectDB() as db:
        db.set(guild, item, normalized)
    if item == 'tone_profile':
        for listener in _tone_profile_listeners:
            listener(guild, normalized)
    if item == 'bot_enable':
        for listener in _bot_enable_listeners:
            listener(guild, normalized)


def mark_setup_complete(guild: int) -> None:
    settings = get_all_settings(guild)
    if not settings.bot_log_channel:
        raise SettingValidationError(
            '로그 채널이 설정되지 않았어요. `/초기설정 일반`을 먼저 실행해 주세요.',
        )
    update_setting(guild, 'bot_enable', 1)
