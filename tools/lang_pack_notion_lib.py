# coding: utf-8
"""언어팩 .py ↔ Notion DB (키 / 대사) 동기화."""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any

from lang_pack_xlsx_lib import (
    ImportPlan,
    LangPackChange,
    ToneFileData,
    format_diff_report,
    format_excel_value,
    parse_tone_file,
    parse_tone_value,
    render_tone_file,
)

try:
    from notion_client import Client
    from notion_client.errors import APIResponseError
except ImportError as exc:  # pragma: no cover - runtime guard
    raise SystemExit(
        "notion-client가 필요합니다. pip install notion-client 로 설치해 주세요."
    ) from exc

PROP_KEY = "키"
PROP_VALUE = "예시 대사"
RICH_TEXT_CHUNK = 2000
DEFAULT_CONFIG_NAME = "notion_config.json"
REQUEST_PAUSE_SEC = 0.35


@dataclass
class NotionPageRow:
    page_id: str
    key: str
    value_text: str


@dataclass
class NotionSyncResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    plan: ImportPlan | None = None


def load_notion_config(path: pathlib.Path | None = None) -> dict[str, Any]:
    if path is None:
        path = pathlib.Path(__file__).resolve().parent / DEFAULT_CONFIG_NAME
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_token(
    *,
    token: str | None = None,
    config_path: pathlib.Path | None = None,
) -> str:
    import os

    cfg = load_notion_config(config_path)
    resolved = token or os.environ.get("NOTION_TOKEN") or cfg.get("token")
    if not resolved:
        raise ValueError(
            "Notion 토큰이 없습니다. NOTION_TOKEN 환경변수, --token, "
            "또는 tools/notion_config.json 의 token 을 설정하세요."
        )
    return str(resolved)


def resolve_auth(
    *,
    token: str | None = None,
    database_id: str | None = None,
    config_path: pathlib.Path | None = None,
    addon_no: str | None = None,
) -> tuple[str, str]:
    import os

    cfg = load_notion_config(config_path)
    resolved_token = resolve_token(token=token, config_path=config_path)
    resolved_db = database_id or os.environ.get("NOTION_DATABASE_ID")

    if not resolved_db and addon_no is not None:
        databases = cfg.get("databases") or {}
        raw = str(addon_no).strip()
        candidates = [raw]
        if raw.isdigit():
            candidates.append(raw.zfill(4))
            candidates.append(str(int(raw)))
        for candidate in candidates:
            if candidate in databases:
                resolved_db = databases[candidate]
                break

    if not resolved_db:
        resolved_db = cfg.get("database_id")

    if not resolved_db:
        raise ValueError(
            "Database ID가 없습니다. NOTION_DATABASE_ID, --database-id, "
            "또는 tools/notion_config.json 의 database_id / databases 를 설정하세요."
        )
    return resolved_token, _normalize_id(str(resolved_db))


def _normalize_id(value: str) -> str:
    return value.replace("-", "").strip()


def _client(token: str) -> Client:
    return Client(auth=token)


