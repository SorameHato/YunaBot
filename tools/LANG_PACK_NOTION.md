# 언어팩 Notion 동기화 도구

`tone/*.py`의 `LANG_PACK` **키·대사만** Notion 데이터베이스와 주고받습니다.  
설명·스크린샷은 Notion 페이지 본문에 직접 작성하고, 동기화는 건드리지 않습니다.

## 준비

```powershell
pip install -r requirements-dev.txt
```

`notion-client`가 필요합니다. (엑셀 도구용 `openpyxl`과 함께 들어 있습니다.)

### 1. Notion Integration

1. [Notion Integrations](https://www.notion.so/my-integrations)에서 Internal Integration을 만듭니다.
2. 토큰을 복사합니다.
3. 작업할 페이지(또는 DB)에서 **··· → Connect to → (integration)** 으로 연결합니다.

### 2. 설정 파일

```powershell
copy tools\notion_config.example.json tools\notion_config.json
```

`tools/notion_config.json` 예시:

```json
{
  "token": "ntn_xxxxxxxx",
  "database_id": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "databases": {
    "0002": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }
}
```

- `token` / `database_id` 대신 환경변수 `NOTION_TOKEN`, `NOTION_DATABASE_ID`도 가능합니다.
- `databases.0002`처럼 애드온별 DB를 두면, `tone/addon_0002.py` push/pull 시 파일명으로 자동 선택됩니다.
- `notion_config.json`은 `.gitignore` 대상입니다.
- 설정에는 **브라우저 URL의 database ID**를 넣으면 됩니다. 도구가 Notion API(2025-09-03)용 `data_source_id`로 자동 변환합니다.

## DB 스키마

| 속성 | 타입 | 역할 |
|------|------|------|
| `키` | Title | `LANG_PACK` 키. **수정 금지** |
| `대사` | Text (rich_text) | 고객이 편집하는 값 |

페이지 **본문**에는 설명·이미지를 자유롭게 넣으면 됩니다. push/pull은 속성만 읽습니다.

속성이름을 바꾸지 마세요. (`키`, `대사` 고정)

push/pull 시 스키마를 확인합니다. `Name`만 있는 DB면 `키`로 바꾸고 `대사` 열을 자동 추가합니다.
(`init`으로 만든 DB도 Notion API 변경으로 속성이 빠졌을 수 있어, 첫 push에서 보정합니다.)

### DB 자동 생성 (선택)

빈 상위 페이지에 DB를 만들 때:

```powershell
cd KumaBot\tools
python tone_notion.py init --parent-page-id "<PAGE_ID>" --title "아메 언어팩"
```

출력된 database id를 `notion_config.json`에 넣고, Integration을 그 DB에 Connect 하세요.

수동으로 만들 때도 Title=`키`, Text=`대사` 두 속성만 있으면 됩니다.

## 워크플로

### 1. .py → Notion (최초 / 재배포)

```powershell
cd KumaBot\tools
python tone_notion.py push ..\tone\addon_0002.py
```

- 없는 키 → 새 행 생성 (`키` + `대사`)
- 있는 키 → **`대사`만** `.py` 값으로 덮어씀 (본문의 설명·사진은 유지)

이미 고객이 Notion에서 `대사`를 고친 뒤, `.py`에 새 키만 추가하고 싶을 때:

```powershell
python tone_notion.py push ..\tone\addon_0002.py --create-only
```

쓰기 전에 개수만 보려면 `--dry-run`.

### 2. Notion에서 편집

- **`대사` 속성**만 수정합니다.
- **`키`는 바꾸지 않습니다.**
- 설명·스크린샷은 각 행을 연 뒤 페이지 본문에 작성합니다.
- 리스트 키(`expFE_res_daily` 등)는 Python 리스트 문자열 형식입니다.

```text
[[1, '{author}님, 오늘도 오셨네요!', '자동으로 {day_count}번째 출석이 완료되었어요.'], [None, '{author}님, 오랜만이네요.', '...']]
```

불리언은 `TRUE` / `FALSE`.

### 3. Notion → .py (반영 전 diff)

```powershell
python tone_notion.py pull ..\tone\addon_0002.py --dry-run
```

### 4. .py에 반영

```powershell
# 다른 파일로 출력 (권장)
python tone_notion.py pull ..\tone\addon_0002.py -o ..\tone\addon_0002_new.py

# 원본 덮어쓰기
python tone_notion.py pull ..\tone\addon_0002.py
```

`.py`의 주석·섹션은 유지되고 **값만** 바뀝니다.  
`PARM_*` 메타데이터는 Notion에 올리지 않으며 pull 대상도 아닙니다.

## 동기화 규칙 요약

| 방향 | 동작 |
|------|------|
| push | `.py`의 각 `LANG_PACK` 키 → Notion `키`/`대사`. 본문 미변경 |
| pull | Notion `대사` → 동일 키의 `.py` 값. 설명/본문 무시 |
| Notion에만 있는 키 | 무시 (경고) |
| `.py`에만 있는 키 | pull 시 기존 값 유지 (경고). push 시 새 행 생성 |

## 파일 구성

| 파일 | 설명 |
|------|------|
| `tools/tone_notion.py` | CLI (`init` / `push` / `pull`) |
| `tools/lang_pack_notion_lib.py` | Notion API 동기화 |
| `tools/lang_pack_xlsx_lib.py` | `.py` 파싱·렌더링 재사용 |
| `tools/notion_config.example.json` | 설정 예시 |
| `tools/LANG_PACK_NOTION.md` | 이 문서 |

엑셀 변환은 `LANG_PACK_XLSX.md`를 참고하세요. 두 도구는 같은 `.py` 파서/렌더러를 공유합니다.

## 주의사항

- Notion API 속도 제한 때문에 키가 많으면 push에 시간이 걸릴 수 있습니다.
- `대사`는 rich_text 속성 한계가 있어 매우 긴 값은 피하세요. (일반 대사·리스트 repr은 문제 없음)
- pull 후 봇에 적용하려면 tone reload 또는 봇 재시작이 필요합니다.
