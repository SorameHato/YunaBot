#!/usr/bin/env python3
"""Replay exp chat cooltime from the EXP log and optionally apply to DB.

Default is dry-run (print deltas only). Use --apply to:
  1) write chat_count/last_call from log replay (new cooltime)
  2) recalculate exp for EVERY guild/global row with current formula
     (chatPoint / voiceCooltime / dayPoint from DB.db_exp)

With --from-log-all, voice_count/day_count/total_chat/last_attend are also overwritten from the log
before the full exp sweep.

Use --global-uid to compare specific global users with the DB and repair only their
mismatched chat_count and exp. Repeat the option to select multiple users.

Examples:
  python tools/recalc_chat_cooltime.py --log path/to/log_test.csv --new-cool 45
  python tools/recalc_chat_cooltime.py --log path/to/log_test.csv --new-cool 45 --apply
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime as dt
from datetime import timedelta as td
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from DB.exp_log import iter_events, resolve_log  # noqa: E402
from DB.db_exp import (  # noqa: E402
    __calcFriendlyRate__,
    __calcGlobalFriendlyRate__,
    _connectDB,
    chatPoint,
    dayPoint,
    exp_day_index,
    fromTimeStamp,
    getTimeStamp,
    via_voice_last_call,
    voiceCooltime,
    voicePoint,
)

# Patchable cooltime for via_voice_last_call during replay (module uses chatCooltime).
import DB.db_exp as db_exp  # noqa: E402


@dataclass
class UserState:
    first_call: int = 0
    last_call: int = 0
    last_attend: int = 0
    chat_count: int = 0
    voice_count: int = 0
    day_count: int = 0
    total_chat: int = 0
    seen_register: bool = False


@dataclass
class ReplayResult:
    guild: dict[tuple[int, int], UserState] = field(default_factory=dict)
    global_: dict[int, UserState] = field(default_factory=dict)
    last_ts: int | None = None


def _parse_bool(s: str) -> bool:
    return s.strip().lower() in ('1', 'true', 'yes')


def global_chat_in_voice(value: str, guild_in_voice: bool) -> bool:
    """Read task 110's global voice flag, using task 60 for older logs."""
    if value.strip().lower() in ('true', 'false', '1', '0', 'yes', 'no'):
        return _parse_bool(value)
    return guild_in_voice


@dataclass
class GlobalChat:
    guild: int
    ts: int
    in_voice: bool
    global_active: bool
    registered: bool = False


class GlobalChatLog:
    def __init__(self) -> None:
        self.pending: dict[int, GlobalChat] = {}
        self.started = False

    def read(self, ts: int, guild: int, uid: int, task: int, value: str) -> GlobalChat | None:
        chat = self.pending.get(uid)
        if task == 60:
            self.pending[uid] = GlobalChat(guild, ts, _parse_bool(value), self.started)
        elif task in (110, 111, 112, 113, 120, 170):
            # Legacy files can begin before global activity was introduced.
            self.started = True
            if chat is None:
                return None
            chat.global_active = True
            if task == 110:
                chat.ts = ts
                chat.in_voice = global_chat_in_voice(value, chat.in_voice)
            elif task == 170 and value and not _parse_bool(value):
                chat.registered = True
        elif task == 61 and chat is not None and guild == chat.guild:
            self.pending.pop(uid)
            if chat.global_active:
                return chat
        return None


def replay_global_chat(states: dict[int, UserState], uid: int, chat: GlobalChat, cool: int) -> None:
    now = fromTimeStamp(chat.ts)
    st = states.get(uid)
    if st is None:
        states[uid] = UserState(
            first_call=chat.ts, last_call=chat.ts, last_attend=exp_day_index(now),
            chat_count=int(chat.registered or not chat.in_voice), day_count=1, total_chat=1,
            seen_register=chat.registered,
        )
        return
    if chat.registered or (not chat.in_voice and chat.ts - st.last_call >= cool * 1000):
        st.last_call = chat.ts
        st.chat_count += 1
    st.seen_register |= chat.registered
    st.total_chat += 1
    _mark_attend(st, now)


def _via_voice_last_ts(now: dt, cool: int) -> int:
    old = db_exp.chatCooltime
    db_exp.chatCooltime = cool
    try:
        return getTimeStamp(via_voice_last_call(now))
    finally:
        db_exp.chatCooltime = old


def _mark_attend(st: UserState, now: dt) -> bool:
    '''If new exp-day, bump day_count and set last_attend. Returns True if attended.'''
    today_idx = exp_day_index(now)
    if st.last_attend == today_idx:
        return False
    st.day_count += 1
    st.last_attend = today_idx
    return True


