#!/usr/bin/env python3
"""EXP 로그를 읽어 경험치일(05:15 KST) 단위로 활동 통계를 출력한다.

지표:
  총 채팅     — total_chat (쿨타임·통화 여부와 무관하게 온 채팅)
  집계 채팅   — chat_count (쿨타임이 지나 점수로 인정된 채팅)
  통화(초)    — voice_count / 10
  출석 인원   — 그날 day_count 가 오른 고유 uid
  증가 EXP    — 그날 인정된 chat/voice/출석으로 늘어난 공식 EXP

기본: 최근 7 경험치일, global_exp 스코프.
날짜 범위(--from/--to/--days), 서버(--guild), 유저(--uid)를 지정할 수 있다.
전 기간을 지정한 채팅 쿨타임과 현재 배점으로 다시 집계한다.
글로벌 통화 여부는 110번 값을 우선하며, 값이 없으면 60번의 서버별 값으로 추정한다.

Examples:
  python tools/daily_stats_from_log.py
  python tools/daily_stats_from_log.py --days 14
  python tools/daily_stats_from_log.py --from 2026-08-01 --to 2026-08-31
  python tools/daily_stats_from_log.py --guild 1517783211051192350
  python tools/daily_stats_from_log.py --uid 1470810710379466934
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import unicodedata
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime as dt
from datetime import timedelta as td
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

from DB.db_exp import (  # noqa: E402
    EXP_DAY_EPOCH,
    EXP_DAY_ROLLOVER,
    EXP_TZ,
    chatCooltime,
    chatPoint,
    dayPoint,
    exp_day_index,
    fromTimeStamp,
    getNow,
    voiceCooltime,
    voicePoint,
)
from DB.exp_log import Event, iter_events, resolve_log  # noqa: E402
from recalc_chat_cooltime import (  # noqa: E402
    GlobalChat,
    GlobalChatLog,
    UserState,
    _mark_attend,
    _parse_bool,
    _via_voice_last_ts,
    replay_global_chat,
)

_REPLAY_VERSION = 1


@dataclass
class DayStats:
    total_chat: int = 0
    counted_chat: int = 0
    voice_tenths: int = 0
    attend_uids: set[int] = field(default_factory=set)
    exp_delta: int = 0


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding='utf-8')
        except Exception:
            pass


def exp_idx_to_date(idx: int) -> date:
    return EXP_DAY_EPOCH + td(days=idx)


def date_to_exp_idx(d: date) -> int:
    noon = dt(d.year, d.month, d.day, 12, 0, tzinfo=EXP_TZ)
    return exp_day_index(noon)


def parse_ymd(text: str) -> date:
    try:
        return dt.strptime(text, '%Y-%m-%d').date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f'date must be YYYY-MM-DD: {text}') from e


def _voice_exp(voice_count: int) -> int:
    return int(voice_count / voiceCooltime / 10) * voicePoint


def _snap(st: UserState | None) -> tuple[int, int, int, int]:
    if st is None:
        return (0, 0, 0, 0)
    return (st.total_chat, st.chat_count, st.voice_count, st.day_count)


def exp_gain(
    before: tuple[int, int, int, int],
    after: tuple[int, int, int, int],
) -> int:
    return (
        (after[1] - before[1]) * chatPoint
        + (after[3] - before[3]) * dayPoint
        + (_voice_exp(after[2]) - _voice_exp(before[2]))
    )


def _credit(
    bucket: DayStats | None,
    uid: int,
    before: tuple[int, int, int, int],
    after: tuple[int, int, int, int],
) -> None:
    if bucket is None:
        return
    d_total = after[0] - before[0]
    d_chat = after[1] - before[1]
    d_voice = after[2] - before[2]
    d_day = after[3] - before[3]
    _merge_stats(bucket, uid, d_total, d_chat, d_voice, d_day > 0, exp_gain(before, after))


def _new_chat_user(ts: int, attend_idx: int) -> UserState:
    return UserState(
        first_call=ts,
        last_call=ts,
        last_attend=attend_idx,
        chat_count=1,
        day_count=1,
        total_chat=1,
        seen_register=False,
    )


def _new_voice_user(ts: int, attend_idx: int, cool: int, now: dt) -> UserState:
    return UserState(
        first_call=ts,
        last_call=_via_voice_last_ts(now, cool),
        last_attend=attend_idx,
        chat_count=0,
        day_count=1,
        seen_register=False,
    )


def _new_register_user(
    ts: int, attend_idx: int, via_voice: bool, cool: int, now: dt,
) -> UserState:
    return UserState(
        first_call=ts,
        last_call=_via_voice_last_ts(now, cool) if via_voice else ts,
        last_attend=attend_idx,
        chat_count=0 if via_voice else 1,
        day_count=1,
        seen_register=True,
    )


def _apply_chat(
    states: dict,
    key,
    uid: int,
    ts: int,
    now: dt,
    attend_idx: int,
    in_voice: bool,
    cool: int,
    bucket: DayStats | None,
) -> None:
    before = _snap(states.get(key))
    st = states.get(key)
    if st is None:
        states[key] = _new_chat_user(ts, attend_idx)
    else:
        if not in_voice and now - fromTimeStamp(st.last_call) >= td(seconds=cool):
            st.last_call = ts
            st.chat_count += 1
        st.total_chat += 1
        _mark_attend(st, now)
    after = _snap(states[key])
    _credit(bucket, uid, before, after)


def _apply_global_chat(
    states: dict[int, UserState], uid: int, chat: GlobalChat, cool: int,
    bucket: DayStats | None,
) -> None:
    before = _snap(states.get(uid))
    replay_global_chat(states, uid, chat, cool)
    after = _snap(states[uid])
    _credit(bucket, uid, before, after)


def _apply_register(
    states: dict,
    key,
    uid: int,
    ts: int,
    now: dt,
    attend_idx: int,
    via_voice: bool,
    cool: int,
    bucket: DayStats | None,
) -> None:
    before = _snap(states.get(key))
    st = states.get(key)
    if st is None:
        states[key] = _new_register_user(ts, attend_idx, via_voice, cool, now)
    else:
        st.seen_register = True
    after = _snap(states[key])
    _credit(bucket, uid, before, after)


def _apply_voice(
    states: dict,
    key,
    uid: int,
    ts: int,
    now: dt,
    attend_idx: int,
    amount: int,
    cool: int,
    bucket: DayStats | None,
) -> None:
    if amount <= 0:
        return
    before = _snap(states.get(key))
    st = states.get(key)
    if st is None:
        st = _new_voice_user(ts, attend_idx, cool, now)
        states[key] = st
    else:
        _mark_attend(st, now)
    st.voice_count += amount
    after = _snap(st)
    _credit(bucket, uid, before, after)


def _apply_manual_attend(
    states: dict,
    key,
    uid: int,
    now: dt,
    cool: int,
    bucket: DayStats | None,
) -> None:
    st = states.get(key)
    if st is None:
        return
    before = _snap(st)
    if _mark_attend(st, now):
        st.last_call = _via_voice_last_ts(now, cool)
    after = _snap(st)
    _credit(bucket, uid, before, after)


def _disp_width(text: str) -> int:
    n = 0
    for ch in text:
        n += 2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1
    return n


def _pad(text: str, width: int, *, align: str) -> str:
    pad = max(0, width - _disp_width(text))
    if align == 'left':
        return text + ' ' * pad
    return ' ' * pad + text


class _DailyReplay:
    def __init__(self, cool: int, *, window: range | None = None,
                 guild: int | None = None, uid: int | None = None,
                 include_guild: bool = True, include_global: bool = True):
        self.cool = cool
        self.window = window
        self.guild = guild
        self.uid = uid
        self.include_guild = include_guild
        self.global_log = GlobalChatLog() if include_global else None
        self.guild_states: dict[tuple[int, int], UserState] = {}
        self.global_states: dict[int, UserState] = {}
        self.buckets: dict[tuple[int, int | None, int], DayStats] = {}
        self.seq = 0
        self.min_ts: int | None = None
        self.max_ts: int | None = None

    def _bucket(self, day: int, scope: int | None, uid: int) -> DayStats | None:
        if self.window is not None and day not in self.window:
            return None
        key = (day, scope, uid)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = self.buckets[key] = DayStats()
        return bucket

    def read(self, event: Event) -> None:
        self.seq = event.seq
        ts, guild, uid, task = event.ts, event.guild, event.uid, event.task
        self.min_ts = ts if self.min_ts is None else min(self.min_ts, ts)
        self.max_ts = ts if self.max_ts is None else max(self.max_ts, ts)
        if task not in (13, 50, 60, 61, 70, 110, 111, 112, 113, 120, 170):
            return

        value = event.first_field_text()
        # Even when output is scoped, older logs need global activation and
        # pending chat context from the complete stream.
        log = self.global_log
        chat = log.read(ts, guild, uid, task, value) if log is not None else None
        if self.uid is not None and uid != self.uid:
            return
        if chat is not None:
            chat_day = exp_day_index(fromTimeStamp(chat.ts))
            _apply_global_chat(self.global_states, uid, chat, self.cool, self._bucket(chat_day, None, uid))

        now = fromTimeStamp(ts)
        day = exp_day_index(now)
        gkey = (guild, uid)
        guild_enabled = self.include_guild and (self.guild is None or self.guild == guild)
        if task == 60 and guild_enabled:
            _apply_chat(self.guild_states, gkey, uid, ts, now, day, _parse_bool(value),
                        self.cool, self._bucket(day, guild, uid))
        elif task == 70 and guild_enabled:
            _apply_register(self.guild_states, gkey, uid, ts, now, day, _parse_bool(value),
                            self.cool, self._bucket(day, guild, uid))
        elif task == 170 and log is not None:
            via_voice = _parse_bool(value)
            if via_voice or uid not in log.pending:
                _apply_register(self.global_states, uid, uid, ts, now, day, via_voice,
                                self.cool, self._bucket(day, None, uid))
        elif task == 50 and (guild_enabled or log is not None):
            amount = int(value) if event.fields else 0
            if guild_enabled:
                _apply_voice(self.guild_states, gkey, uid, ts, now, day, amount,
                             self.cool, self._bucket(day, guild, uid))
            if log is not None:
                _apply_voice(self.global_states, uid, uid, ts, now, day, amount,
                             self.cool, self._bucket(day, None, uid))
        elif task == 13 and guild_enabled:
            _apply_manual_attend(self.guild_states, gkey, uid, now, self.cool, self._bucket(day, guild, uid))
        elif task == 113 and log is not None:
            _apply_manual_attend(self.global_states, uid, uid, now, self.cool, self._bucket(day, None, uid))

    def restore(self, position: tuple, state_json: str) -> None:
        self.seq, self.min_ts, self.max_ts = position
        guilds, users, started, pending = json.loads(state_json)
        self.guild_states = {(guild, uid): UserState(**state) for guild, uid, state in guilds}
        self.global_states = {uid: UserState(**state) for uid, state in users}
        self.global_log.started = started
        self.global_log.pending = {uid: GlobalChat(**chat) for uid, chat in pending}

    def checkpoint(self) -> str:
        return json.dumps((
            [(guild, uid, asdict(state)) for (guild, uid), state in self.guild_states.items()],
            [(uid, asdict(state)) for uid, state in self.global_states.items()],
            self.global_log.started,
            [(uid, asdict(chat)) for uid, chat in self.global_log.pending.items()],
        ), separators=(',', ':'))

    def save_buckets(self, db: sqlite3.Connection, config: str) -> None:
        rows = (
            (config, day, '' if scope is None else str(scope), str(uid),
             stats.total_chat, stats.counted_chat, stats.voice_tenths,
             bool(stats.attend_uids), stats.exp_delta)
            for (day, scope, uid), stats in self.buckets.items()
            if stats.total_chat or stats.counted_chat or stats.voice_tenths
            or stats.attend_uids or stats.exp_delta
        )
        db.executemany(
            """INSERT INTO daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(config, scope, day, uid) DO UPDATE SET
               total_chat=total_chat+excluded.total_chat, counted_chat=counted_chat+excluded.counted_chat,
               voice=voice+excluded.voice, attended=max(attended, excluded.attended), exp=exp+excluded.exp""",
            rows,
        )
        self.buckets.clear()


@contextmanager
def _cached_daily(path: Path, cool: int):
    config = json.dumps([
        _REPLAY_VERSION, cool, chatPoint, dayPoint, voiceCooltime, voicePoint,
        EXP_DAY_EPOCH.isoformat(), EXP_DAY_ROLLOVER.isoformat(),
    ])
    with closing(sqlite3.connect(path / 'daily_stats.sqlite3', timeout=60)) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                config TEXT PRIMARY KEY, seq INTEGER, min_ts INTEGER, max_ts INTEGER, state TEXT
            );
            CREATE TABLE IF NOT EXISTS daily (
                config TEXT, day INTEGER, scope TEXT, uid TEXT,
                total_chat INTEGER, counted_chat INTEGER, voice INTEGER, attended INTEGER, exp INTEGER,
                PRIMARY KEY (config, scope, day, uid)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS daily_by_day ON daily (config, day);
        """)
        with db:
            db.execute('BEGIN IMMEDIATE')
            checkpoint = db.execute(
                'SELECT seq, min_ts, max_ts FROM checkpoints WHERE config=?', (config,),
            ).fetchone()
            after = checkpoint[0] if checkpoint is not None else 0
            with closing(iter_events(path, after=after)) as events:
                first = next(events, None)
                if first is not None or checkpoint is None:
                    replay = _DailyReplay(cool)
                    if checkpoint is not None:
                        state, = db.execute('SELECT state FROM checkpoints WHERE config=?', (config,)).fetchone()
                        replay.restore(checkpoint, state)
                    if first is not None:
                        replay.read(first)
                    for event in events:
                        replay.read(event)
                        if event.seq % 16384 == 0:
                            replay.save_buckets(db, config)
                    replay.save_buckets(db, config)
                    db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?, ?, ?, ?, ?)', (
                        config, replay.seq, replay.min_ts, replay.max_ts, replay.checkpoint(),
                    ))
                    min_ts, max_ts = replay.min_ts, replay.max_ts
                else:
                    min_ts, max_ts = checkpoint[1:3]
            yield db, config, min_ts, max_ts


