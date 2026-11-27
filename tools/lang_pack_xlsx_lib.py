# coding: utf-8
"""언어팩 .py <-> 엑셀(4열) 변환 공통 라이브러리."""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

openpyxl = None  # lazy
Font = None
PatternFill = None
Worksheet = None

SHEET_MAIN = "팩"
SHEET_RAW = "원시데이터"
HEADERS = ("변수명", "설명", "예시 값", "설정할 값")
PARM_PREFIX = "PARM_"
EXCEL_ERRORS = {"#VALUE!", "#N/A", "#REF!", "#NAME?", "#DIV/0!", "#NULL!", "#NUM!"}


def _require_openpyxl():
    global openpyxl, Font, PatternFill, Worksheet
    if openpyxl is not None:
        return
    try:
        import openpyxl as _openpyxl
        from openpyxl.styles import Font as _Font, PatternFill as _PatternFill
        from openpyxl.worksheet.worksheet import Worksheet as _Worksheet
    except ImportError as exc:  # pragma: no cover - runtime guard
        raise SystemExit(
            "openpyxl이 필요합니다. pip install openpyxl 로 설치해 주세요."
        ) from exc
    openpyxl = _openpyxl
    Font = _Font
    PatternFill = _PatternFill
    Worksheet = _Worksheet


@dataclass
class LangPackEntry:
    key: str
    comments: list[str] = field(default_factory=list)
    value_lines: list[str] = field(default_factory=list)
    value: Any = None


@dataclass
class ToneFileData:
    path: pathlib.Path
    header: str
    parm_block: str
    lang_pack_prefix: str
    entries: list[LangPackEntry]
    lang_pack_suffix: str
    parm_values: dict[str, Any]
    parm_comments: dict[str, str]
    lang_pack_values: dict[str, Any]


@dataclass
class LangPackChange:
    key: str
    old: Any
    new: Any
    source: str


@dataclass
class ImportPlan:
    updated_values: dict[str, Any]
    warnings: list[str]
    changes: list[LangPackChange]
    output_path: pathlib.Path | None = None