def replay_log(log_path: Path, cool: int) -> ReplayResult:
    """Replay guild + global chat/voice/attend from the EXP log with given cooltime."""
    out = ReplayResult()
    global_log = GlobalChatLog()

    for event in iter_events(log_path):
        ts, guild, uid, task = event.ts, event.guild, event.uid, event.task
        out.last_ts = ts if out.last_ts is None else max(ts, out.last_ts)
        now = fromTimeStamp(ts)
        attend_idx = exp_day_index(now)
        value = event.first_field_text()
        chat = global_log.read(ts, guild, uid, task, value)
        if chat is not None:
            replay_global_chat(out.global_, uid, chat, cool)

        if task == 70:
            # 60/50 already applied this turn; do not reset counters (total_chat/voice).
            via = _parse_bool(value)
            key = (guild, uid)
            st = out.guild.get(key)
            if st is None:
                out.guild[key] = UserState(
                    first_call=ts,
                    last_call=_via_voice_last_ts(now, cool) if via else ts,
                    last_attend=attend_idx,
                    chat_count=0 if via else 1,
                    day_count=1,
                    seen_register=True,
                )
            else:
                st.seen_register = True

        elif task == 170:
            via = _parse_bool(value)
            if not via and uid in global_log.pending:
                continue  # Applied with its chat upon task 61.
            st = out.global_.get(uid)
            if st is None:
                out.global_[uid] = UserState(
                    first_call=ts,
                    last_call=_via_voice_last_ts(now, cool) if via else ts,
                    last_attend=attend_idx,
                    chat_count=0 if via else 1,
                    day_count=1,
                    seen_register=True,
                )
            else:
                st.seen_register = True

        elif task == 60:
            in_voice = _parse_bool(value)
            key = (guild, uid)
            st = out.guild.get(key)
            if st is None:
                # Chat path register: chat_count default 1, last_call=now, no +1 this turn.
                out.guild[key] = UserState(
                    first_call=ts,
                    last_call=ts,
                    last_attend=attend_idx,
                    chat_count=1,
                    day_count=1,
                    total_chat=1,
                    seen_register=False,
                )
                continue
            last_call = fromTimeStamp(st.last_call)
            if (not in_voice) and (now - last_call >= td(seconds=cool)):
                st.last_call = ts
                st.chat_count += 1
            st.total_chat += 1
            _mark_attend(st, now)

        elif task == 50:
            amount = int(value) if event.fields else 0
            if amount <= 0:
                continue
            key = (guild, uid)
            st = out.guild.get(key)
            if st is None:
                last_ts = _via_voice_last_ts(now, cool)
                st = UserState(
                    first_call=ts,
                    last_call=last_ts,
                    last_attend=attend_idx,
                    chat_count=0,
                    day_count=1,
                    seen_register=False,
                )
                out.guild[key] = st
            else:
                _mark_attend(st, now)
            st.voice_count += amount

            gst = out.global_.get(uid)
            if gst is None:
                last_ts = _via_voice_last_ts(now, cool)
                gst = UserState(
                    first_call=ts,
                    last_call=last_ts,
                    last_attend=attend_idx,
                    chat_count=0,
                    day_count=1,
                    seen_register=False,
                )
                out.global_[uid] = gst
            else:
                _mark_attend(gst, now)
            gst.voice_count += amount

        elif task == 13:
            st = out.guild.get((guild, uid))
            if st is None:
                continue
            if _mark_attend(st, now):
                st.last_call = _via_voice_last_ts(now, cool)

        elif task == 113:
            st = out.global_.get(uid)
            if st is None:
                continue
            if _mark_attend(st, now):
                st.last_call = _via_voice_last_ts(now, cool)

    return out


def calc_exp(chat_count: int, voice_count: int, day_count: int) -> int:
    return (
        chat_count * chatPoint
        + int(voice_count / voiceCooltime / 10) * voicePoint
        + day_count * dayPoint
    )


