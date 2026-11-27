# 언어팩 엑셀 변환 도구

`tone/*.py` 안의 `LANG_PACK`을 고객이 편집할 수 있는 4열 엑셀로보내고, 수정된 엑셀을 다시 `.py`에 반영하는 도구입니다.

## 준비

```powershell
pip install -r requirements-dev.txt
```

`openpyxl`만 추가로 필요합니다. 봇 런타임(`requirements.txt`)에는 포함되지 않습니다.

## 파일 구성

| 파일 | 설명 |
|------|------|
| `tools/export_lang_pack.py` | `.py` → 엑셀 export |
| `tools/import_lang_pack.py` | 엑셀 → `.py` import (diff 리포트 포함) |
| `tools/lang_pack_xlsx_lib.py` | 공통 라이브러리 |
| `tools/tone_notion.py` | `.py` ↔ Notion DB (`키`/`대사`) — [LANG_PACK_NOTION.md](LANG_PACK_NOTION.md) |

## 엑셀 형식 (`팩` 시트)

1행은 헤더이며, 2행부터 데이터입니다.

| 열 | 이름 | 설명 |
|----|------|------|
| A | 변수명 | `PARM_*` 또는 `LANG_PACK` 키. **수정 금지** |
| B | 설명 | 항목 설명 (참고용) |
| C | 예시 값 | 현재 `.py`에 들어 있는 값 |
| D | 설정할 값 | 고객이 입력하는 새 값 |

추가로 `원시데이터` 시트가 export 시 자동 생성됩니다. 키·값 참조용이며 import에는 사용하지 않습니다.

### 행 순서

1. `PARM_*` 메타데이터 (상단, 수정 금지 예정)
2. `LANG_PACK` 항목 (`.py`에 있는 순서 그대로)

## 워크플로

### 1. 엑셀 생성 (export)

```powershell
cd KumaBot\tools
python export_lang_pack.py ..\tone\addon_0002.py -o "..\..\메냐 유나봇 언어팩.xlsx"
```

`-o`를 생략하면 `tone/addon_0002_langpack.xlsx`로 저장됩니다.

### 2. 고객 편집

- **D열(설정할 값)**만 수정합니다.
- **A열(변수명)**은 절대 바꾸지 않습니다.
- **PARM_* 행**은 수정하지 않습니다. (엑셀에서 해당 영역 보호 설정 권장)
- `{author}`, `{day_count}` 같은 플레이스홀더는 필요한 경우 그대로 둡니다.

### 3. 반영 전 diff 확인 (권장)

```powershell
python import_lang_pack.py ..\tone\addon_0002.py "..\..\메냐 유나봇 언어팩.xlsx" --dry-run
```

파일은 변경하지 않고, 어떤 키가 어떻게 바뀌는지 리포트만 출력합니다.

### 4. `.py`에 반영 (import)

```powershell
# 다른 파일로 출력 (권장)
python import_lang_pack.py ..\tone\addon_0002.py "..\..\메냐 유나봇 언어팩.xlsx" -o ..\tone\addon_0002_new.py

# 원본 덮어쓰기
python import_lang_pack.py ..\tone\addon_0002.py "..\..\메냐 유나봇 언어팩.xlsx"
```

import 실행 시 **변경 diff 리포트**가 콘솔에 자동으로 출력됩니다.

### 5. diff 리포트 파일로 저장

```powershell
python import_lang_pack.py ..\tone\addon_0002.py "..\..\메냐 유나봇 언어팩.xlsx" --dry-run --diff-out ..\tone\addon_0002.diff.txt
```

## 값 반영 규칙

각 행마다 아래 순서로 적용됩니다.

1. **D열(설정할 값)**에 내용이 있으면 → D열 사용
2. D열이 비어 있으면 → **C열(예시 값)** 사용
3. C·D 모두 비어 있으면 → 기존 `.py` 값 유지
4. `#VALUE!` 등 엑셀 오류 셀 → 무시 (위 규칙대로 처리)

### PARM 메타데이터

`PARM_`으로 시작하는 행은 import 시 **항상 무시**됩니다.  
엑셀에서 PARM을 수정해도 `.py`의 PARM 값은 바뀌지 않습니다.

## 특수 타입

| 타입 | 예시 키 | 엑셀 입력 형식 |
|------|---------|----------------|
| 문자열 | 대부분의 키 | 그대로 입력 |
| 불리언 | `expFE_voice_duration_form` | `TRUE` / `FALSE` (또는 `True` / `False`) |
| 리스트 | `expFE_res_daily` | Python 리스트 문자열 |

`expFE_res_daily` 예시:

```text
[[1, '{author}님, 오늘도 오셨네요!', '자동으로 {day_count}번째 출석이 완료되었어요.'], [None, '{author}님, 오랜만이네요.', '...']]
```

마지막 행의 기준일수는 `None`으로 두면 “그 외 모든 경우”에 해당합니다.

## diff 리포트 예시

```
=== 언어팩 변경 diff 리포트 ===
기준 .py : C:\...\tone\addon_0002.py
엑셀     : C:\...\메냐 유나봇 언어팩.xlsx
변경 키  : 2개

[1] expFE_group_name  ← D열(설정할 값)
  - 이전: 활동 경험치 기능 관련 명령어에요. (현황, 랭킹 등)
  + 이후: 테스트 그룹명

[2] bot_name  ← D열(설정할 값)
  - 이전: 유나봇
  + 이후: 메냐봇

--- 참고 ---
엑셀에 없는 LANG_PACK 키 10개 — 기존 .py 값 유지
```

## import 옵션 요약

| 옵션 | 설명 |
|------|------|
| `--dry-run` | 검증·diff만 수행, `.py` 미변경 |
| `--diff-out PATH` | diff 리포트를 텍스트 파일로 저장 |
| `--no-diff` | 콘솔 diff 출력 생략 |
| `-o PATH` | 출력 `.py` 경로 지정 |

## 주의사항

- 엑셀에만 있고 `.py`에 없는 키는 **무시**됩니다.
- `.py`에만 있고 엑셀에 없는 키는 **기존 값 유지**됩니다. (경고로 표시)
- import 후 생성된 `.py`는 자동으로 `importlib` 로드 검증을 거칩니다.
- `.py` 안의 주석·섹션 헤더(`##### ...`)는 유지한 채 **값만** 갱신됩니다.

## 기존 엑셀과 동기화

정리 중인 엑셀에 키가 빠져 있을 수 있습니다. 전체 키를 맞추려면:

1. `export_lang_pack.py`로 새 엑셀 생성
2. 기존 엑셀의 **B열(설명)·D열(설정할 값)**을 복사
3. `--dry-run`으로 diff 확인 후 import

## 반영 후

언어팩 변경을 봇에 적용하려면 `reload_tone.sh`를 실행하거나 봇을 재시작합니다.
