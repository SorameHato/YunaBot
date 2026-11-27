#!/usr/bin/env python3
# coding: utf-8
"""봇이 꺼진 채 05:15 KST를 넘겼을 때, daily_init_exp와 같은 DB 일일 초기화를 수동 실행합니다.

기본은 dry-run입니다. 미리보기만 보고, 맞으면 --apply 로 반영하세요.
Discord 프로필 갱신·백업 통계 DM·물갈이는 봇이 필요하므로 이 스크립트에서는 건너뜁니다.

사용 예:
  cd /path/to/KumaBot
  python tools/manual_daily_init.py
  python tools/manual_daily_init.py --apply
  python tools/manual_daily_init.py --apply --force
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime as dt
from datetime import timedelta as td
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from DB.db_exp import (  # noqa: E402
    EXP_DAY_ROLLOVER,
    EXP_TZ,
    _connectDB,
    archive_exp_logs,
    dailyDBInit,
    exp_day_index,
    fromTimeStamp,
    getNow,
    logDailyInitExp,
)
from DB.exp_log import latest_init, resolve_log  # noqa: E402

_SAMPLE_LIMIT = 8


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding='utf-8')
        except Exception:
            pass


def _last_rollover(now: dt) -> dt:
    d = now.astimezone(EXP_TZ) if now.tzinfo else now.replace(tzinfo=EXP_TZ)
    base = dt(
        d.year,
        d.month,
        d.day,
        EXP_DAY_ROLLOVER.hour,
        EXP_DAY_ROLLOVER.minute,
        0,
        tzinfo=EXP_TZ,
    )
    if d.time() < EXP_DAY_ROLLOVER:
        return base - td(days=1)
    return base


def _next_rollover(now: dt) -> dt:
    return _last_rollover(now) + td(days=1)


def _last_daily_init_from_log(path: Path) -> tuple[dt, int] | None:
    if not path.exists():
        return None
    event = latest_init(path)
    return (fromTimeStamp(event.ts), event.task) if event is not None else None


def _preview_table(db, table: str, *, has_guild: bool) -> dict:
    db.cur.execute(
        f'SELECT COUNT(*), '
        f'SUM(CASE WHEN yesterday_exp = exp THEN 1 ELSE 0 END), '
        f'SUM(CASE WHEN (exp - yesterday_exp) <> 0 THEN 1 ELSE 0 END), '
        f'COALESCE(SUM(exp - yesterday_exp), 0), '
        f'COALESCE(SUM(yesterday_incr), 0) '
        f'FROM {table};'
    )
    row = db.cur.fetchone()
    total = int(row[0] or 0)
    already_equal = int(row[1] or 0)
    changing = int(row[2] or 0)
    new_incr_sum = int(row[3] or 0)
    old_incr_sum = int(row[4] or 0)

    key_cols = 'guild, uid' if has_guild else 'uid'
    db.cur.execute(
        f'SELECT {key_cols}, exp, yesterday_exp, yesterday_incr, '
        f'(exp - yesterday_exp) AS new_incr '
        f'FROM {table} '
        f'ORDER BY new_incr DESC, {key_cols} ASC;'
    )
    samples = []
    for sample in db.cur.fetchall()[:_SAMPLE_LIMIT]:
        samples.append(sample)

    return {
        'table': table,
        'total': total,
        'already_equal': already_equal,
        'changing': changing,
        'new_incr_sum': new_incr_sum,
        'old_incr_sum': old_incr_sum,
        'samples': samples,
        'has_guild': has_guild,
    }


def _print_preview(preview: dict) -> None:
    print(f'=== {preview["table"]} ===')
    print(
        f'  rows={preview["total"]}  '
        f'exp==yesterday_exp={preview["already_equal"]}  '
        f'will_change_incr={preview["changing"]}'
    )
    print(
        f'  yesterday_incr sum {preview["old_incr_sum"]} '
        f'-> {preview["new_incr_sum"]}'
    )
    if not preview['samples']:
        print('  (empty)')
        return
    print('  top new_incr samples (key, exp, yesterday_exp, yesterday_incr -> new_incr):')
    for sample in preview['samples']:
        *keys, exp, y_exp, y_incr, new_incr = sample
        print(
            f'    {keys}  exp={exp}  yesterday_exp {y_exp}->{exp}  '
            f'yesterday_incr {y_incr}->{new_incr}'
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', type=Path, help='EXP log directory or legacy CSV for status lookup')
    parser.add_argument(
        '--apply',
        action='store_true',
        help='dailyDBInit 실행 (기본: dry-run)',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='오늘 롤오버 이후 이미 초기화된 것으로 보여도 다시 실행',
    )
    args = parser.parse_args()
    _ensure_utf8_stdio()

    now = getNow()
    last_roll = _last_rollover(now)
    next_roll = _next_rollover(now)
    today_idx = exp_day_index(now)
    past_rollover = now >= last_roll
    log_path = resolve_log(args.log)
    last_log = _last_daily_init_from_log(log_path)
    already_today = last_log is not None and last_log[0] >= last_roll

    mode = 'APPLY' if args.apply else 'DRY-RUN'
    print(f'mode={mode}')
    print(
        f'now={now.strftime("%Y-%m-%d %H:%M:%S %Z")}  '
        f'exp_day={today_idx}  '
        f'rollover={EXP_DAY_ROLLOVER.strftime("%H:%M")} KST'
    )
    print(
        f'last_rollover={last_roll.strftime("%Y-%m-%d %H:%M")}  '
        f'next_rollover={next_roll.strftime("%Y-%m-%d %H:%M")}'
    )
    if past_rollover:
        print('status: 오늘 05:15는 이미 지났습니다. 봇이 꺼져 있었다면 이 스크립트로 스냅샷을 맞춰야 합니다.')
    else:
        print('status: 아직 오늘 05:15 전입니다. 지금 적용하면 전날 구간을 한 번 더 자를 수 있습니다.')

    if last_log is None:
        print(f'last_init_log: (없음) {log_path}')
    else:
        when, task = last_log
        flag = ' [오늘 롤오버 이후 — 이미 실행된 것으로 보임]' if already_today else ''
        print(
            f'last_init_log: {when.strftime("%Y-%m-%d %H:%M:%S")}  '
            f'task={task}{flag}'
        )

    with _connectDB() as db:
        prefix = db.db_prefix
        guild_preview = _preview_table(db, f'{prefix}_exp', has_guild=True)
        global_preview = _preview_table(db, f'{prefix}_global_exp', has_guild=False)

    _print_preview(guild_preview)
    _print_preview(global_preview)
    print(
        '적용 내용: yesterday_incr = exp - yesterday_exp,  '
        'yesterday_exp = exp  (서버·글로벌 경험치 테이블)'
    )
    print(
        '건너뜀: Discord 프로필 캐시 갱신, 백업 일일 통계 DM, 분기 물갈이 '
        '(봇 기동 후 다음 05:15 또는 해당 명령으로 처리)'
    )
    print('참고: 출석(day_count)은 시각 기준이라 이 스크립트와 무관합니다.')

    if already_today and args.apply and not args.force:
        print(
            '거부: 오늘 롤오버 이후 daily init 로그가 있습니다. '
            '다시 실행하면 yesterday_incr가 0으로 덮입니다. 필요하면 --force'
        )
        return 2

    if not args.apply:
        print('no writes (dry-run). 봇을 내린 뒤 --apply 로 실행하세요.')
        return 0

    ran = dailyDBInit(force=args.force)
    if ran:
        logDailyInitExp(0, 'manual-script')
    try:
        archive_exp_logs()
    except (OSError, ValueError) as exc:
        print(f'EXP 로그 보관 실패. 다음 기동 또는 일일 초기화에서 재시도합니다. {exc}', file=sys.stderr)
    if not ran:
        print('skipped: 이미 이 경험치일에 스냅샷됨. 덮으려면 --force')
        return 2
    print('applied: dailyDBInit + log task 92 (manual-script)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