def collect(
    log_path: Path,
    *,
    start_idx: int,
    end_idx: int,
    guild: int | None,
    cool: int,
    user_id: int | None = None,
) -> tuple[dict[int, DayStats], int | None, int | None]:
    window = range(start_idx, end_idx + 1)
    days = {day: DayStats() for day in window}
    if log_path.is_dir():
        with _cached_daily(log_path, cool) as (db, config, min_ts, max_ts):
            scope = '' if guild is None else str(guild)
            sql = """SELECT day, uid, total_chat, counted_chat, voice, attended, exp
                     FROM daily WHERE config=? AND scope=? AND day BETWEEN ? AND ?"""
            params = (config, scope, start_idx, end_idx)
            if user_id is not None:
                sql += ' AND uid=?'
                params += (str(user_id),)
            for day, uid, total, counted, voice, attended, exp in db.execute(sql, params):
                _merge_stats(days[day], int(uid), total, counted, voice, attended, exp)
        return days, min_ts, max_ts

    replay = _DailyReplay(cool, window=window, guild=guild, uid=user_id,
                          include_guild=guild is not None, include_global=guild is None)
    for event in iter_events(log_path):
        replay.read(event)
    for (day, _scope, uid), stats in replay.buckets.items():
        _merge_stats(days[day], uid, stats.total_chat, stats.counted_chat,
                     stats.voice_tenths, bool(stats.attend_uids), stats.exp_delta)
    return days, replay.min_ts, replay.max_ts