def _plain_rich_text(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    chunks = prop.get("rich_text") or prop.get("title") or []
    return "".join(part.get("plain_text", "") for part in chunks)


def _rich_text_property(text: str) -> dict[str, Any]:
    if text == "":
        return {"rich_text": []}
    chunks = []
    for i in range(0, len(text), RICH_TEXT_CHUNK):
        piece = text[i : i + RICH_TEXT_CHUNK]
        chunks.append({"type": "text", "text": {"content": piece}})
    return {"rich_text": chunks}


def _title_property(text: str) -> dict[str, Any]:
    if text == "":
        return {"title": []}
    # title도 2000자 제한 — 키는 짧음
    return {"title": [{"type": "text", "text": {"content": text[:RICH_TEXT_CHUNK]}}]}


def _sleep() -> None:
    time.sleep(REQUEST_PAUSE_SEC)


def resolve_data_source_id(notion: Client, database_id: str) -> str:
    """URL의 database_id → API용 data_source_id (Notion API 2025-09-03)."""
    database_id = _normalize_id(database_id)
    try:
        db = notion.databases.retrieve(database_id=database_id)
    except APIResponseError as exc:
        raise RuntimeError(
            f"Notion DB 조회 실패 (database_id={database_id}): {exc}\n"
            "Integration을 해당 데이터베이스에 Connect 했는지 확인하세요."
        ) from exc

    sources = db.get("data_sources") or []
    if not sources:
        raise RuntimeError(
            f"database_id={database_id} 에 data_sources가 없습니다. "
            "Notion에서 DB를 다시 열거나 Integration 권한을 확인하세요."
        )
    return _normalize_id(sources[0]["id"])


def iter_data_source_pages(notion: Client, data_source_id: str) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    cursor = None
    data_source_id = _normalize_id(data_source_id)
    while True:
        kwargs: dict[str, Any] = {
            "data_source_id": data_source_id,
            "page_size": 100,
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        try:
            response = notion.data_sources.query(**kwargs)
        except APIResponseError as exc:
            raise RuntimeError(f"Notion data source 조회 실패: {exc}") from exc
        pages.extend(response.get("results") or [])
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
        _sleep()
    return pages


def iter_database_pages(notion: Client, database_id: str) -> list[dict[str, Any]]:
    return iter_data_source_pages(notion, resolve_data_source_id(notion, database_id))


def pages_to_rows(pages: list[dict[str, Any]]) -> list[NotionPageRow]:
    rows: list[NotionPageRow] = []
    for page in pages:
        if page.get("archived"):
            continue
        props = page.get("properties") or {}
        if PROP_KEY not in props:
            raise ValueError(
                f"DB에 '{PROP_KEY}'(title) 속성이 없습니다. "
                f"현재 속성: {', '.join(props.keys()) or '(없음)'}"
            )
        if PROP_VALUE not in props:
            raise ValueError(
                f"DB에 '{PROP_VALUE}'(rich_text) 속성이 없습니다. "
                f"현재 속성: {', '.join(props.keys()) or '(없음)'}"
            )
        key = _plain_rich_text(props.get(PROP_KEY)).strip()
        if not key:
            continue
        value_text = _plain_rich_text(props.get(PROP_VALUE))
        rows.append(
            NotionPageRow(
                page_id=page["id"],
                key=key,
                value_text=value_text,
            )
        )
    return rows


def pages_to_keys(pages: list[dict[str, Any]]) -> list[str]:
    """페이지에서 키(title)만 추출합니다. 대사 속성은 없어도 됩니다."""
    keys: list[str] = []
    for page in pages:
        if page.get("archived"):
            continue
        props = page.get("properties") or {}
        if PROP_KEY not in props:
            raise ValueError(
                f"DB에 '{PROP_KEY}'(title) 속성이 없습니다. "
                f"현재 속성: {', '.join(props.keys()) or '(없음)'}"
            )
        key = _plain_rich_text(props.get(PROP_KEY)).strip()
        if key:
            keys.append(key)
    return keys


def value_to_notion_text(value: Any) -> str:
    formatted = format_excel_value(value)
    if formatted is None:
        return ""
    return str(formatted)


def _data_source_properties(notion: Client, data_source_id: str) -> dict[str, Any]:
    try:
        ds = notion.data_sources.retrieve(data_source_id=_normalize_id(data_source_id))
    except APIResponseError as exc:
        raise RuntimeError(f"data source 조회 실패: {exc}") from exc
    return ds.get("properties") or {}


def ensure_lang_pack_schema(notion: Client, data_source_id: str) -> list[str]:
    """키(title)·대사(rich_text) 속성이 있도록 스키마를 맞춥니다.

    - title이 Name 등 다른 이름이면 → `키`로 이름 변경
    - `대사`가 없으면 rich_text로 추가
    """
    data_source_id = _normalize_id(data_source_id)
    props = _data_source_properties(notion, data_source_id)
    notes: list[str] = []
    patch: dict[str, Any] = {}

    if PROP_KEY not in props:
        title_names = [name for name, meta in props.items() if meta.get("type") == "title"]
        if title_names:
            old = title_names[0]
            patch[old] = {"name": PROP_KEY}
            notes.append(f"title 속성 '{old}' → '{PROP_KEY}' 로 이름 변경")
        else:
            # Notion은 title 속성이 항상 있어야 함 — 없으면 생성 시도
            patch[PROP_KEY] = {"title": {}}
            notes.append(f"title 속성 '{PROP_KEY}' 추가")

    if PROP_VALUE not in props:
        # 이름 변경만으로 PROP_VALUE가 생기는 경우는 없음
        patch[PROP_VALUE] = {"rich_text": {}}
        notes.append(f"rich_text 속성 '{PROP_VALUE}' 추가")

    if not patch:
        return notes

    try:
        notion.data_sources.update(
            data_source_id=data_source_id,
            properties=patch,
        )
    except APIResponseError as exc:
        raise RuntimeError(
            f"스키마 보정 실패: {exc}\n"
            f"현재 속성: {', '.join(props.keys()) or '(없음)'}\n"
            f"Notion에서 '{PROP_KEY}'(제목), '{PROP_VALUE}'(텍스트) 열을 직접 만들어도 됩니다."
        ) from exc
    _sleep()

    # 검증
    props2 = _data_source_properties(notion, data_source_id)
    missing = [n for n in (PROP_KEY, PROP_VALUE) if n not in props2]
    if missing:
        raise RuntimeError(
            f"스키마 보정 후에도 속성이 없습니다: {', '.join(missing)}. "
            f"현재: {', '.join(props2.keys()) or '(없음)'}"
        )
    return notes


def create_lang_pack_database(
    notion: Client,
    *,
    parent_page_id: str,
    title: str,
) -> str:
    parent_page_id = _normalize_id(parent_page_id)
    try:
        # API 2025-09-03: 속성은 initial_data_source 아래에 둠
        created = notion.databases.create(
            parent={"type": "page_id", "page_id": parent_page_id},
            title=[{"type": "text", "text": {"content": title}}],
            initial_data_source={
                "properties": {
                    PROP_KEY: {"title": {}},
                    PROP_VALUE: {"rich_text": {}},
                }
            },
        )
    except APIResponseError as exc:
        raise RuntimeError(f"Notion DB 생성 실패: {exc}") from exc

    db_id = created["id"]
    # 생성 직후 스키마가 Name만 있는 경우 대비
    try:
        ds_id = resolve_data_source_id(notion, db_id)
        ensure_lang_pack_schema(notion, ds_id)
    except RuntimeError:
        pass
    return db_id


def push_tone_to_notion(
    tone_path: pathlib.Path,
    *,
    token: str,
    database_id: str,
    create_only: bool = False,
    dry_run: bool = False,
) -> NotionSyncResult:
    data = parse_tone_file(tone_path)
    notion = _client(token)
    data_source_id = resolve_data_source_id(notion, database_id)
    schema_notes = ensure_lang_pack_schema(notion, data_source_id)
    existing = pages_to_rows(iter_data_source_pages(notion, data_source_id))
    by_key = {row.key: row for row in existing}

    result = NotionSyncResult(warnings=list(schema_notes))
    duplicate_keys = set()
    seen: set[str] = set()
    for row in existing:
        if row.key in seen:
            duplicate_keys.add(row.key)
        seen.add(row.key)
    if duplicate_keys:
        result.warnings.append(
            f"Notion에 중복 키 {len(duplicate_keys)}개 — 마지막 페이지만 갱신 대상으로 사용: "
            + ", ".join(sorted(duplicate_keys)[:10])
            + ("..." if len(duplicate_keys) > 10 else "")
        )

    for entry in data.entries:
        text = value_to_notion_text(entry.value)
        if len(text) > RICH_TEXT_CHUNK * 50:
            result.warnings.append(f"값이 매우 김(푸시 생략): {entry.key}")
            result.skipped += 1
            continue

        row = by_key.get(entry.key)
        if row is None:
            result.created += 1
            if dry_run:
                continue
            try:
                notion.pages.create(
                    parent={"type": "data_source_id", "data_source_id": data_source_id},
                    properties={
                        PROP_KEY: _title_property(entry.key),
                        PROP_VALUE: _rich_text_property(text),
                    },
                )
            except APIResponseError as exc:
                raise RuntimeError(f"페이지 생성 실패 ({entry.key}): {exc}") from exc
            _sleep()
            continue

        if create_only:
            result.skipped += 1
            continue

        if row.value_text == text:
            result.skipped += 1
            continue

        result.updated += 1
        if dry_run:
            continue
        try:
            notion.pages.update(
                page_id=row.page_id,
                properties={PROP_VALUE: _rich_text_property(text)},
            )
        except APIResponseError as exc:
            raise RuntimeError(f"페이지 갱신 실패 ({entry.key}): {exc}") from exc
        _sleep()

    notion_only = sorted(set(by_key) - {e.key for e in data.entries})
    if notion_only:
        result.warnings.append(
            f".py에 없는 Notion 키 {len(notion_only)}개 — push에서 삭제하지 않음"
        )
    return result


def plan_pull_from_notion(
    data: ToneFileData,
    rows: list[NotionPageRow],
) -> ImportPlan:
    original = {entry.key: entry.value for entry in data.entries}
    updated = dict(original)
    warnings: list[str] = []
    changes: list[LangPackChange] = []

    notion_keys: set[str] = set()
    for row in rows:
        notion_keys.add(row.key)
        if row.key not in updated:
            warnings.append(f"Notion에만 있는 키(무시): {row.key}")
            continue
        if row.value_text.strip() == "" and not isinstance(original[row.key], str):
            # 비문자 타입에 빈 대사는 유지
            warnings.append(f"빈 대사 — 기존 값 유지: {row.key}")
            continue
        try:
            new_value = parse_tone_value(row.value_text, updated[row.key])
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"키 '{row.key}' 값 파싱 실패: {exc}") from exc
        if new_value != original[row.key]:
            changes.append(
                LangPackChange(
                    key=row.key,
                    old=original[row.key],
                    new=new_value,
                    source="notion",
                )
            )
        updated[row.key] = new_value

    missing = set(updated) - notion_keys
    if missing:
        warnings.append(
            f"Notion에 없는 LANG_PACK 키 {len(missing)}개 — 기존 .py 값 유지"
        )
    return ImportPlan(updated_values=updated, warnings=warnings, changes=changes)


def pull_notion_to_tone(
    tone_path: pathlib.Path,
    *,
    token: str,
    database_id: str,
    output_path: pathlib.Path | None = None,
    write: bool = True,
) -> NotionSyncResult:
    data = parse_tone_file(tone_path)
    notion = _client(token)
    data_source_id = resolve_data_source_id(notion, database_id)
    schema_notes = ensure_lang_pack_schema(notion, data_source_id)
    rows = pages_to_rows(iter_data_source_pages(notion, data_source_id))
    plan = plan_pull_from_notion(data, rows)
    result = NotionSyncResult(plan=plan, warnings=schema_notes + list(plan.warnings))

    if not write:
        return result

    rendered = render_tone_file(data, plan.updated_values)
    target = output_path or tone_path
    target.write_text(rendered, encoding="utf-8")
    parse_tone_file(target)  # load 검증
    plan.output_path = target
    plan.warnings.insert(0, f"저장 완료: {target}")
    result.warnings = list(plan.warnings)
    result.updated = len(plan.changes)
    return result


def format_notion_diff_report(
    plan: ImportPlan,
    tone_path: pathlib.Path,
    database_id: str,
) -> str:
    return format_diff_report(
        plan,
        tone_path,
        database_id,
        source_name="Notion",
    )


@dataclass
class KeyCompareResult:
    local_keys: set[str]
    notion_keys: set[str]
    notion_only: list[str]
    local_only: list[str]
    both: list[str]
    warnings: list[str] = field(default_factory=list)


def compare_tone_keys(
    tone_path: pathlib.Path,
    *,
    token: str,
    database_id: str,
) -> KeyCompareResult:
    """로컬 LANG_PACK 키와 Notion DB 키를 비교합니다."""
    data = parse_tone_file(tone_path)
    local_keys = {entry.key for entry in data.entries}

    notion = _client(token)
    data_source_id = resolve_data_source_id(notion, database_id)
    key_list = pages_to_keys(iter_data_source_pages(notion, data_source_id))

    warnings: list[str] = []
    notion_keys: set[str] = set()
    seen: set[str] = set()
    duplicates: set[str] = set()
    for key in key_list:
        if key in seen:
            duplicates.add(key)
        seen.add(key)
        notion_keys.add(key)
    if duplicates:
        warnings.append(
            f"Notion에 중복 키 {len(duplicates)}개: "
            + ", ".join(sorted(duplicates)[:10])
            + ("..." if len(duplicates) > 10 else "")
        )

    notion_only = sorted(notion_keys - local_keys)
    local_only = sorted(local_keys - notion_keys)
    both = sorted(local_keys & notion_keys)
    return KeyCompareResult(
        local_keys=local_keys,
        notion_keys=notion_keys,
        notion_only=notion_only,
        local_only=local_only,
        both=both,
        warnings=warnings,
    )


def format_key_compare_report(
    result: KeyCompareResult,
    tone_path: pathlib.Path,
    database_id: str,
) -> str:
    lines = [
        f"키 비교: {tone_path}",
        f"Notion DB: {database_id}",
        f"로컬 키: {len(result.local_keys)} / Notion 키: {len(result.notion_keys)} / 공통: {len(result.both)}",
        "",
        f"=== Notion에만 있음 ({len(result.notion_only)}) ===",
    ]
    if result.notion_only:
        lines.extend(result.notion_only)
    else:
        lines.append("(없음)")

    lines.extend(
        [
            "",
            f"=== 로컬에만 있음 ({len(result.local_only)}) ===",
        ]
    )
    if result.local_only:
        lines.extend(result.local_only)
    else:
        lines.append("(없음)")

    if result.warnings:
        lines.extend(["", "=== 경고 ==="])
        lines.extend(result.warnings)

    lines.append("")
    return "\n".join(lines)
