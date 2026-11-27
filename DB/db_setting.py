import json
import re
from typing import Literal, Any, Optional, Tuple, NamedTuple

from .db import _connectDB_raw

'''
DB 명세
guild, 각 설정의 n행
guild : guild의 ID (조회의 기준이 됨)

## 기본
bot_enable (BOOL DEFAULT FALSE) : 해당 서버의 초기 설정이 완료되었는지
onboarding_dm_sent (BOOL DEFAULT FALSE) : 서버 추가 시 온보딩 안내 DM(또는 대체 안내) 전송 여부
bot_admin_role (INT, NULL이어도 됨) : 해당 서버의 관리자 역할, 없으면 서버 소유자만 봇 관리자로 판단
bot_log_channel (INT) : 해당 서버에서 오류 메세지 등을 보낼 채널

## 활동점수
exp_enable (BOOL DEFAULT FALSE) : 활동점수 기능이 enable되었는지
exp_role (INT, NULL이어도 됨) : 기본적으로 주어지는 멤버의 역할 (이 역할이 있는 사람만 활동점수를 체크) / NULL이면 모든 멤버의 활동점수를 체크
exp_channel (INT, NULL이어도 됨) : 출석 메세지를 전송할 채널 / NULL이면 출석 메세지를 보내지 않음

## 톤/대사 프로필
tone_profile (VARCHAR(64) DEFAULT 'default') : 서버 별 대사/톤 프로필 키

## 표시
embed_color (INT, NULL이어도 됨) : 임베드 색상 (Discord 색상 정수) / NULL이면 기본값

## 프리미엄/면접 인증/파티
premium_enable (BOOL DEFAULT FALSE) : 프리미엄 기능 사용 가능 여부 (main 경로에서만 사용)
recruit_enable (BOOL DEFAULT FALSE) : 파티 모집 기능 사용 가능 여부 (운영자/빌링 제어)
verify_enable (BOOL DEFAULT FALSE) : 면접형 인증 기능 활성화 여부
verify_repass_enable (BOOL DEFAULT TRUE) : 기존 인증 완료 유저 재가입 시 프리패스 여부
verify_auto_reject_wrong (BOOL DEFAULT FALSE) : 정답이 있는 질문 오답 시 자동 거절 여부
recruit_thread_channel (INT, NULL이어도 됨) : 파티 종료 시 비공개 스레드를 만들 채널
  - 스레드 채팅은 부모 채널 권한을 상속함 (멤버별 overwrite 없음)
  - 참여자에게 줄 역할: view_channel, read_message_history, send_messages_in_threads
  - 권한 검사는 `/설정`에서 하지 않음 (문서 안내)
verify_panel_channel (INT, NULL이어도 됨) : 인증 패널을 게시할 채널
verify_log_channel (INT, NULL이어도 됨) : 인증 신청 로그/검토 카드 채널
verify_role (INT, NULL이어도 됨) : 승인 시 부여할 역할
verify_question (VARCHAR(512) DEFAULT '') : 신청 모달에서 보여줄 질문
verify_panel_message_id (INT, NULL이어도 됨) : 마지막 인증 패널 메시지 ID
'''

DEFAULT_EMBED_COLOR = 0xa57bdb

SettingItemBool = Literal[
    'bot_enable',
    'onboarding_dm_sent',
    'exp_enable',
    'premium_enable',
    'recruit_enable',
    'verify_enable',
    'verify_repass_enable',
    'verify_auto_reject_wrong',
]
SettingItemInt = Literal[
    'bot_admin_role',
    'bot_log_channel',
    'exp_role',
    'exp_channel',
    'embed_color',
    'recruit_thread_channel',
    'verify_panel_channel',
    'verify_log_channel',
    'verify_role',
    'verify_panel_message_id',
]
SettingItemStr = Literal[
    'tone_profile',
    'verify_question',
    'verify_questions',
]
SettingItems = SettingItemBool | SettingItemInt | SettingItemStr

# (kind, nullable, default[, char_len]) — kind: int | bool | text; text+char_len → VARCHAR(n)
_SETTING_SCHEMA: dict[str, Tuple] = {
    'guild': ('int', False, None),
    'bot_enable': ('bool', False, 0),
    'onboarding_dm_sent': ('bool', False, 0),
    'premium_enable': ('bool', False, 0),
    'recruit_enable': ('bool', False, 0),
    'bot_admin_role': ('int', True, None),
    'bot_log_channel': ('int', True, None),
    'exp_enable': ('bool', False, 0),
    'exp_role': ('int', True, None),
    'exp_channel': ('int', True, None),
    'verify_enable': ('bool', False, 0),
    'verify_repass_enable': ('bool', False, 1),
    'verify_auto_reject_wrong': ('bool', False, 0),
    'recruit_thread_channel': ('int', True, None),
    'verify_panel_channel': ('int', True, None),
    'verify_log_channel': ('int', True, None),
    'verify_role': ('int', True, None),
    'verify_question': ('text', False, '', 512),
    'verify_questions': ('text', False, ''),
    'verify_panel_message_id': ('int', True, None),
    'tone_profile': ('text', False, 'default', 64),
    'embed_color': ('int', True, None),
}