def _merge_stats(bucket: DayStats, uid: int, total: int, counted: int,
                 voice: int, attended: bool, exp: int) -> None:
    bucket.total_chat += total
    bucket.counted_chat += counted
    bucket.voice_tenths += voice
    if attended:
        bucket.attend_uids.add(uid)
    bucket.exp_delta += exp


def collect_day_user_exp(
    log_path: Path,
    *,
    day_idx: int,
    cool: int,
    guild: int | None = None,
) -> tuple[dict[tuple[int, int], int], dict[int, int]]:
    """Read one EXP day's guild and global user gains for the backfill."""
    guild_exp = {}
    global_exp = {}
    if log_path.is_dir():
        with _cached_daily(log_path, cool) as (db, config, _min_ts, _max_ts):
            sql = "SELECT scope, uid, exp FROM daily WHERE config=? AND day=? AND exp<>0"
            params = (config, day_idx)
            if guild is not None:
                sql += " AND (scope='' OR scope=?)"
                params += (str(guild),)
            for scope, uid, exp in db.execute(sql, params):
                if scope:
                    guild_exp[(int(scope), int(uid))] = exp
                else:
                    global_exp[int(uid)] = exp
        return guild_exp, global_exp

    replay = _DailyReplay(cool, window=range(day_idx, day_idx + 1), guild=guild)
    for event in iter_events(log_path):
        replay.read(event)
    for (_day, scope, uid), stats in replay.buckets.items():
        if stats.exp_delta:
            if scope is None:
                global_exp[uid] = stats.exp_delta
            else:
                guild_exp[(scope, uid)] = stats.exp_delta
    return guild_exp, global_exp