def _load_module(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(f"tone_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"모듈을 로드할 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _count_brackets(text: str) -> int:
    depth = 0
    in_single = False
    in_double = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single or in_double:
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
    return depth


def _strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False
    escape = False
    for idx, ch in enumerate(line):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single or in_double:
            continue
        if ch == "#":
            return line[:idx].rstrip()
    return line.rstrip()


def _is_comment_or_section_line(stripped: str) -> bool:
    if not stripped:
        return True
    if stripped.startswith("#"):
        return True
  # section headers like ##### or ####
    if stripped.startswith("#####") or stripped.startswith("####"):
        return True
    return False


def _parse_key_line(line: str) -> tuple[str, str] | None:
    match = re.match(r"^(\s*)'([^']+)'\s*:\s*(.*)$", line)
    if not match:
        return None
    return match.group(2), match.group(3)


def _parse_parm_block(source: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    lines = source.splitlines(keepends=True)
    parm_values: dict[str, Any] = {}
    parm_comments: dict[str, str] = {}
    parm_lines: list[str] = []

    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("LANG_PACK"):
            break
        parm_lines.append(line)
        if not (stripped.startswith(PARM_PREFIX) and "=" in stripped):
            continue

        name = stripped.split("=", 1)[0].strip()
        expr = stripped.split("=", 1)[1].strip()
        inline_comment = ""
        if "#" in expr:
            code, _, inline_comment = expr.partition("#")
            expr = code.strip()
            inline_comment = inline_comment.strip()
        try:
            parm_values[name] = ast.literal_eval(expr)
        except (SyntaxError, ValueError):
            parm_values[name] = expr.strip("'\"")

        desc_lines: list[str] = []
        for prev in range(line_idx - 1, -1, -1):
            prev_stripped = lines[prev].strip()
            if not prev_stripped:
                break
            if prev_stripped.startswith("#"):
                text = prev_stripped.lstrip("#").strip()
                if text.startswith("coding:"):
                    continue
                desc_lines.insert(0, text)
                continue
            break
        if inline_comment:
            desc_lines.append(inline_comment)
        parm_comments[name] = "\n".join(desc_lines)

    parm_block = "".join(parm_lines)
    return parm_block, parm_values, parm_comments


def _parse_lang_pack_entries(lang_pack_body: str) -> list[LangPackEntry]:
    lines = lang_pack_body.splitlines(keepends=True)
    entries: list[LangPackEntry] = []
    comment_buf: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if _is_comment_or_section_line(stripped) and not _parse_key_line(_strip_inline_comment(line)):
            comment_buf.append(line)
            i += 1
            continue

        parsed = _parse_key_line(_strip_inline_comment(line))
        if not parsed:
            i += 1
            continue

        key, rest = parsed
        value_lines = [line]
        combined = rest
        depth = _count_brackets(rest)
        j = i + 1
        while depth > 0 and j < len(lines):
            value_lines.append(lines[j])
            combined += lines[j]
            depth += _count_brackets(lines[j])
            j += 1

        expr = combined.strip()
        if expr.endswith(","):
            expr = expr[:-1].strip()
        try:
            value = ast.literal_eval(expr)
        except (SyntaxError, ValueError):
            value = expr

        entries.append(
            LangPackEntry(
                key=key,
                comments=list(comment_buf),
                value_lines=value_lines,
                value=value,
            )
        )
        comment_buf = []
        i = j

    return entries


def parse_tone_file(path: pathlib.Path) -> ToneFileData:
    source = path.read_text(encoding="utf-8")
    module = _load_module(path)

    lang_pack_match = re.search(r"^LANG_PACK\s*=\s*\{", source, re.MULTILINE)
    if not lang_pack_match:
        raise ValueError(f"LANG_PACK 블록을 찾을 수 없습니다: {path}")

    start = lang_pack_match.start()
    header = source[:start]

    brace_start = source.find("{", lang_pack_match.start())
    depth = 0
    end = brace_start
    for idx in range(brace_start, len(source)):
        ch = source[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = idx
                break
    else:
        raise ValueError(f"LANG_PACK 닫는 중괄호를 찾을 수 없습니다: {path}")

    lang_pack_block = source[brace_start + 1 : end]
    lang_pack_prefix = source[lang_pack_match.start() : brace_start + 1]
    lang_pack_suffix = source[end:]

    parm_block, parm_values, parm_comments = _parse_parm_block(header)
    entries = _parse_lang_pack_entries(lang_pack_block)
    lang_pack_values = getattr(module, "LANG_PACK", {}) or {}

    return ToneFileData(
        path=path,
        header=header,
        parm_block=parm_block,
        lang_pack_prefix=lang_pack_prefix,
        entries=entries,
        lang_pack_suffix=lang_pack_suffix,
        parm_values=parm_values,
        parm_comments=parm_comments,
        lang_pack_values=lang_pack_values,
    )


def format_excel_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple, dict)):
        return repr(value)
    if value is None:
        return None
    return str(value)


def _format_list_value(key: str, value: list) -> list[str]:
    if key == "expFE_res_daily":
        lines = ["    'expFE_res_daily':[\n"]
        for row in value:
            threshold = "None" if row[0] is None else repr(row[0])
            title = repr(row[1])
            body = repr(row[2])
            lines.append(f"        [{threshold},{title},{body}],\n")
        lines.append("    ],\n")
        return lines

    compact = repr(value)
    return [f"    '{key}':{compact},\n"]


def _format_scalar_value_line(key: str, value: Any, original_lines: list[str]) -> list[str]:
    if isinstance(value, bool):
        rendered = "True" if value else "False"
        return [f"    '{key}': {rendered},\n"]

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [f"    '{key}': {value},\n"]

    if isinstance(value, str):
        line = f"    '{key}':{value!r},\n"
        if original_lines:
            orig = original_lines[-1]
            inline_match = re.search(r"(#.+)$", orig.rstrip("\n"))
            if inline_match and inline_match.group(1) not in line:
                line = line.rstrip("\n") + f" {inline_match.group(1)}\n"
        return [line]

    if isinstance(value, (list, tuple)):
        return _format_list_value(key, list(value))

    return [f"    '{key}':{repr(value)},\n"]


def format_entry_value_lines(entry: LangPackEntry, value: Any) -> list[str]:
    return _format_scalar_value_line(entry.key, value, entry.value_lines)


def render_tone_file(data: ToneFileData, updated_values: dict[str, Any]) -> str:
    parts = [data.header, data.lang_pack_prefix]
    for entry in data.entries:
        value = updated_values.get(entry.key, entry.value)
        parts.extend(entry.comments)
        parts.extend(format_entry_value_lines(entry, value))
    parts.append(data.lang_pack_suffix)
    return "".join(parts)


def _cell_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if not text or text in EXCEL_ERRORS:
        return None
    return text


def parse_tone_value(raw: Any, original: Any, *, treat_excel_errors: bool = False) -> Any:
    """원시 텍스트/셀 값을 기존 LANG_PACK 값 타입에 맞춰 파싱합니다."""
    if raw is None:
        return original
    if treat_excel_errors and isinstance(raw, str) and raw.strip() in EXCEL_ERRORS:
        return original

    if isinstance(original, bool):
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in {"true", "1", "yes", "y", "참"}:
            return True
        if text in {"false", "0", "no", "n", "거짓"}:
            return False
        raise ValueError(f"불리언 값을 해석할 수 없습니다: {raw!r}")

    if isinstance(original, int) and not isinstance(original, bool):
        if isinstance(raw, (int, float)):
            return int(raw)
        return int(str(raw).strip())

    if isinstance(original, float) and not isinstance(original, bool):
        if isinstance(raw, (int, float)):
            return float(raw)
        return float(str(raw).strip())

    if isinstance(original, (list, tuple)):
        text = str(raw).strip()
        return ast.literal_eval(text)

    return str(raw)


def _parse_import_value(raw: Any, original: Any) -> Any:
    return parse_tone_value(raw, original, treat_excel_errors=True)


def read_excel_rows(xlsx_path: pathlib.Path) -> list[tuple[str, str | None, Any, Any]]:
    _require_openpyxl()
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    if SHEET_MAIN not in wb.sheetnames:
        raise ValueError(f"'{SHEET_MAIN}' 시트를 찾을 수 없습니다: {xlsx_path}")
    ws = wb[SHEET_MAIN]

    rows: list[tuple[str, str | None, Any, Any]] = []
    for row_idx in range(2, ws.max_row + 1):
        key = _cell_text(ws.cell(row_idx, 1).value)
        if not key:
            continue
        desc = ws.cell(row_idx, 2).value
        example = ws.cell(row_idx, 3).value
        custom = ws.cell(row_idx, 4).value
        rows.append((key, None if desc is None else str(desc), example, custom))
    return rows


def resolve_row_value(example: Any, custom: Any, original: Any) -> Any:
    value, _source = resolve_row_value_with_source(example, custom, original)
    return value


def resolve_row_value_with_source(
    example: Any,
    custom: Any,
    original: Any,
) -> tuple[Any, str | None]:
    chosen = custom
    source = "column_d"
    if _cell_text(custom) is None:
        chosen = example
        source = "column_c"
    if _cell_text(chosen) is None:
        return original, None
    return _parse_import_value(chosen, original), source


def apply_excel_to_tone(data: ToneFileData, xlsx_path: pathlib.Path) -> tuple[dict[str, Any], list[str]]:
    plan = plan_import_from_excel(data, xlsx_path)
    return plan.updated_values, plan.warnings


def plan_import_from_excel(data: ToneFileData, xlsx_path: pathlib.Path) -> ImportPlan:
    rows = read_excel_rows(xlsx_path)
    warnings: list[str] = []
    original = {entry.key: entry.value for entry in data.entries}
    updated = dict(original)
    changes: list[LangPackChange] = []

    excel_keys = set()
    for key, _desc, example, custom in rows:
        excel_keys.add(key)
        if key.startswith(PARM_PREFIX):
            continue
        if key not in updated:
            warnings.append(f"엑셀에만 있는 키(무시): {key}")
            continue
        try:
            new_value, source = resolve_row_value_with_source(example, custom, updated[key])
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"키 '{key}' 값 파싱 실패: {exc}") from exc
        if new_value != original[key]:
            changes.append(
                LangPackChange(
                    key=key,
                    old=original[key],
                    new=new_value,
                    source=source or "unknown",
                )
            )
        updated[key] = new_value

    missing = set(updated) - excel_keys
    if missing:
        warnings.append(
            f"엑셀에 없는 LANG_PACK 키 {len(missing)}개 — 기존 .py 값 유지"
        )
    return ImportPlan(updated_values=updated, warnings=warnings, changes=changes)


def _format_diff_value(value: Any, max_len: int = 120) -> str:
    if isinstance(value, bool):
        text = "TRUE" if value else "FALSE"
    elif isinstance(value, (list, tuple, dict)):
        text = repr(value)
    elif value is None:
        text = "(없음)"
    else:
        text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _source_label(source: str) -> str:
    if source == "column_d":
        return "D열(설정할 값)"
    if source == "column_c":
        return "C열(예시 값)"
    if source == "notion":
        return "Notion 대사"
    return source


def format_diff_report(
    plan: ImportPlan,
    tone_path: pathlib.Path,
    source_path: pathlib.Path | str,
    *,
    source_name: str = "엑셀",
) -> str:
    lines = [
        "=== 언어팩 변경 diff 리포트 ===",
        f"기준 .py : {tone_path}",
        f"{source_name:<8}: {source_path}",
        f"변경 키  : {len(plan.changes)}개",
        "",
    ]
    if not plan.changes:
        lines.append("(반영될 변경 없음)")
    else:
        for idx, change in enumerate(plan.changes, start=1):
            lines.extend(
                [
                    f"[{idx}] {change.key}  ← {_source_label(change.source)}",
                    f"  - 이전: {_format_diff_value(change.old)}",
                    f"  + 이후: {_format_diff_value(change.new)}",
                    "",
                ]
            )

    if plan.warnings:
        lines.append("--- 참고 ---")
        lines.extend(plan.warnings)
    return "\n".join(lines).rstrip() + "\n"


def _style_header(ws) -> None:
    _require_openpyxl()
    header_fill = PatternFill("solid", fgColor="F4CCCC")
    header_font = Font(bold=True)
    for col, title in enumerate(HEADERS, start=1):
        cell = ws.cell(1, col, title)
        cell.fill = header_fill
        cell.font = header_font
    ws.freeze_panes = "A2"
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 48
    ws.column_dimensions["C"].width = 52
    ws.column_dimensions["D"].width = 52


def _write_raw_sheet(wb, lang_values: dict[str, Any]) -> None:
    if SHEET_RAW in wb.sheetnames:
        del wb[SHEET_RAW]
    ws = wb.create_sheet(SHEET_RAW)
    for idx, (key, value) in enumerate(lang_values.items(), start=1):
        ws.cell(idx, 1, key)
        ws.cell(idx, 2, format_excel_value(value))


def export_to_excel(tone_path: pathlib.Path, xlsx_path: pathlib.Path) -> None:
    _require_openpyxl()
    data = parse_tone_file(tone_path)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_MAIN
    _style_header(ws)

    row_idx = 2
    for name in data.parm_values:
        ws.cell(row_idx, 1, name)
        ws.cell(row_idx, 2, data.parm_comments.get(name))
        ws.cell(row_idx, 3, format_excel_value(data.parm_values[name]))
        ws.cell(row_idx, 4, None)
        row_idx += 1

    for entry in data.entries:
        ws.cell(row_idx, 1, entry.key)
        desc = "".join(
            line.lstrip("#").strip() + "\n"
            for line in entry.comments
            if line.strip().startswith("#")
        ).strip()
        ws.cell(row_idx, 2, desc or None)
        ws.cell(row_idx, 3, format_excel_value(entry.value))
        ws.cell(row_idx, 4, None)
        row_idx += 1

    _write_raw_sheet(wb, data.lang_pack_values)
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx_path)


def import_from_excel(
    tone_path: pathlib.Path,
    xlsx_path: pathlib.Path,
    output_path: pathlib.Path | None = None,
    *,
    write: bool = True,
) -> ImportPlan:
    data = parse_tone_file(tone_path)
    plan = plan_import_from_excel(data, xlsx_path)
    if not write:
        return plan

    rendered = render_tone_file(data, plan.updated_values)
    target = output_path or tone_path
    target.write_text(rendered, encoding="utf-8")
    _load_module(target)
    plan.output_path = target
    plan.warnings.insert(0, f"저장 완료: {target}")
    return plan