def print_comparison(old: ReplayResult, new: ReplayResult) -> None:
    print('=== guild (exp) ===')
    keys = sorted(set(old.guild) | set(new.guild))
    changed = 0
    for key in keys:
        a = old.guild.get(key)
        b = new.guild.get(key)
        if a is None or b is None:
            print(f'  MISSING {key} old={a is not None} new={b is not None}')
            continue
        ae = calc_exp(a.chat_count, a.voice_count, a.day_count)
        be = calc_exp(b.chat_count, b.voice_count, b.day_count)
        if a.chat_count != b.chat_count or ae != be:
            changed += 1
            g, u = key
            print(
                f'  guild={g} uid={u} '
                f'chat {a.chat_count}->{b.chat_count} ({b.chat_count - a.chat_count:+d}) '
                f'day {a.day_count}/{b.day_count} voice {a.voice_count}/{b.voice_count} '
                f'exp {ae}->{be} ({be - ae:+d})'
            )
    print(
        f'changed {changed}/{len(keys)} | '
        f'total chat {sum(s.chat_count for s in old.guild.values())}'
        f'->{sum(s.chat_count for s in new.guild.values())} | '
        f'total exp {sum(calc_exp(s.chat_count, s.voice_count, s.day_count) for s in old.guild.values())}'
        f'->{sum(calc_exp(s.chat_count, s.voice_count, s.day_count) for s in new.guild.values())}'
    )

    print('=== global_exp ===')
    ukeys = sorted(set(old.global_) | set(new.global_))
    changed = 0
    for uid in ukeys:
        a = old.global_.get(uid)
        b = new.global_.get(uid)
        if a is None or b is None:
            print(f'  MISSING uid={uid}')
            continue
        ae = calc_exp(a.chat_count, a.voice_count, a.day_count)
        be = calc_exp(b.chat_count, b.voice_count, b.day_count)
        if a.chat_count != b.chat_count or ae != be:
            changed += 1
            print(
                f'  uid={uid} '
                f'chat {a.chat_count}->{b.chat_count} ({b.chat_count - a.chat_count:+d}) '
                f'exp {ae}->{be} ({be - ae:+d})'
            )
    print(
        f'changed {changed}/{len(ukeys)} | '
        f'total chat {sum(s.chat_count for s in old.global_.values())}'
        f'->{sum(s.chat_count for s in new.global_.values())}'
    )


def repair_global_chat_from_replay(result: ReplayResult, uids: set[int], *, apply: bool) -> int:
    """Preview or repair selected global chat counts. Return a CLI exit status."""
    missed = changed = 0
    with _connectDB() as db:
        table = f'{db.db_prefix}_global_exp'
        param = '?' if db.type == 'sqlite3' else '%s'
        for uid in sorted(uids):
            st = result.global_.get(uid)
            if st is None:
                print(f'  uid={uid} skipped: no global replay')
                missed += 1
                continue
            db.cur.execute(
                f'SELECT chat_count, exp, last_api_call, voice_count, day_count '
                f'FROM {table} WHERE uid={param}', (uid,),
            )
            row = db.cur.fetchone()
            if row is None:
                print(f'  uid={uid} skipped: no global DB row')
                missed += 1
                continue
            chat_count, exp, last_api_call, voice_count, day_count = row
            if chat_count == st.chat_count:
                print(f'  uid={uid} unchanged: chat_count={chat_count}')
                continue
            if result.last_ts is None or last_api_call > result.last_ts:
                print(f'  uid={uid} skipped: DB activity is newer than the log')
                missed += 1
                continue
            new_exp = calc_exp(st.chat_count, voice_count, day_count)
            if apply:
                db.cur.execute(
                    f'UPDATE {table} SET chat_count={param}, exp={param} '
                    f'WHERE uid={param} AND chat_count={param} AND exp={param} '
                    f'AND last_api_call={param} AND voice_count={param} AND day_count={param}',
                    (st.chat_count, new_exp, uid, *row),
                )
                if db.cur.rowcount != 1:
                    print(f'  uid={uid} skipped: DB row changed during comparison')
                    missed += 1
                    continue
            print(f'  uid={uid} chat_count {chat_count}->{st.chat_count}, exp {exp}->{new_exp}')
            changed += 1
    action = 'updated' if apply else 'would update'
    print(f'  {action}: {changed}, skipped: {missed}')
    return int(missed > 0)


def apply_chat_from_replay(result: ReplayResult, *, from_log_all: bool) -> tuple[int, int]:
    """Write replayed counters; returns (guild_updated, global_updated)."""
    guild_n = 0
    global_n = 0
    with _connectDB() as db:
        for (guild, uid), st in result.guild.items():
            try:
                db.get(guild, uid, 'uid')
            except IndexError:
                print(f'  skip missing guild row guild={guild} uid={uid}')
                continue
            db.set(guild, uid, 'chat_count', st.chat_count)
            db.set(guild, uid, 'last_call', st.last_call)
            if from_log_all:
                db.set(guild, uid, 'voice_count', st.voice_count)
                db.set(guild, uid, 'day_count', st.day_count)
                db.set(guild, uid, 'total_chat', st.total_chat)
                db.set(guild, uid, 'last_attend', st.last_attend)
            guild_n += 1

        for uid, st in result.global_.items():
            try:
                db.global_get(uid, 'uid')
            except IndexError:
                print(f'  skip missing global row uid={uid}')
                continue
            db.global_set(uid, 'chat_count', st.chat_count)
            db.global_set(uid, 'last_call', st.last_call)
            if from_log_all:
                db.global_set(uid, 'voice_count', st.voice_count)
                db.global_set(uid, 'day_count', st.day_count)
                db.global_set(uid, 'total_chat', st.total_chat)
                db.global_set(uid, 'last_attend', st.last_attend)
            global_n += 1
    return guild_n, global_n