def _fmt_seconds(tenths: int) -> str:
    return f'{tenths / 10:.1f}'


def print_table(
    days: dict[int, DayStats],
    *,
    start_idx: int,
    end_idx: int,
    guild: int | None,
    cool: int,
    log_path: Path,
    min_ts: int | None,
    max_ts: int | None,
    user_id: int | None = None,
) -> None:
    scope = 'global' if guild is None else f'guild={guild}'
    if user_id is not None:
        scope += f'  uid={user_id}'
    start_d = exp_idx_to_date(start_idx)
    end_d = exp_idx_to_date(end_idx)
    print(
        f'scope={scope}  from={start_d.isoformat()}  to={end_d.isoformat()}  '
        f'(exp day, 05:15 KST)  cool={cool}s'
    )
    print(
        f'formula: chat={chatPoint}/msg, voice={voicePoint}/{voiceCooltime}s, '
        f'day={dayPoint}'
    )
    print(f'log={log_path}')
    if min_ts is not None and max_ts is not None:
        print(
            f'log span: {fromTimeStamp(min_ts).isoformat(timespec="seconds")} '
            f'~ {fromTimeStamp(max_ts).isoformat(timespec="seconds")}'
        )

    headers = ('날짜', '총 채팅', '집계 채팅', '통화(초)', '출석 인원', '증가 EXP')
    rows: list[tuple[str, str, str, str, str, str]] = []
    tot_chat = tot_counted = tot_voice = tot_attend = tot_exp = 0
    all_attend: set[int] = set()
    for idx in range(start_idx, end_idx + 1):
        st = days[idx]
        tot_chat += st.total_chat
        tot_counted += st.counted_chat
        tot_voice += st.voice_tenths
        tot_attend += len(st.attend_uids)
        tot_exp += st.exp_delta
        all_attend |= st.attend_uids
        rows.append((
            exp_idx_to_date(idx).isoformat(),
            str(st.total_chat),
            str(st.counted_chat),
            _fmt_seconds(st.voice_tenths),
            str(len(st.attend_uids)),
            str(st.exp_delta),
        ))
    rows.append((
        '합계',
        str(tot_chat),
        str(tot_counted),
        _fmt_seconds(tot_voice),
        str(tot_attend),
        str(tot_exp),
    ))

    widths = [_disp_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _disp_width(cell))

    def fmt_row(row: tuple[str, ...], *, header: bool = False) -> str:
        parts = []
        for i, cell in enumerate(row):
            align = 'left' if i == 0 or header else 'right'
            parts.append(_pad(cell, widths[i], align=align))
        return '  '.join(parts)

    print()
    print(fmt_row(headers, header=True))
    print('  '.join('-' * w for w in widths))
    for i, row in enumerate(rows):
        if i == len(rows) - 1:
            print('  '.join('-' * w for w in widths))
        print(fmt_row(row))
    print(f'기간 내 고유 출석 인원: {len(all_attend)}')

    if tot_chat == 0 and tot_voice == 0 and not all_attend:
        print()
        print('선택한 구간에 활동이 없습니다. --from/--to 또는 --days 를 바꿔 보세요.')


