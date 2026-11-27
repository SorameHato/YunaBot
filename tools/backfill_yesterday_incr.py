#!/usr/bin/env python3
"""로그에서 지정한 경험치일의 EXP 증가분을 구해 yesterday_incr 에 채운다.

dailyDBInit 이 같은 날 두 번 돌아 yesterday_incr 가 0이 된 뒤 쓰는 임시 복구 도구.
yesterday_exp / exp 는 건드리지 않는다 (오늘 랭킹 공식 exp-yesterday_exp 유지).

기본: 직전 경험치일(어제 탭이 가리키는 날), dry-run.
  python tools/backfill_yesterday_incr.py
  python tools/backfill_yesterday_incr.py --day 2026-09-03
  python tools/backfill_yesterday_incr.py --apply
  python tools/backfill_yesterday_incr.py --guild 959065568135241728 --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

from DB.db_exp import (  # noqa: E402
    _connectDB,
    chatCooltime,
    chatPoint,
    dayPoint,
    exp_day_index,
    getNow,
    voiceCooltime,
    voicePoint,
)
from daily_stats_from_log import (  # noqa: E402
    _ensure_utf8_stdio,
    collect_day_user_exp,
    date_to_exp_idx,
    exp_idx_to_date,
    parse_ymd,
    resolve_log,
)

_SAMPLE = 12


def _read_incr(db, *, guild: int | None, uid: int) -> int | None:
    try:
        if guild is None:
            return int(db.global_get(uid, 'yesterday_incr') or 0)
        return int(db.get(guild, uid, 'yesterday_incr') or 0)
    except IndexError:
        return None


def _write_incr(db, *, guild: int | None, uid: int, amount: int) -> None:
    if guild is None:
        db.global_set(uid, 'yesterday_incr', amount)
    else:
        db.set(guild, uid, 'yesterday_incr', amount)


def _plan_rows(
    computed: dict,
    *,
    global_scope: bool,
    only_zero: bool,
    overwrite: bool,
) -> tuple[list[tuple], int, int]:
    '''Return (rows to write, missing_db, skipped_nonzero).'''
    out: list[tuple] = []
    missing = 0
    skipped_nonzero = 0
    with _connectDB() as db:
        for key, new in computed.items():
            if new < 0:
                continue
            if global_scope:
                guild, uid = None, key
                label = f'global uid={uid}'
            else:
                guild, uid = key
                label = f'guild={guild} uid={uid}'
            old = _read_incr(db, guild=guild, uid=uid)
            if old is None:
                missing += 1
                continue
            if old == new:
                continue
            if (only_zero or not overwrite) and old != 0:
                skipped_nonzero += 1
                continue
            out.append((label, guild, uid, old, new))
    out.sort(key=lambda row: (-row[4], row[1] or 0, row[2]))
    return out, missing, skipped_nonzero


def _print_plan(title: str, rows: list[tuple], missing: int, skipped_nonzero: int) -> None:
    print(f'=== {title} ===')
    extra = []
    if missing:
        extra.append(f'missing_db={missing}')
    if skipped_nonzero:
        extra.append(f'skipped_nonzero={skipped_nonzero}')
    if extra:
        print('  ' + '  '.join(extra))
    if not rows:
        print('  (변경할 행 없음)')
        return
    total_new = sum(r[4] for r in rows)
    from_zero = sum(1 for r in rows if r[3] == 0 and r[4] > 0)
    print(
        f'  rows={len(rows)}  from_zero={from_zero}  '
        f'yesterday_incr sum -> {total_new}'
    )
    print('  top samples (old -> new):')
    for label, _g, _u, old, new in rows[:_SAMPLE]:
        print(f'    {label}  {old} -> {new} ({new - old:+d})')
    if len(rows) > _SAMPLE:
        print(f'    … {len(rows) - _SAMPLE} more')


def _apply_rows(rows: list[tuple]) -> int:
    n = 0
    with _connectDB() as db:
        for _label, guild, uid, _old, new in rows:
            _write_incr(db, guild=guild, uid=uid, amount=new)
            n += 1
    return n


def main() -> int:
    _ensure_utf8_stdio()
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--log', type=Path, help='EXP log directory or legacy CSV file')
    p.add_argument(
        '--day',
        type=parse_ymd,
        default=None,
        metavar='YYYY-MM-DD',
        help='채울 경험치일 (기본: 어제 탭 = 직전 경험치일)',
    )
    p.add_argument('--guild', type=int, default=None, help='특정 서버만 (생략 시 전 서버+global)')
    p.add_argument(
        '--cool',
        type=int,
        default=chatCooltime,
        help=f'chatCooltime 초 (기본 {chatCooltime})',
    )
    p.add_argument(
        '--overwrite',
        action='store_true',
        help='yesterday_incr 가 0이 아닌 행도 로그 값으로 덮음',
    )
    p.add_argument('--apply', action='store_true', help='DB에 yesterday_incr 기록 (기본: dry-run)')
    args = p.parse_args()

    log_path = resolve_log(args.log)
    if not log_path.exists():
        print(f'log not found: {log_path}', file=sys.stderr)
        return 1

    today_idx = exp_day_index(getNow())
    day_idx = date_to_exp_idx(args.day) if args.day is not None else today_idx - 1
    day = exp_idx_to_date(day_idx)
    only_zero = not args.overwrite

    print(f'mode={"APPLY" if args.apply else "DRY-RUN"}')
    print(
        f'day={day.isoformat()} (exp day, 05:15 KST)  '
        f'today={exp_idx_to_date(today_idx).isoformat()}  cool={args.cool}s'
    )
    print(
        f'formula: chat={chatPoint}/msg, voice={voicePoint}/{voiceCooltime}s, '
        f'day={dayPoint}'
    )
    print(f'log={log_path}')
    print('writes: yesterday_incr only (yesterday_exp/exp 유지)')
    if only_zero:
        print('filter: yesterday_incr==0 인 행만')
    else:
        print('filter: 로그와 다른 행 전부 (--overwrite)')

    guild_exp, global_exp = collect_day_user_exp(
        log_path, day_idx=day_idx, cool=args.cool, guild=args.guild,
    )
    print(
        f'log users: guild={len(guild_exp)} (sum {sum(guild_exp.values())})  '
        f'global={len(global_exp)} (sum {sum(global_exp.values())})'
    )

    guild_rows, g_miss, g_skip = _plan_rows(
        guild_exp, global_scope=False, only_zero=only_zero, overwrite=args.overwrite,
    )
    global_rows: list[tuple] = []
    gl_miss = gl_skip = 0
    if args.guild is None:
        global_rows, gl_miss, gl_skip = _plan_rows(
            global_exp, global_scope=True, only_zero=only_zero, overwrite=args.overwrite,
        )
    _print_plan('guild exp', guild_rows, g_miss, g_skip)
    if args.guild is None:
        _print_plan('global_exp', global_rows, gl_miss, gl_skip)
    else:
        print(f'=== global_exp ===\n  (--guild {args.guild} 이라 건너뜀)')

    if not args.apply:
        print('no writes (dry-run). 맞으면 --apply 로 기록하세요.')
        return 0

    g_n = _apply_rows(guild_rows)
    gl_n = _apply_rows(global_rows)
    print(f'applied: guild={g_n} global={gl_n}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
