# coding: utf-8
"""엑셀(4열) → 언어팩 .py import."""

from __future__ import annotations

import argparse
import pathlib
import sys

from lang_pack_xlsx_lib import format_diff_report, import_from_excel


def _print_report(tone_path: pathlib.Path, xlsx_path: pathlib.Path, plan) -> None:
    report = format_diff_report(plan, tone_path, xlsx_path)
    print(report, end="")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="4열 엑셀의 '설정할 값'을 반영해 언어팩 .py를 갱신합니다.",
        epilog="자세한 사용법: tools/LANG_PACK_XLSX.md",
    )
    parser.add_argument(
        "tone_py",
        type=pathlib.Path,
        help="기준 언어팩 .py 경로 (예: tone/default.py)",
    )
    parser.add_argument(
        "xlsx",
        type=pathlib.Path,
        help="고객이 수정한 .xlsx 경로",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        help="출력 .py 경로 (기본: tone_py를 덮어씀). 안전하게 쓰려면 다른 경로 지정",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="파일을 쓰지 않고 검증·diff 리포트만 출력",
    )
    parser.add_argument(
        "--diff-out",
        type=pathlib.Path,
        help="diff 리포트를 저장할 텍스트 파일 경로",
    )
    parser.add_argument(
        "--no-diff",
        action="store_true",
        help="콘솔에 diff 리포트를 출력하지 않음",
    )
    args = parser.parse_args()

    tone_path = args.tone_py.resolve()
    xlsx_path = args.xlsx.resolve()
    if not tone_path.is_file():
        print(f"파일을 찾을 수 없습니다: {tone_path}", file=sys.stderr)
        return 1
    if not xlsx_path.is_file():
        print(f"파일을 찾을 수 없습니다: {xlsx_path}", file=sys.stderr)
        return 1

    output_path = args.output.resolve() if args.output else None
    plan = import_from_excel(
        tone_path,
        xlsx_path,
        output_path,
        write=not args.dry_run,
    )

    if not args.no_diff:
        _print_report(tone_path, xlsx_path, plan)

    if args.diff_out:
        report = format_diff_report(plan, tone_path, xlsx_path)
        diff_path = args.diff_out.resolve()
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(report, encoding="utf-8")
        print(f"diff 리포트 저장: {diff_path}")

    if args.dry_run:
        print("dry-run 검증 성공 (파일은 변경하지 않았습니다)")
    elif plan.output_path:
        for line in plan.warnings:
            print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
