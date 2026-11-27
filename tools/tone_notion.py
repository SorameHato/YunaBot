# coding: utf-8
"""언어팩 .py ↔ Notion DB push/pull CLI."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

from lang_pack_notion_lib import (
    _client,
    compare_tone_keys,
    create_lang_pack_database,
    format_key_compare_report,
    format_notion_diff_report,
    pull_notion_to_tone,
    push_tone_to_notion,
    resolve_auth,
    resolve_token,
)


def _guess_addon_no(tone_path: pathlib.Path) -> str | None:
    match = re.search(r"addon_(\d+)", tone_path.stem)
    return match.group(1) if match else None


def _config_path(args: argparse.Namespace) -> pathlib.Path | None:
    return args.config.resolve() if args.config else None


def _add_auth_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--token",
        help="Notion integration token (기본: NOTION_TOKEN 또는 notion_config.json)",
    )
    parser.add_argument(
        "--database-id",
        help="Notion database ID (기본: NOTION_DATABASE_ID 또는 notion_config.json)",
    )
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        help="설정 JSON 경로 (기본: tools/notion_config.json)",
    )
    parser.add_argument(
        "--addon",
        help="notion_config.json databases 맵 키 (예: 0002). 미지정 시 파일명에서 추정",
    )


def cmd_init(args: argparse.Namespace) -> int:
    try:
        token = resolve_token(token=args.token, config_path=_config_path(args))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    notion = _client(token)
    db_id = create_lang_pack_database(
        notion,
        parent_page_id=args.parent_page_id,
        title=args.title,
    )
    print("데이터베이스 생성 완료")
    print(f"  title : {args.title}")
    print(f"  id    : {db_id}")
    print("이 ID를 notion_config.json 의 database_id 또는 databases.0002 등에 넣으세요.")
    print("Integration을 해당 DB(또는 상위 페이지)에 Connect 해야 API로 접근됩니다.")
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    tone_path = args.tone_py.resolve()
    if not tone_path.is_file():
        print(f"파일을 찾을 수 없습니다: {tone_path}", file=sys.stderr)
        return 1

    addon = args.addon or _guess_addon_no(tone_path)
    try:
        token, database_id = resolve_auth(
            token=args.token,
            database_id=args.database_id,
            config_path=_config_path(args),
            addon_no=addon,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        result = push_tone_to_notion(
            tone_path,
            token=token,
            database_id=database_id,
            create_only=args.create_only,
            dry_run=args.dry_run,
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    mode = "dry-run " if args.dry_run else ""
    print(f"{mode}push 완료 → DB {database_id}")
    print(f"  생성: {result.created}")
    print(f"  갱신: {result.updated}")
    print(f"  생략: {result.skipped}")
    if args.create_only:
        print("  (create-only: 기존 페이지 대사는 덮어쓰지 않음)")
    for warning in result.warnings:
        print(f"  참고: {warning}")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    tone_path = args.tone_py.resolve()
    if not tone_path.is_file():
        print(f"파일을 찾을 수 없습니다: {tone_path}", file=sys.stderr)
        return 1

    addon = args.addon or _guess_addon_no(tone_path)
    try:
        token, database_id = resolve_auth(
            token=args.token,
            database_id=args.database_id,
            config_path=_config_path(args),
            addon_no=addon,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_path = args.output.resolve() if args.output else None
    try:
        result = pull_notion_to_tone(
            tone_path,
            token=token,
            database_id=database_id,
            output_path=output_path,
            write=not args.dry_run,
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    plan = result.plan
    assert plan is not None

    if not args.no_diff:
        print(format_notion_diff_report(plan, tone_path, database_id), end="")

    if args.diff_out:
        report = format_notion_diff_report(plan, tone_path, database_id)
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


def cmd_compare(args: argparse.Namespace) -> int:
    tone_path = args.tone_py.resolve()
    if not tone_path.is_file():
        print(f"파일을 찾을 수 없습니다: {tone_path}", file=sys.stderr)
        return 1

    addon = args.addon or _guess_addon_no(tone_path)
    try:
        token, database_id = resolve_auth(
            token=args.token,
            database_id=args.database_id,
            config_path=_config_path(args),
            addon_no=addon,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        result = compare_tone_keys(
            tone_path,
            token=token,
            database_id=database_id,
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    report = format_key_compare_report(result, tone_path, database_id)
    print(report, end="")

    if args.out:
        out_path = args.out.resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"리포트 저장: {out_path}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="언어팩 .py와 Notion DB(키/대사)를 동기화합니다.",
        epilog="자세한 사용법: tools/LANG_PACK_NOTION.md",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="키/대사 속성을 가진 Notion DB를 생성합니다.")
    _add_auth_args(init_p)
    init_p.add_argument(
        "--parent-page-id",
        required=True,
        help="DB를 만들 상위 Notion 페이지 ID",
    )
    init_p.add_argument(
        "--title",
        default="언어팩",
        help="생성할 데이터베이스 제목 (기본: 언어팩)",
    )
    init_p.set_defaults(func=cmd_init)

    push_p = sub.add_parser("push", help=".py → Notion (키/대사만, 페이지 본문은 유지)")
    _add_auth_args(push_p)
    push_p.add_argument("tone_py", type=pathlib.Path, help="언어팩 .py (예: tone/addon_0002.py)")
    push_p.add_argument(
        "--create-only",
        action="store_true",
        help="없는 키만 생성하고, 기존 페이지의 대사는 덮어쓰지 않음",
    )
    push_p.add_argument(
        "--dry-run",
        action="store_true",
        help="생성/갱신 개수만 계산하고 Notion에는 쓰지 않음",
    )
    push_p.set_defaults(func=cmd_push)

    pull_p = sub.add_parser("pull", help="Notion → .py (대사만 반영)")
    _add_auth_args(pull_p)
    pull_p.add_argument("tone_py", type=pathlib.Path, help="기준 언어팩 .py")
    pull_p.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        help="출력 .py 경로 (기본: tone_py 덮어쓰기)",
    )
    pull_p.add_argument(
        "--dry-run",
        action="store_true",
        help="파일을 쓰지 않고 검증·diff만 출력",
    )
    pull_p.add_argument(
        "--diff-out",
        type=pathlib.Path,
        help="diff 리포트를 저장할 텍스트 파일",
    )
    pull_p.add_argument(
        "--no-diff",
        action="store_true",
        help="콘솔 diff 출력 생략",
    )
    pull_p.set_defaults(func=cmd_pull)

    compare_p = sub.add_parser(
        "compare",
        help="로컬 .py와 Notion DB의 키 집합을 비교합니다",
    )
    _add_auth_args(compare_p)
    compare_p.add_argument("tone_py", type=pathlib.Path, help="언어팩 .py (예: tone/addon_0002.py)")
    compare_p.add_argument(
        "-o",
        "--out",
        type=pathlib.Path,
        help="비교 리포트를 저장할 텍스트 파일",
    )
    compare_p.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