_NULLABLE_INT_ITEMS: frozenset[str] = frozenset({
    'bot_admin_role',
    'bot_log_channel',
    'exp_role',
    'exp_channel',
    'embed_color',
    'recruit_thread_channel',
    'verify_panel_channel',
    'verify_log_channel',
    'verify_role',
    'verify_panel_message_id',
})


class GuildSettings(NamedTuple):
    guild: int
    bot_enable: int
    onboarding_dm_sent: int
    premium_enable: int
    recruit_enable: int
    bot_admin_role: Optional[int]
    bot_log_channel: Optional[int]
    exp_enable: int
    exp_role: Optional[int]
    exp_channel: Optional[int]
    verify_enable: int
    verify_repass_enable: int
    verify_auto_reject_wrong: int
    recruit_thread_channel: Optional[int]
    verify_panel_channel: Optional[int]
    verify_log_channel: Optional[int]
    verify_role: Optional[int]
    verify_question: str
    verify_questions: str
    verify_panel_message_id: Optional[int]
    tone_profile: str
    embed_color: Optional[int]


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
    elif char_len is not None and not sqlite:
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
    from . import db_tone
    return set(db_tone.PROFILE_TEMPLATES.keys())


def _normalize_bool(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if value in (0, 1, '0', '1'):
        return int(value)
    raise SettingValidationError('부울 설정값은 0 또는 1이어야 해요.')


def _normalize_embed_color(value: Any, *, nullable: bool) -> Optional[int]:
    if value is None:
        if nullable:
            return None
        raise SettingValidationError('값이 비어 있어요.')
    if isinstance(value, str):
        normalized = value.strip().lstrip('#')
        if not re.fullmatch(r'[0-9a-fA-F]{6}', normalized):
            raise SettingValidationError('임베드 색상은 16진수 6자리(예: a57bdb)로 입력해 주세요.')
        return int(normalized, 16)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SettingValidationError('임베드 색상 값이 올바르지 않아요.') from exc
    if parsed < 0 or parsed > 0xFFFFFF:
        raise SettingValidationError('임베드 색상은 0x000000~0xFFFFFF 범위여야 해요.')
    return parsed


def format_embed_color(color: Optional[int]) -> str:
    resolved = color if color is not None else DEFAULT_EMBED_COLOR
    return f'#{resolved:06X}'


def get_embed_color(guild: int) -> int:
    color = get_setting(guild, 'embed_color')
    return color if color is not None else DEFAULT_EMBED_COLOR


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


def _normalize_verify_question(value: Any) -> str:
    if value is None:
        return ''
    question = str(value).strip()
    if len(question) > 512:
        raise SettingValidationError('인증 질문은 512자 이하여야 해요.')
    return question


def _normalize_verify_questions(value: Any) -> str:
    if value is None:
        return ''
    payload = str(value).strip()
    if len(payload) > 20000:
        raise SettingValidationError('인증 질문 데이터가 너무 길어요.')
    return payload


def validate_setting(item: SettingItems, data: Any) -> Any:
    if item in (
        'bot_enable',
        'onboarding_dm_sent',
        'exp_enable',
        'premium_enable',
        'recruit_enable',
        'verify_enable',
        'verify_repass_enable',
        'verify_auto_reject_wrong',
    ):
        return _normalize_bool(data)
    if item == 'embed_color':
        return _normalize_embed_color(data, nullable=True)
    if item in _NULLABLE_INT_ITEMS:
        return _normalize_int(data, nullable=True)
    if item == 'verify_question':
        return _normalize_verify_question(data)
    if item == 'verify_questions':
        return _normalize_verify_questions(data)
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
        added_onboarding_dm_sent = False
        for name, spec in _SETTING_SCHEMA.items():
            if name == 'guild' or name in existing:
                continue
            kind, nullable, default, char_len = _parse_schema(spec)
            col_def = _column_sql(name, kind, nullable, default, sqlite, char_len)
            self.cur.execute(f'ALTER TABLE {table} ADD COLUMN {col_def};')
            if name == 'onboarding_dm_sent':
                added_onboarding_dm_sent = True
        if added_onboarding_dm_sent:
            self.cur.execute(
                f'UPDATE {table} SET onboarding_dm_sent=1 WHERE onboarding_dm_sent=0;',
            )

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

    def _default_for_item(self, item: SettingItems):
        spec = _SETTING_SCHEMA.get(item)
        if spec is None:
            return None
        return _parse_schema(spec)[2]

    def get(self, guild: int, item: SettingItems):
        self.ensure_guild(guild)
        table = self._table_name()
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {item} FROM {table} WHERE guild=:guild;',
                {'guild': guild},
            )
        else:
            self.cur.execute(
                f'SELECT {item} FROM {table} WHERE guild=%s;',
                (guild,),
            )
        result = self.cur.fetchone()
        if result is not None:
            return result[0]

        # 극단적 경쟁/불일치: 재ensure 후 한 번 더 조회, 그래도 없으면 스키마 기본값
        self.ensure_guild(guild)
        if self.type == 'sqlite3':
            self.cur.execute(
                f'SELECT {item} FROM {table} WHERE guild=:guild;',
                {'guild': guild},
            )
        else:
            self.cur.execute(
                f'SELECT {item} FROM {table} WHERE guild=%s;',
                (guild,),
            )
        result = self.cur.fetchone()
        if result is None:
            return self._default_for_item(item)
        return result[0]

    def get_all(self, guild: int) -> GuildSettings:
        self.ensure_guild(guild)
        columns = (
            'bot_enable',
            'onboarding_dm_sent',
            'premium_enable',
            'recruit_enable',
            'bot_admin_role',
            'bot_log_channel',
            'exp_enable',
            'exp_role',
            'exp_channel',
            'verify_enable',
            'verify_repass_enable',
            'verify_auto_reject_wrong',
            'recruit_thread_channel',
            'verify_panel_channel',
            'verify_log_channel',
            'verify_role',
            'verify_question',
            'verify_questions',
            'verify_panel_message_id',
            'tone_profile',
            'embed_color',
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
    # Primary: lib_bot_lifecycle.ensure_core_db_schemas() (부트)
    with _connectDB() as db:
        db.ensure_schema()


def ensure_guild(guild: int) -> None:
    with _connectDB() as db:
        db.ensure_guild(guild)


def get_verify_questions(guild: int) -> list[dict]:
    """Load verify_questions JSON (max 4). Falls back to legacy verify_question."""
    raw = (get_setting(guild, 'verify_questions') or '').strip()
    if raw:
        try:
            payload = json.loads(raw)
            if isinstance(payload, list):
                out: list[dict] = []
                for item in payload[:4]:
                    if not isinstance(item, dict):
                        continue
                    question = str(item.get('question') or '').strip()
                    if not question:
                        continue
                    answers_raw = item.get('answers') or []
                    answers = (
                        [str(x).strip() for x in answers_raw if str(x).strip()]
                        if isinstance(answers_raw, list)
                        else []
                    )
                    out.append({'question': question, 'answers': answers})
                if out:
                    return out
        except Exception:
            pass
    legacy = (get_setting(guild, 'verify_question') or '').strip()
    return [{'question': legacy, 'answers': []}] if legacy else []


def save_verify_questions(guild: int, questions: list[dict]) -> None:
    """Persist verify_questions (max 4), trimming empty entries."""
    compact = []
    for item in questions[:4]:
        question = str(item.get('question') or '').strip()
        if not question:
            continue
        answers = [str(x).strip() for x in (item.get('answers') or []) if str(x).strip()]
        compact.append({'question': question, 'answers': answers})
    update_setting(guild, 'verify_questions', json.dumps(compact, ensure_ascii=False))


def get_setting(guild: int, item: SettingItems):
    with _connectDB() as db:
        return db.get(guild, item)


def get_all_settings(guild: int) -> GuildSettings:
    with _connectDB() as db:
        return db.get_all(guild)


def is_setup_ready(guild: int) -> bool:
    settings = get_all_settings(guild)
    return bool(settings.bot_log_channel)


def is_premium_enabled(guild: int) -> bool:
    return bool(get_setting(guild, 'premium_enable'))


_tone_profile_listeners: list = []
_bot_enable_listeners: list = []
_premium_enable_listeners: list = []


def register_tone_profile_listener(callback) -> None:
    _tone_profile_listeners.append(callback)


def register_bot_enable_listener(callback) -> None:
    _bot_enable_listeners.append(callback)


def register_premium_enable_listener(callback) -> None:
    _premium_enable_listeners.append(callback)


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
    if item == 'premium_enable':
        for listener in _premium_enable_listeners:
            listener(guild, normalized)


def mark_setup_complete(guild: int) -> None:
    settings = get_all_settings(guild)
    if not settings.bot_log_channel:
        raise SettingValidationError(
            '로그 채널이 설정되지 않았어요. `/초기설정 일반`을 먼저 실행해 주세요.',
        )
    update_setting(guild, 'bot_enable', 1)