def resolve_window(args: argparse.Namespace) -> tuple[int, int]:
    today_idx = exp_day_index(getNow())
    if args.from_date is None and args.to_date is None:
        end_idx = today_idx
        start_idx = end_idx - args.days + 1
        return start_idx, end_idx
    if args.from_date is not None and args.to_date is not None:
        start_idx = date_to_exp_idx(args.from_date)
        end_idx = date_to_exp_idx(args.to_date)
    elif args.from_date is not None:
        start_idx = date_to_exp_idx(args.from_date)
        end_idx = today_idx
    else:
        end_idx = date_to_exp_idx(args.to_date)
        start_idx = end_idx - args.days + 1
    if start_idx > end_idx:
        raise SystemExit('--from 가 --to 보다 뒤입니다.')
    return start_idx, end_idx


def main() -> int:
    _ensure_utf8_stdio()
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        '--log',
        type=Path,
        default=None,
        help='EXP log directory or legacy CSV file',
    )
    p.add_argument(
        '--days',
        type=int,
        default=7,
        help='최근 N 경험치일 (기본 7). --from/--to 가 있으면 그쪽이 우선',
    )
    p.add_argument(
        '--from',
        dest='from_date',
        type=parse_ymd,
        default=None,
        metavar='YYYY-MM-DD',
        help='시작 경험치일 (해당 날짜 05:15 KST부터)',
    )
    p.add_argument(
        '--to',
        dest='to_date',
        type=parse_ymd,
        default=None,
        metavar='YYYY-MM-DD',
        help='끝 경험치일 (포함)',
    )
    p.add_argument(
        '--guild',
        type=int,
        default=None,
        help='특정 서버(guild id). 생략 시 global',
    )
    p.add_argument('--uid', type=int, help='특정 Discord 유저 ID. --guild와 함께 사용 가능')
    p.add_argument(
        '--cool',
        type=int,
        default=chatCooltime,
        help=f'전 기간 집계 채팅 재계산용 쿨타임 초 (기본 {chatCooltime})',
    )
    args = p.parse_args()
    if args.days < 1:
        print('--days 는 1 이상이어야 합니다.', file=sys.stderr)
        return 2

    log_path = resolve_log(args.log)
    if not log_path.exists():
        print(f'log not found: {log_path}', file=sys.stderr)
        return 1

    start_idx, end_idx = resolve_window(args)
    days, min_ts, max_ts = collect(
        log_path,
        start_idx=start_idx,
        end_idx=end_idx,
        guild=args.guild,
        cool=args.cool,
        user_id=args.uid,
    )
    print_table(
        days,
        start_idx=start_idx,
        end_idx=end_idx,
        guild=args.guild,
        cool=args.cool,
        log_path=log_path,
        min_ts=min_ts,
        max_ts=max_ts,
        user_id=args.uid,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