def recalc_all_exp() -> tuple[int, int]:
    """Recompute exp for every guild/global row using current db_exp constants."""
    guild_n = 0
    global_n = 0
    with _connectDB() as db:
        table = f'{db.db_prefix}_exp'
        gtable = f'{db.db_prefix}_global_exp'
        db.cur.execute(f'SELECT guild, uid FROM {table};')
        guild_rows = [(int(g), int(u)) for g, u in db.cur.fetchall()]
        db.cur.execute(f'SELECT uid FROM {gtable};')
        global_uids = [int(u) for (u,) in db.cur.fetchall()]

        for guild, uid in guild_rows:
            before = db.get(guild, uid, 'exp')
            after = __calcFriendlyRate__(guild, uid, db=db)
            guild_n += 1
            if before != after:
                print(f'  guild={guild} uid={uid} exp {before}->{after} ({after - before:+d})')

        for uid in global_uids:
            before = db.global_get(uid, 'exp')
            after = __calcGlobalFriendlyRate__(uid, db=db)
            global_n += 1
            if before != after:
                print(f'  global uid={uid} exp {before}->{after} ({after - before:+d})')
    return guild_n, global_n


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        '--log',
        type=Path,
        help='EXP log directory or legacy CSV file',
    )
    p.add_argument('--old-cool', type=int, default=75, help='previous chatCooltime (seconds)')
    p.add_argument('--new-cool', type=int, default=45, help='new chatCooltime (seconds)')
    p.add_argument(
        '--global-uid', action='append', type=int, metavar='UID',
        help='preview or repair this global user only (repeatable)',
    )
    p.add_argument(
        '--apply',
        action='store_true',
        help='write the selected global corrections, or run the full replay and EXP sweep',
    )
    p.add_argument(
        '--from-log-all',
        action='store_true',
        help='with --apply, also overwrite voice_count/day_count/total_chat/last_attend from log replay',
    )
    p.add_argument(
        '--exp-only',
        action='store_true',
        help='with --apply, skip chat cooltime replay and only recalc exp for all rows',
    )
    args = p.parse_args()
    args.log = resolve_log(args.log)
    if args.global_uid and (args.exp_only or args.from_log_all):
        p.error('--global-uid cannot be combined with --exp-only or --from-log-all')

    print(
        f'formula: chat={chatPoint}/msg, voice={voicePoint}/{voiceCooltime}s, '
        f'day={dayPoint}'
    )

    if args.global_uid:
        if not args.log.exists():
            print(f'log not found: {args.log}', file=sys.stderr)
            return 1
        print(f'log={args.log}, replay cooltime={args.new_cool}s')
        result = replay_log(args.log, args.new_cool)
        return repair_global_chat_from_replay(result, set(args.global_uid), apply=args.apply)

    if not args.exp_only:
        if not args.log.exists():
            print(f'log not found: {args.log}', file=sys.stderr)
            return 1
        print(f'log={args.log}')
        print(f'replay old_cool={args.old_cool} vs new_cool={args.new_cool}')
        old = replay_log(args.log, args.old_cool)
        new = replay_log(args.log, args.new_cool)
        print_comparison(old, new)
    else:
        new = None
        print('exp-only mode (skip chat cooltime replay)')

    if args.apply:
        if not args.exp_only:
            assert new is not None
            print('applying new_cool chat replay to DB…')
            g_n, gl_n = apply_chat_from_replay(new, from_log_all=args.from_log_all)
            print(f'  chat rows updated: guild={g_n} global={gl_n}')
        print(
            f'recalculating exp for all DB rows '
            f'(voiceCooltime={voiceCooltime}, dayPoint={dayPoint})…'
        )
        g_n, gl_n = recalc_all_exp()
        print(f'  exp sweep: guild={g_n} global={gl_n}')
        print('done.')
    else:
        print('(dry-run only; pass --apply to write DB)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
