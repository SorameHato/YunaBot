# coding: utf-8
"""언어팩 .py → 엑셀(4열) export."""

from __future__ import annotations

import argparse
import pathlib
import sys

from lang_pack_xlsx_lib import export_to_excel


def main() -> int:
    parser = argparse.ArgumentParser(
        description="언어팩 .py 파일을 4열 엑셀(팩 시트)로보냅니다.",
        epilog="자세한 사용법: tools/LANG_PACK_XLSX.md",
    )
    parser.add_argument(
        "tone_py",
        type=pathlib.Path,
        help="언어팩 .py 경로 (예: tone/default.py)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        help="출력 .xlsx 경로 (기본: <tone_stem>_langpack.xlsx)",
    )
    args = parser.parse_args()

    tone_path = args.tone_py.resolve()
    if not tone_path.is_file():
        print(f"파일을 찾을 수 없습니다: {tone_path}", file=sys.stderr)
        return 1

    output = args.output
    if output is None:
        output = tone_path.with_name(f"{tone_path.stem}_langpack.xlsx")
    output = output.resolve()

    export_to_excel(tone_path, output)
    print(f"엑셀 생성 완료: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
