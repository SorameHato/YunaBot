#!/usr/bin/env python3
"""Compare EXP log replay against current DB exp rows.

Default: only users that exist in DB, and only fields that still differ
(chat/voice/day/total_chat/exp). Historical grant events are omitted.

Does not write DB.

Examples:
  python tools/verify_exp_from_log.py
  python tools/verify_exp_from_log.py --log path/to/log_test.csv --cool 45
  python tools/verify_exp_from_log.py --events
  python tools/verify_exp_from_log.py --csv findings.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime as dt
from datetime import timedelta as td
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

from DB.exp_log import iter_events, resolve_log  # noqa: E402
from DB.db_exp import (  # noqa: E402
    _connectDB,
    _rest_days_since_attend,
    chatCooltime,
    chatPoint,
    dayPoint,
    exp_day_index,
    fromTimeStamp,
    voiceCooltime,
    voicePoint,
)
from recalc_chat_cooltime import (  # noqa: E402
    ReplayResult,
    UserState,
    _via_voice_last_ts,
    calc_exp,
    global_chat_in_voice,
    replay_log,
)

_SAMPLE = 40


@dataclass
class AuditUser:
    last_call: int | None = None
    last_attend: int | None = None
    last_exp: int | None = None
    known: bool = False


@dataclass
class PendingChat:
    ts: int
    guild: int
    uid: int
    in_voice: bool
    global_in_voice: bool
    now: dt
    today_idx: int
    saw_register: bool = False
    saw_global_register: bool = False
    saw_attend: bool = False
    saw_global_attend: bool = False
    guild_exp: int | None = None
    global_exp: int | None = None
    expected_guild: int | None = None
    expected_global: int | None = None
    first_guild: bool = False
    first_global: bool = False


@dataclass
class Finding:
    kind: str
    scope: str
    guild: int
    uid: int
    ts: int
    detail: str


@dataclass
class AuditStats:
    chats: int = 0
    voices: int = 0
    skipped_unknown: int = 0
    findings: list[Finding] = field(default_factory=list)


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding='utf-8')
        except Exception:
            pass


def _parse_bool(s: str) -> bool:
    return s.strip().lower() in ('1', 'true', 'yes')


def _chat_arg(
    last_call: int,
    last_attend: int,
    now: dt,
    cool: int,
    in_voice: bool,
) -> int:
    today_idx = exp_day_index(now)
    last_dt = fromTimeStamp(last_call)
    recalc = (not in_voice) and (now - last_dt >= td(seconds=cool))
    if last_attend != today_idx:
        return _rest_days_since_attend(last_attend, today_idx, last_dt)
    if not recalc:
        return -1
    return 0


def _add(
    stats: AuditStats,
    kind: str,
    scope: str,
    guild: int,
    uid: int,
    ts: int,
    detail: str,
) -> None:
    stats.findings.append(Finding(kind, scope, guild, uid, ts, detail))


def collapse_attend_dup(findings: list[Finding]) -> list[Finding]:
    '''Merge same-user same-day extra attendance into one finding.'''
    dups: list[Finding] = []
    others: list[Finding] = []
    for f in findings:
        if f.kind == 'ATTEND_DUP':
            dups.append(f)
        else:
            others.append(f)
    groups: dict[tuple, list[Finding]] = {}
    for f in dups:
        day = exp_day_index(fromTimeStamp(f.ts)) if f.ts else 0
        groups.setdefault((f.scope, f.guild, f.uid, day), []).append(f)
    collapsed: list[Finding] = []
    for (scope, guild, uid, day), items in groups.items():
        src = items[0].detail
        if len(items) == 1:
            collapsed.append(items[0])
            continue
        collapsed.append(Finding(
            'ATTEND_DUP',
            scope,
            guild,
            uid,
            items[0].ts,
            f'{src} — {len(items)} extra attends on exp-day {day} '
            f'(ts {items[0].ts}..{items[-1].ts})',
        ))
    return others + collapsed


def _apply_chat_outcome(
    au: AuditUser,
    *,
    ts: int,
    now: dt,
    today_idx: int,
    in_voice: bool,
    logged: int,
    cool: int,
) -> None:
    if logged == -1:
        if au.last_attend is None:
            au.last_attend = today_idx
        return
    if logged == 0:
        au.last_call = ts
        au.last_attend = today_idx
        au.known = True
        return
    au.last_attend = today_idx
    if not in_voice and au.last_call is not None:
        last_dt = fromTimeStamp(au.last_call)
        if now - last_dt >= td(seconds=cool):
            au.last_call = ts
            au.known = True


def _finish_chat(
    pending: PendingChat,
    logged: int,
    guild_au: AuditUser,
    global_au: AuditUser,
    cool: int,
    stats: AuditStats,
    old_cool: int | None = None,
) -> None:
    stats.chats += 1
    in_voice = pending.in_voice
    g_in_voice = pending.global_in_voice

    if in_voice and logged == 0:
        _add(
            stats, 'CHAT_IN_VOICE', 'guild', pending.guild, pending.uid, pending.ts,
            'task61=0 while in_voice (chat_count must not increase)',
        )
    if g_in_voice and pending.global_exp is not None and pending.expected_global == -1:
        prev = global_au.last_exp
        if prev is not None and pending.global_exp > prev:
            _add(
                stats, 'CHAT_IN_VOICE', 'global', 0, pending.uid, pending.ts,
                f'global exp {prev}->{pending.global_exp} while in_voice',
            )

    if pending.saw_register:
        if logged != 0:
            _add(
                stats, 'CHAT_REGISTER_ARG', 'guild', pending.guild, pending.uid, pending.ts,
                f'register path should return 0, task61={logged}',
            )
    elif pending.expected_guild is None:
        stats.skipped_unknown += 1
    elif pending.expected_guild != logged:
        kind = 'CHAT_ARG_MISMATCH'
        if pending.expected_guild == -1 and logged == 0:
            kind = 'CHAT_COOLTIME'
        elif pending.expected_guild == 0 and logged == -1:
            kind = 'CHAT_MISSED'
        elif pending.expected_guild >= 1 and logged == -1:
            kind = 'ATTEND_MISSED'
        elif logged >= 1 and pending.expected_guild == -1:
            kind = 'ATTEND_DUP'
        if (
            kind == 'CHAT_MISSED'
            and old_cool is not None
            and old_cool != cool
            and guild_au.last_call is not None
            and guild_au.last_attend is not None
        ):
            old_arg = _chat_arg(
                guild_au.last_call, guild_au.last_attend, pending.now, old_cool, in_voice,
            )
            if old_arg == -1:
                kind = 'CHAT_OLD_COOL'
        _add(
            stats, kind, 'guild', pending.guild, pending.uid, pending.ts,
            f'expected {pending.expected_guild}, task61={logged}, in_voice={in_voice}',
        )

    if logged != -1 and pending.guild_exp is None and not pending.saw_register:
        _add(
            stats, 'RECALC_MISSING', 'guild', pending.guild, pending.uid, pending.ts,
            f'task61={logged} but no task 20',
        )
    if logged == -1 and pending.guild_exp is not None:
        _add(
            stats, 'RECALC_UNEXPECTED', 'guild', pending.guild, pending.uid, pending.ts,
            f'task61=-1 but task20={pending.guild_exp}',
        )

    if pending.guild_exp is not None and guild_au.last_exp is not None:
        if pending.saw_register:
            _add(
                stats, 'RE_REGISTER', 'guild', pending.guild, pending.uid, pending.ts,
                f'row re-created; prior exp {guild_au.last_exp} -> {pending.guild_exp}',
            )
        elif pending.guild_exp < guild_au.last_exp:
            _add(
                stats, 'EXP_DECREASE', 'guild', pending.guild, pending.uid, pending.ts,
                f'exp {guild_au.last_exp}->{pending.guild_exp}',
            )
    if pending.global_exp is not None and global_au.last_exp is not None:
        if pending.saw_global_register and pending.global_exp < global_au.last_exp:
            _add(
                stats, 'RE_REGISTER', 'global', 0, pending.uid, pending.ts,
                f'global row re-created; prior exp {global_au.last_exp} -> {pending.global_exp}',
            )
        elif pending.global_exp < global_au.last_exp and not pending.saw_global_register:
            _add(
                stats, 'EXP_DECREASE', 'global', 0, pending.uid, pending.ts,
                f'exp {global_au.last_exp}->{pending.global_exp}',
            )

    if pending.saw_register:
        guild_au.last_call = pending.ts
        guild_au.last_attend = pending.today_idx
        guild_au.known = True
    else:
        _apply_chat_outcome(
            guild_au, ts=pending.ts, now=pending.now, today_idx=pending.today_idx,
            in_voice=in_voice, logged=logged, cool=cool,
        )
    if pending.guild_exp is not None:
        guild_au.last_exp = pending.guild_exp

    g_logged = 0 if pending.global_exp is not None else -1
    if pending.expected_global is not None and pending.expected_global >= 1:
        g_logged = pending.expected_global if pending.global_exp is not None else -1
    elif pending.saw_global_attend:
        g_logged = 1
    if pending.saw_global_register:
        global_au.last_call = pending.ts
        global_au.last_attend = pending.today_idx
        global_au.known = True
    else:
        _apply_chat_outcome(
            global_au, ts=pending.ts, now=pending.now, today_idx=pending.today_idx,
            in_voice=g_in_voice, logged=g_logged, cool=cool,
        )
    if pending.global_exp is not None:
        global_au.last_exp = pending.global_exp


def audit_events(log_path: Path, cool: int, old_cool: int | None = None) -> AuditStats:
    stats = AuditStats()
    guild_users: dict[tuple[int, int], AuditUser] = {}
    global_users: dict[int, AuditUser] = {}
    pending: dict[tuple[int, int], PendingChat] = {}

    for event in iter_events(log_path):
        ts, guild, uid, task = event.ts, event.guild, event.uid, event.task
        value = event.first_field_text()
        now = fromTimeStamp(ts)
        today_idx = exp_day_index(now)

        if task == 60:
            key = (guild, uid)
            old = pending.pop(key, None)
            if old is not None:
                _add(
                    stats, 'CHAT_MISSING_61', 'guild', old.guild, old.uid, old.ts,
                    'task 60 without following task 61',
                )
            g_au = guild_users.get(key)
            gl_au = global_users.get(uid)
            in_voice = _parse_bool(value)
            first_guild = g_au is None
            first_global = gl_au is None
            if g_au is None:
                g_au = AuditUser()
                guild_users[key] = g_au
            if gl_au is None:
                gl_au = AuditUser()
                global_users[uid] = gl_au
            expected_guild = None
            if g_au.last_call is not None and g_au.last_attend is not None:
                expected_guild = _chat_arg(
                    g_au.last_call, g_au.last_attend, now, cool, in_voice,
                )
            expected_global = None
            if gl_au.last_call is not None and gl_au.last_attend is not None:
                expected_global = _chat_arg(
                    gl_au.last_call, gl_au.last_attend, now, cool, in_voice,
                )
            pending[key] = PendingChat(
                ts=ts, guild=guild, uid=uid, in_voice=in_voice, global_in_voice=in_voice, now=now,
                today_idx=today_idx, expected_guild=expected_guild,
                expected_global=expected_global, first_guild=first_guild,
                first_global=first_global,
            )

        elif task == 110:
            pc = next((chat for chat in pending.values() if chat.uid == uid), None)
            if pc is None or not event.fields:
                continue
            pc.global_in_voice = global_chat_in_voice(value, pc.in_voice)
            au = global_users[uid]
            if au.last_call is not None and au.last_attend is not None:
                pc.expected_global = _chat_arg(
                    au.last_call, au.last_attend, pc.now, cool, pc.global_in_voice,
                )

        elif task == 70:
            key = (guild, uid)
            via = _parse_bool(value)
            last_ts = _via_voice_last_ts(now, cool) if via else ts
            pc = pending.get(key)
            if pc is not None:
                pc.saw_register = True
                pc.expected_guild = 0
            au = guild_users.get(key)
            if au is None:
                guild_users[key] = AuditUser(
                    last_call=last_ts, last_attend=today_idx, known=True,
                )
            elif au.last_call is None:
                au.last_call = last_ts
                au.last_attend = today_idx
                au.known = True

        elif task == 170:
            via = _parse_bool(value)
            last_ts = _via_voice_last_ts(now, cool) if via else ts
            for pc in pending.values():
                if pc.uid == uid:
                    pc.saw_global_register = True
                    pc.expected_global = 0
                    break
            gl_au = global_users.get(uid)
            if gl_au is None:
                global_users[uid] = AuditUser(
                    last_call=last_ts, last_attend=today_idx, known=True,
                )
            elif gl_au.last_call is None:
                gl_au.last_call = last_ts
                gl_au.last_attend = today_idx
                gl_au.known = True

        elif task == 11:
            key = (guild, uid)
            pc = pending.get(key)
            if pc is not None:
                pc.saw_attend = True
            au = guild_users.get(key)
            if au is not None and au.last_attend == today_idx:
                _add(
                    stats, 'ATTEND_DUP', 'guild', guild, uid, ts,
                    'task 11 on an exp-day already attended',
                )

        elif task == 111:
            au = global_users.get(uid)
            for pc in pending.values():
                if pc.uid == uid:
                    pc.saw_global_attend = True
                    break
            if au is not None and au.last_attend == today_idx:
                _add(
                    stats, 'ATTEND_DUP', 'global', 0, uid, ts,
                    'task 111 on an exp-day already attended',
                )

        elif task == 20:
            key = (guild, uid)
            pc = pending.get(key)
            exp_val = int(value) if event.fields else 0
            if pc is not None:
                pc.guild_exp = exp_val
            else:
                au = guild_users.get(key)
                if au is not None and au.last_exp is not None and exp_val < au.last_exp:
                    _add(
                        stats, 'EXP_DECREASE', 'guild', guild, uid, ts,
                        f'exp {au.last_exp}->{exp_val}',
                    )
                if au is None:
                    au = AuditUser()
                    guild_users[key] = au
                au.last_exp = exp_val

        elif task == 120:
            exp_val = int(value) if event.fields else 0
            matched = False
            for pc in pending.values():
                if pc.uid == uid:
                    pc.global_exp = exp_val
                    matched = True
                    break
            au = global_users.get(uid)
            if au is None:
                au = AuditUser()
                global_users[uid] = au
            if not matched and au.last_exp is not None and exp_val < au.last_exp:
                _add(
                    stats, 'EXP_DECREASE', 'global', 0, uid, ts,
                    f'exp {au.last_exp}->{exp_val}',
                )
            au.last_exp = exp_val

        elif task == 61:
            key = (guild, uid)
            pc = pending.pop(key, None)
            logged = int(value) if event.fields else 0
            if pc is None:
                _add(
                    stats, 'CHAT_ORPHAN_61', 'guild', guild, uid, ts,
                    f'task 61={logged} without task 60',
                )
                continue
            g_au = guild_users.setdefault(key, AuditUser())
            gl_au = global_users.setdefault(uid, AuditUser())
            _finish_chat(
                pc, logged, g_au, gl_au, cool, stats, old_cool,
            )

        elif task == 50:
            stats.voices += 1
            amount = int(value) if event.fields else 0
            if amount <= 0:
                continue
            key = (guild, uid)
            if key not in guild_users:
                guild_users[key] = AuditUser()
            if uid not in global_users:
                global_users[uid] = AuditUser()

        elif task == 12:
            au = guild_users.get((guild, uid))
            if au is not None and au.last_attend == today_idx:
                _add(
                    stats, 'ATTEND_DUP', 'guild', guild, uid, ts,
                    'task 12 on an exp-day already attended',
                )
            elif au is not None:
                au.last_attend = today_idx

        elif task == 112:
            au = global_users.get(uid)
            if au is not None and au.last_attend == today_idx:
                _add(
                    stats, 'ATTEND_DUP', 'global', 0, uid, ts,
                    'task 112 on an exp-day already attended',
                )
            elif au is not None:
                au.last_attend = today_idx

        elif task == 13:
            au = guild_users.get((guild, uid))
            if au is None:
                guild_users[(guild, uid)] = AuditUser(
                    last_call=ts, last_attend=today_idx, known=True,
                )
            elif au.last_attend == today_idx:
                _add(
                    stats, 'ATTEND_DUP', 'guild', guild, uid, ts,
                    'manual attend task 13 on an exp-day already attended',
                )
            else:
                au.last_attend = today_idx

        elif task == 113:
            au = global_users.get(uid)
            if au is None:
                global_users[uid] = AuditUser(
                    last_call=ts, last_attend=today_idx, known=True,
                )
            elif au.last_attend == today_idx:
                _add(
                    stats, 'ATTEND_DUP', 'global', 0, uid, ts,
                    'manual attend task 113 on an exp-day already attended',
                )
            else:
                au.last_attend = today_idx

    for pc in pending.values():
        _add(
            stats, 'CHAT_MISSING_61', 'guild', pc.guild, pc.uid, pc.ts,
            'task 60 without following task 61 (EOF)',
        )
    return stats


@dataclass
class DbRow:
    chat_count: int
    voice_count: int
    day_count: int
    total_chat: int
    last_call: int
    last_attend: int
    exp: int


def load_db() -> tuple[dict[tuple[int, int], DbRow], dict[int, DbRow]]:
    guild: dict[tuple[int, int], DbRow] = {}
    global_: dict[int, DbRow] = {}
    with _connectDB() as db:
        table = f'{db.db_prefix}_exp'
        gtable = f'{db.db_prefix}_global_exp'
        db.cur.execute(
            f'SELECT guild, uid, chat_count, voice_count, day_count, total_chat, '
            f'last_call, last_attend, exp FROM {table};'
        )
        for row in db.cur.fetchall():
            guild[(int(row[0]), int(row[1]))] = DbRow(
                chat_count=int(row[2] or 0),
                voice_count=int(row[3] or 0),
                day_count=int(row[4] or 0),
                total_chat=int(row[5] or 0),
                last_call=int(row[6] or 0),
                last_attend=int(row[7] or 0),
                exp=int(row[8] or 0),
            )
        db.cur.execute(
            f'SELECT uid, chat_count, voice_count, day_count, total_chat, '
            f'last_call, last_attend, exp FROM {gtable};'
        )
        for row in db.cur.fetchall():
            global_[int(row[0])] = DbRow(
                chat_count=int(row[1] or 0),
                voice_count=int(row[2] or 0),
                day_count=int(row[3] or 0),
                total_chat=int(row[4] or 0),
                last_call=int(row[5] or 0),
                last_attend=int(row[6] or 0),
                exp=int(row[7] or 0),
            )
    return guild, global_


def _state_to_tuple(st: UserState) -> tuple[int, int, int, int, int]:
    return (
        st.chat_count,
        st.voice_count,
        st.day_count,
        st.total_chat,
        calc_exp(st.chat_count, st.voice_count, st.day_count),
    )


@dataclass
class ReplayDiff:
    mismatch: list[Finding]
    log_only: list[Finding]
    db_only: list[Finding]


def _counter_diffs(row: DbRow, st: UserState) -> list[str]:
    ce, ve, de, te, ee = _state_to_tuple(st)
    diffs: list[str] = []
    if ce != row.chat_count:
        diffs.append(f'chat db={row.chat_count} log={ce}')
    if ve != row.voice_count:
        diffs.append(f'voice db={row.voice_count} log={ve}')
    if de != row.day_count:
        diffs.append(f'day db={row.day_count} log={de}')
    if te != row.total_chat:
        diffs.append(f'total_chat db={row.total_chat} log={te}')
    if ee != row.exp:
        diffs.append(f'exp db={row.exp} log={ee}')
    formula_db = calc_exp(row.chat_count, row.voice_count, row.day_count)
    if row.exp != formula_db:
        diffs.append(f'db_formula={formula_db}')
    return diffs


def compare_replay_db(
    replayed: ReplayResult,
    db_guild: dict[tuple[int, int], DbRow],
    db_global: dict[int, DbRow],
) -> ReplayDiff:
    out = ReplayDiff([], [], [])

    keys = sorted(set(replayed.guild) | set(db_guild))
    for key in keys:
        st = replayed.guild.get(key)
        row = db_guild.get(key)
        g, u = key
        if st is None:
            out.db_only.append(Finding(
                'DB_ONLY', 'guild', g, u, 0,
                f'DB chat={row.chat_count} voice={row.voice_count} '
                f'day={row.day_count} exp={row.exp} (not in log replay)',
            ))
            continue
        if row is None:
            ce, ve, de, te, ee = _state_to_tuple(st)
            tag = 'complete' if st.seen_register else 'partial-log'
            out.log_only.append(Finding(
                'LOG_ONLY', 'guild', g, u, 0,
                f'{tag} replay chat={ce} voice={ve} day={de} total={te} exp={ee} (no DB row)',
            ))
            continue
        diffs = _counter_diffs(row, st)
        if diffs:
            out.mismatch.append(Finding(
                'DB_NE_LOG', 'guild', g, u, 0, ', '.join(diffs),
            ))

    ukeys = sorted(set(replayed.global_) | set(db_global))
    for uid in ukeys:
        st = replayed.global_.get(uid)
        row = db_global.get(uid)
        if st is None:
            out.db_only.append(Finding(
                'DB_ONLY', 'global', 0, uid, 0,
                f'DB chat={row.chat_count} voice={row.voice_count} '
                f'day={row.day_count} exp={row.exp} (not in log replay)',
            ))
            continue
        if row is None:
            ce, ve, de, te, ee = _state_to_tuple(st)
            tag = 'complete' if st.seen_register else 'partial-log'
            out.log_only.append(Finding(
                'LOG_ONLY', 'global', 0, uid, 0,
                f'{tag} replay chat={ce} voice={ve} day={de} total={te} exp={ee} (no DB row)',
            ))
            continue
        diffs = _counter_diffs(row, st)
        if diffs:
            out.mismatch.append(Finding(
                'DB_NE_LOG', 'global', 0, uid, 0, ', '.join(diffs),
            ))
    return out


def _kind_counts(items: list[Finding]) -> str:
    counts: dict[str, int] = {}
    for f in items:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    if not counts:
        return ''
    parts = ', '.join(f'{k}={n}' for k, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])))
    return f' [{parts}]'


def _print_group(title: str, items: list[Finding], limit: int) -> None:
    print(f'=== {title} ({len(items)}){_kind_counts(items)} ===')
    if not items:
        print('  (none)')
        return
    for f in items[:limit]:
        loc = f'guild={f.guild} uid={f.uid}' if f.scope == 'guild' else f'uid={f.uid}'
        ts = f' ts={f.ts}' if f.ts else ''
        print(f'  {f.kind} {loc}{ts} {f.detail}')
    if len(items) > limit:
        print(f'  … {len(items) - limit} more (use --limit)')


def _write_csv(path: Path, groups: list[tuple[str, list[Finding]]]) -> None:
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['section', 'kind', 'scope', 'guild', 'uid', 'ts', 'detail'])
        for section, items in groups:
            for it in items:
                w.writerow([section, it.kind, it.scope, it.guild, it.uid, it.ts, it.detail])


def main() -> int:
    _ensure_utf8_stdio()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        '--log',
        type=Path,
        help='EXP log directory or legacy CSV file',
    )
    p.add_argument(
        '--cool',
        type=int,
        default=chatCooltime,
        help=f'chatCooltime seconds (default: current {chatCooltime})',
    )
    p.add_argument(
        '--old-cool',
        type=int,
        default=75,
        help='previous chatCooltime; used only with --events',
    )
    p.add_argument(
        '--events',
        action='store_true',
        help='also print historical grant-rule findings from the log (not DB)',
    )
    p.add_argument(
        '--coverage',
        action='store_true',
        help='also print log-only / DB-only rows',
    )
    p.add_argument('--skip-db', action='store_true', help='with --events, skip DB comparison')
    p.add_argument('--limit', type=int, default=_SAMPLE, help='max findings printed per section')
    p.add_argument('--csv', type=Path, default=None, help='write all findings to CSV')
    args = p.parse_args()
    args.log = resolve_log(args.log)

    if args.skip_db and not args.events:
        print('--skip-db requires --events', file=sys.stderr)
        return 2

    print(
        f'formula: chat={chatPoint}/msg, voice={voicePoint}/{voiceCooltime}s, '
        f'day={dayPoint}, cool={args.cool}s'
    )
    if not args.log.exists():
        print(f'log not found: {args.log}', file=sys.stderr)
        return 1
    print(f'log={args.log}')

    grant: list[Finding] = []
    info: list[Finding] = []
    if args.events:
        events = audit_events(args.log, args.cool, args.old_cool)
        events.findings = collapse_attend_dup(events.findings)
        info_kinds = {'CHAT_MISSING_61', 'CHAT_OLD_COOL', 'RE_REGISTER'}
        grant = [f for f in events.findings if f.kind not in info_kinds]
        info = [f for f in events.findings if f.kind in info_kinds]
        print(
            f'events: chats={events.chats} voices={events.voices} '
            f'unknown-cool-skips={events.skipped_unknown}'
        )
        _print_group('grant rules (historical log, not current DB)', grant, args.limit)
        if info:
            _print_group(
                'informational (old cooltime / re-register / incomplete window)',
                info,
                args.limit,
            )

    replay_mismatch: list[Finding] = []
    replay_coverage: list[Finding] = []
    if not args.skip_db:
        print('replaying log vs current DB…')
        replayed = replay_log(args.log, args.cool)
        try:
            db_guild, db_global = load_db()
        except Exception as e:
            print(f'DB load failed: {e}', file=sys.stderr)
            return 1
        diff = compare_replay_db(replayed, db_guild, db_global)
        replay_mismatch = diff.mismatch
        replay_coverage = diff.log_only + diff.db_only
        compared = (
            len(set(replayed.guild) & set(db_guild)),
            len(set(replayed.global_) & set(db_global)),
        )
        print(
            f'compared DB∩log: guild={compared[0]}/{len(db_guild)} '
            f'global={compared[1]}/{len(db_global)}'
        )
        _print_group('current DB != log replay', replay_mismatch, args.limit)
        if args.coverage:
            _print_group('coverage (log-only / DB-only)', replay_coverage, args.limit)
    else:
        print('(skipped DB comparison)')

    if args.csv is not None:
        groups = [('db_ne_log', replay_mismatch)]
        if args.coverage:
            groups.append(('coverage', replay_coverage))
        if args.events:
            groups.extend([('grant', grant), ('info', info)])
        _write_csv(args.csv, groups)
        print(f'wrote {args.csv}')

    print(f'done. db mismatches={len(replay_mismatch)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
