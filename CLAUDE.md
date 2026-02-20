# CLAUDE.md — 재무제표 국문/영문 대사 웹앱 설계문서

> Claude Code가 이 프로젝트를 작업할 때 반드시 이 문서를 우선 참조할 것.
> 이 문서는 **현재 구현된 코드 상태**를 기준으로 작성되었음 (2026-02 기준).

---

## 1. 프로젝트 개요

### 목적
국문 재무제표(DSD 양식)와 영문 재무제표(Word 또는 PDF)를 업로드하면,
**재무제표 본문 4종(FS)** 및 **주석(Note) 전체**를 국문↔영문 대사(Reconciliation)하여
Excel 파일로 출력하는 웹 애플리케이션.

### 핵심 워크플로우
```
[사용자]
  ↓ 국문 DSD 파일 + 영문 재무제표 파일(Word .docx 또는 PDF .pdf) 업로드
[FastAPI 서버]
  ↓ DSD → XML 파싱 → LLM으로 FS 4종 + 주석 전체 추출 (병렬)
  ↓ 영문 문서 → 포맷 자동 감지 → FS 4종 + Note별 raw_text 추출 (병렬)
  ↓ 번호 기반 주석 매핑 (불일치 시 LLM 보조) + FS 타입 직접 매핑
  ↓ LLM이 국문 구조(앵커)를 들고 영문 원문 전체를 직접 읽으며 대사
  ↓ 수치 3-scale 일치 판정(×1 / ×1,000 / ×1,000,000) + 신뢰도 스코어 산출
  ↓ Excel 파일 생성 (Summary + FS 4종 시트 + 주석 시트)
[사용자]
  ↓ Excel 다운로드
```

---

## 2. 기술 스택

| 레이어 | 기술 | 비고 |
|--------|------|------|
| 백엔드 | Python 3.11+ / FastAPI | 비동기 처리 |
| 프론트엔드 | Next.js 14 (App Router) + TypeScript | PwC 디자인 시스템 적용 |
| 스타일링 | Tailwind CSS v3 + CSS Variables | PwC 컬러/타이포 토큰 |
| DSD 파싱 | 기존 `dsd_to_json.py` 재사용 | 독립 스크립트 → 모듈화 |
| 영문 문서 파싱 | `python-docx` (Word) + `pdfplumber` (PDF) | 포맷 자동 감지 |
| LLM 대사 | PwC Internal LLM (Bedrock Claude) | 사람처럼 직접 읽고 비교 |
| Excel 생성 | `openpyxl` | 서식/색상/스코어 표현 |
| 파일 처리 | `python-multipart` | 파일 업로드 |
| 환경변수 | `python-dotenv` | API 키 관리 |

---

## 3. 디렉토리 구조

```
project-root/
│
├── CLAUDE.md                    # 이 파일 (Claude Code 컨텍스트)
├── .env                         # API 키 (git 제외)
├── .gitignore
├── requirements.txt
│
├── app/
│   ├── main.py                  # FastAPI 앱 진입점
│   ├── config.py                # 환경변수, 상수 관리
│   │
│   ├── api/
│   │   └── routes.py            # POST /api/upload, GET /api/status/{id}, GET /api/download/{id}
│   │
│   ├── services/
│   │   ├── dsd_service.py       # DSD XML 파싱 + LLM 기반 FS/주석 추출
│   │   ├── en_doc_service.py    # 영문 문서 파싱 (Word/PDF), FS 섹션 추출
│   │   ├── mapping_service.py   # 주석/FS 국문↔영문 매핑
│   │   ├── reconcile_service.py # LLM 기반 대사 (KR-Anchor 방식)
│   │   └── excel_service.py     # Excel 출력 생성
│   │
│   ├── models/
│   │   ├── dsd_model.py         # DSDNote, DSDItem, DSDAmount (Pydantic)
│   │   ├── en_doc_model.py      # EnNote, EnDocument (Word/PDF 공통)
│   │   └── reconcile_model.py   # ReconcileResult, ReconcileItem, AmountMatch
│   │
│   └── utils/
│       ├── llm_client.py        # PwCLLMClient (BaseLLMClient 추상화)
│       ├── amount_utils.py      # 금액 정규화 + flatten_dict
│       └── job_store.py         # 임시 작업 상태 저장 (in-memory)
│
├── parsers/
│   └── dsd_to_json.py           # 기존 DSD→JSON 스크립트 (수정 금지)
│                                # process_dsd_to_json(dsd_path_str, output_json_str)
│
├── files/                       # 테스트용 파일 (git 제외, .gitignore에 등록)
│
├── temp/                        # 업로드/출력 임시파일 (git 제외)
│   ├── uploads/
│   └── outputs/
│
└── frontend/                    # Next.js 14 App
    ├── package.json
    ├── next.config.js           # /api/* → localhost:8000 프록시
    ├── tailwind.config.ts       # PwC 색상 토큰
    └── app/
        ├── layout.tsx           # PwC 헤더/푸터
        ├── page.tsx             # 메인 페이지
        ├── globals.css          # PwC CSS 변수
        ├── components/
        │   ├── Header.tsx
        │   ├── FileUploadZone.tsx
        │   ├── ProgressTracker.tsx
        │   ├── ProcessLog.tsx
        │   └── DownloadButton.tsx
        └── hooks/
            └── useReconcile.ts  # 업로드→폴링→다운로드 상태 관리
```

---

## 4. API 설계

### `POST /api/upload`
파일 업로드 및 처리 작업 시작.

**Request:** `multipart/form-data`
- `dsd_file`: 국문 DSD 파일 (`.dsd` — ZIP 내 XML 포함)
- `en_file`: 영문 재무제표 파일 (`.docx` 또는 `.pdf`)
- `llm_provider`: `"pwc"` (현재 PwC만 지원)

**Response:**
```json
{ "job_id": "uuid-v4", "status": "processing", "message": "작업이 시작되었습니다." }
```

---

### `GET /api/status/{job_id}`
```json
{ "job_id": "...", "status": "processing|completed|failed", "progress": 75, "step": "주석 매핑 중... (3/12)", "error": null }
```

### `GET /api/download/{job_id}`
완료된 Excel 파일 다운로드.
파일명: `reconciliation_{회사명}_{날짜}.xlsx`

---

## 5. 핵심 데이터 모델

### 설계 원칙 — 다차원 속성(Multi-Attribute) 구조
재무제표 금액 셀은 단순 당기/전기 외에 **행 레이블 + 복수 헤더 속성**의 조합으로 식별됨.
→ 고정 필드 대신 `attributes: dict[str, str]`로 모든 헤더 조합을 담는다.

### DSD 데이터 모델 (`app/models/dsd_model.py`)

```python
class DSDAmount(BaseModel):
    attributes: dict[str, str]   # 예: {"기간":"당기", "수준":"수준2"}
    value: float | None          # 원 단위로 정규화
    raw_text: str                # 원본 셀 텍스트

class DSDItem(BaseModel):
    item_id: int                 # 주석 내 순번 (0-based)
    label: str                   # 행 레이블 (합계/소계 포함)
    is_header_only: bool = False # 금액 없는 제목행 여부
    amounts: list[DSDAmount]
    unit: str = "원"
    raw_row: dict                # 원본 row (검증용)

class DSDNote(BaseModel):
    note_number: str             # "1", "15", "balance_sheet" (FS인 경우)
    note_title: str
    source_filename: str
    unit: str = "원"
    raw_paragraphs: list[str]
    items: list[DSDItem]
```

**FS 처리 시 `note_number = fs_type`:**
- `"balance_sheet"`, `"income_statement"`, `"equity_changes"`, `"cash_flow"`
- 별도 모델 없이 DSDNote 재사용

### 영문 문서 모델 (`app/models/en_doc_model.py`)

```python
class DocFormat(str, Enum):
    WORD = "word"
    PDF  = "pdf"

class EnNote(BaseModel):
    note_number: str              # "1", "15", "balance_sheet" (FS인 경우)
    note_title: str
    raw_text: str                 # 섹션 전체 원문 (LLM 탐색 재료)
    source_format: DocFormat
    page_range: tuple[int,int] | None

class EnDocument(BaseModel):
    filename: str
    format: DocFormat
    notes: list[EnNote]
    full_raw_text: str            # Note 분리 실패 시 fallback용
```

### 대사 결과 모델 (`app/models/reconcile_model.py`)

```python
class AmountMatch(BaseModel):
    amount_id: str               # "{item_id}_{amt_idx}"
    attributes_kr: dict[str, str]
    attributes_en: dict[str, str]
    value_kr: float | None       # 국문 금액 (원)
    value_en: float | None       # LLM이 찾은 영문 금액 (정규화 후)
    is_match: bool | None        # True/False/None(미발견)
    variance: float | None       # value_en - value_kr
    confidence: float
    found: bool
    llm_note: str | None

class ReconcileItem(BaseModel):
    item_id: int
    label_kr: str
    label_en: str | None
    is_header_only: bool
    amount_matches: list[AmountMatch]

class ReconcileResult(BaseModel):
    note_number_kr: str
    note_number_en: str | None
    note_title_kr: str
    note_title_en: str | None
    note_mapping_confidence: float
    items: list[ReconcileItem]

    @property
    def total_amounts(self) -> int: ...
    @property
    def matched_count(self) -> int: ...
    @property
    def match_rate(self) -> float: ...
```

---

## 6. 서비스 로직 상세

> **핵심 원칙 — "국문 앵커(KR-Anchor)" 방식**
>
> ❌ 기존 방식: 국문 숫자 추출 + 영문 숫자 추출 → 매칭 (구조 다르면 실패)
> ✅ 새 방식:  국문 구조화 → LLM이 영문 원문 전체를 직접 읽으며 대응 금액 탐색
>
> 재무제표 본문(FS) + 주석(Notes) 모두 동일한 방식으로 처리.

---

### 6-1. DSD 서비스 (`dsd_service.py`)

```
주요 공개 함수:
  parse_dsd_all(dsd_path, llm_client)
    → tuple[list[DSDNote], list[DSDNote]]  ← (statements, notes)

  parse_dsd_file(dsd_path, llm_client)
    → list[DSDNote]  ← 주석만 (backward compat)

처리 흐름:
1. dsd_to_json.py의 process_dsd_to_json() 호출 → raw JSON 생성
2. _extract_segments(): content를 {"type": "p"|"table", ...} 리스트로 변환
3. _llm_find_boundaries(): 단락 텍스트 목록을 LLM에 전달 → 주석/FS 경계 감지
   - 실패 시 _regex_find_boundaries() fallback (감사보고서 키워드 필터)
4. _find_fs_boundaries(): 주석 첫 경계 이전 세그먼트에서 FS 제목 regex 탐색
   _KR_FS_PATTERNS = {
     "balance_sheet":    r"재\s*무\s*상\s*태\s*표",
     "income_statement": r"(?:포괄\s*)?손\s*익\s*계\s*산\s*서",
     "equity_changes":   r"자\s*본\s*변\s*동\s*표",
     "cash_flow":        r"현\s*금\s*흐\s*름\s*표",
   }
5. asyncio.gather(*note_tasks, *fs_tasks) — 병렬 LLM 추출
   - 주석: _llm_parse_note()
   - FS:   _llm_parse_fs()
   - 세마포어 10으로 동시 호출 제한

LLM 응답 형식 (주석/FS 공통):
{
  "note_number": "15",
  "note_title": "...",
  "unit": "천원",
  "items": [
    {
      "item_id": 0,
      "label": "매출채권",
      "is_header_only": false,
      "amounts": [
        {"attributes": {"기간": "당기"}, "value": 1234567000, "raw_text": "1,234,567"}
      ]
    }
  ]
}
```

**주의:**
- `dsd_to_json.py` 원본 수정 금지
- FS의 `note_number`는 `fs_type` 문자열 ("balance_sheet" 등)

---

### 6-2. 영문 문서 서비스 (`en_doc_service.py`)

```
주요 공개 함수:
  parse_en_file(file_path) → EnDocument         ← 주석 파싱
  parse_en_financial_statements(file_path)       ← FS 4종 파싱
    → dict[str, EnNote]  # {"balance_sheet": EnNote, ...}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[FS 파싱 — PDF (_parse_en_fs_pdf)]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
페이지 단위 감지 전략:
1. 각 페이지의 첫 6줄에서 FS 제목 패턴 탐색 (_EN_FS_PATTERNS)
2. FS 제목 + 재무 금액(7자리+) 동시 존재 → 실제 FS 페이지
   (금액 없는 페이지 = 목차/표지 추정 → 건너뜀)
3. Notes 제목 패턴(_NOTE_RE) 감지 페이지 → 수집 즉시 종료
4. FS/Notes 패턴 없는 페이지 → 현재 FS의 연속 페이지로 추가

영문 FS 제목 패턴 (_EN_FS_PATTERNS):
  balance_sheet:    r"statement[s]?\s+of\s+financial\s+position|balance\s+sheet"
  income_statement: r"statement[s]?\s+of\s+(?:profit|comprehensive\s+income|...)"
  equity_changes:   r"statement[s]?\s+of\s+changes\s+in\s+(?:equity|stockholders|...)"
  cash_flow:        r"statement[s]?\s+of\s+cash\s+flows?|cash\s+flow\s+statement"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[FS 파싱 — Word (_parse_en_fs_word)]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DOM 순서 순회, FS 제목 감지 후 수집.
Notes 섹션 제목(ABCTitle/Heading1 스타일 + Note 번호 패턴) 감지 시 즉시 종료.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[주석 파싱 — PDF (_parse_pdf)]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_NOTE_RE = r"^\s*(\d+)\.\s+([A-Z][^\n]{0,120})$"  ← 줄 시작 기준
Note가 3개 미만 → full_raw_text fallback

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[주석 파싱 — Word (_parse_word)]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3단계 계층적 감지:
  1차: ABCTitle/Heading1 스타일
  2차: regex (_WORD_NOTE_RE: "NOTE 1.", "1. General Information" 등)
  3차: bold 단락 + numbering.xml 파싱 (_compute_list_sequence)
       → Word 자동번호를 실제 순번으로 변환 (B-prefix fallback)

PDF 노이즈 제거:
  _PDF_HEADER_RE: "Notes to (the) Financial Statements" 반복 헤더 제거
  _PAGE_NUM_RE:   단독 페이지 번호 행 제거
  _FINANCIAL_AMOUNT_RE: 7자리+ 금액 패턴 (FS vs 목차 구분용)
```

---

### 6-3. 매핑 서비스 (`mapping_service.py`)

```
map_notes(kr_notes, en_doc, llm_client) → list[NoteMapping]
  1단계: 번호 기반 매핑 (confidence=1.0, method="number")
  2단계: LLM 의미 기반 매핑 (미매핑 항목, method="llm")
  3단계: full_raw_text fallback (Note 분리 실패 시, method="fallback")

map_financial_statements(kr_statements, en_statements) → list[NoteMapping]
  note_number = fs_type 직접 매핑 (LLM 불필요, method="type_match")

@dataclass NoteMapping:
  kr_note: DSDNote
  en_note: EnNote | None
  confidence: float
  method: str  # "number" | "llm" | "fallback" | "unmatched" | "type_match"
```

---

### 6-4. 대사 서비스 (`reconcile_service.py`) ★핵심★

```
reconcile_all(mappings, llm_client, progress_cb, warn_cb)
  → list[ReconcileResult]

MAX_CONCURRENT = 10 (세마포어)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[LLM 호출 구조]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
기본: _llm_single_call() — 전체 items를 1회 LLM 호출
Fallback: _llm_chunked_call() — CHUNK_ITEM_SIZE=3개 단위로 분할 반복

LLM 응답 형식 (JSON 배열):
[
  {
    "amount_id": "0_0",         ← "{item_id}_{amt_idx}"
    "en_label_for_row": "...",
    "en_attributes": {"period": "current"},
    "value_en": 1234567,        ← 영문 원문 숫자 그대로 (단위 변환 안 함)
    "confidence": 0.97,
    "found": true,
    "reasoning": "..."
  }
]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[수치 일치 판정 (_calc_match)]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
영문 단위가 국문과 다를 수 있으므로 3-scale 시도:
  scale ×1, ×1,000, ×1,000,000 중 tolerance 이내이면 is_match=True
  MATCH_TOLERANCE_ABS = 1.0 (1원)
  MATCH_TOLERANCE_RATIO = 0.0 (비율 허용 없음)

결과:
  is_match = True / False / None (found=false인 경우)
  variance = 정규화된 value_en - value_kr

주의: "일치" 판정은 코드가 계산 (LLM은 찾기만 함)
```

---

### 6-5. Excel 서비스 (`excel_service.py`)

**시트 구성 순서:**
```
Summary | Mapping_Log | Mismatches | FS_재무상태표 | FS_손익계산서 | FS_자본변동표 | FS_현금흐름표 | Note_01 | Note_02 | ...
```

**`generate_excel()` 시그니처:**
```python
async def generate_excel(
    results: list[ReconcileResult],         # 주석 대사 결과
    mappings: list[NoteMapping],            # 주석 매핑
    company_name: str,
    output_dir: Path,
    stmt_results: list[ReconcileResult] | None = None,  # FS 대사 결과
    stmt_mappings: list[NoteMapping] | None = None,     # FS 매핑
) -> Path
```

**Note/FS 시트 — Wide Format (다차원 속성):**
```
고정 열 A-D: 항목번호 | 국문레이블 | 영문레이블 | 평균신뢰도
동적 블록 (속성 수에 따라 가변):
  [속성1] [속성2] ... [국문금액] [영문금액] [차이] [일치] [신뢰도] [메모]
  → 한 행(DSDItem)의 모든 AmountMatch를 가로 방향으로 배치
  → 주석 내 최대 amounts 수 기준으로 열 수 고정 (부족한 셀은 공백)
```

**색상 코드:**
```python
C_MATCH     = "C6EFCE"  # 연초록 — 일치
C_MISMATCH  = "FFC7CE"  # 연빨강 — 불일치
C_NOT_FOUND = "D9D9D9"  # 회색 — 미발견
C_LOW_CONF  = "FFEB9C"  # 연노랑 — 신뢰도 < 0.8
C_HEADER    = "4472C4"  # 파랑 — 헤더
C_KR_COL    = "DCE6F1"  # 연청색 — 국문 열
C_EN_COL    = "E2EFDA"  # 연녹색 — 영문 열
```

**FS 시트명 매핑:**
```python
_FS_SHEET_NAMES = {
    "balance_sheet":    "FS_재무상태표",
    "income_statement": "FS_손익계산서",
    "equity_changes":   "FS_자본변동표",
    "cash_flow":        "FS_현금흐름표",
}
```

---

### 6-6. API 라우트 파이프라인 (`routes.py`)

```python
# Step 1: 파싱 3종 병렬
(dsd_result, en_doc, en_statements) = await asyncio.gather(
    parse_dsd_all(dsd_path, llm_client),      # (statements, notes)
    parse_en_file(en_path),                    # EnDocument (주석)
    parse_en_financial_statements(en_path),    # dict[str, EnNote] (FS)
)
kr_statements, kr_notes = dsd_result

# Step 2: 매핑
mappings     = await map_notes(kr_notes, en_doc, llm_client)
stmt_mappings = map_financial_statements(kr_statements, en_statements)

# Step 3: 대사 (FS + 주석 합산, 병렬 처리)
all_results = await reconcile_all(stmt_mappings + mappings, llm_client, ...)
stmt_results = all_results[:len(stmt_mappings)]
results      = all_results[len(stmt_mappings):]

# Step 4: Excel 생성
output_path = await generate_excel(
    results=results, mappings=mappings,
    stmt_results=stmt_results, stmt_mappings=stmt_mappings,
    company_name=company_name, output_dir=settings.outputs_dir,
)
```

**진행률 표시:**
```
5% → 파싱 시작 | 15% → 파싱 완료 | 20% → 매핑 시작
20~90% → 대사 (주석별 진행) | 95% → Excel 생성 | 100% → 완료
```

---

## 7. LLM 클라이언트 (`app/utils/llm_client.py`)

```python
class BaseLLMClient(ABC):
    @abstractmethod
    async def chat_json_async(messages) -> dict | list
    def chat_json(messages) -> dict | list
    def chat(messages, temperature) -> str

class PwCLLMClient(BaseLLMClient):
    # PwC Bedrock 엔드포인트 (OpenAI-compatible)
    # 재시도: 최대 5회, 지수 backoff (1→2→4→8초)
    # HTTP 429, 500-504 재시도 대상
    # max_tokens = 65536
    # JSON 응답 안전 파싱: ```json...``` 마크다운 자동 제거
    # 부분 응답 복구: _recover_partial_json_array()

def get_llm_client(provider: str = "pwc") -> BaseLLMClient:
    # 현재 "pwc"만 지원
    # Claude Direct API는 미구현 (향후 추가 예정)
```

**주의사항:**
- 모든 LLM 호출은 `get_llm_client().chat_json_async()` 경유
- API 키는 `.env`에서만 로드, 코드 하드코딩 금지
- `chat_json()` 사용 시 항상 try/except로 파싱 실패 처리

---

## 8. 프론트엔드 (`frontend/`)

### 현재 구현 상태
- **3단계 스텝 인디케이터**: 파일 업로드 → 처리 중 → 완료
- **FileUploadZone**: 국문(`.dsd`) / 영문(`.docx`, `.pdf`) 드래그앤드롭
- **ProgressTracker**: 진행률 + 현재 단계 텍스트
- **ProcessLog**: 처리 로그 실시간 표시
- **DownloadButton**: 완료 후 Excel 다운로드 활성화

### PwC 디자인 토큰
```css
--pwc-orange: #E8400C   /* Primary CTA */
--pwc-grey-90: #2D2D2D  /* 헤더 배경 */
--pwc-grey-20: #CCCCCC  /* 구분선 */
```

### 파일 업로드 레이블
```tsx
<FileUploadZone label="국문 재무제표" subLabel="국문 DSD 파일을 업로드하세요" accept=".dsd" />
<FileUploadZone label="영문 재무제표" subLabel="영문 Word 또는 PDF 파일을 업로드하세요" accept=".docx,.pdf" />
```

### API 프록시 (`next.config.js`)
```javascript
{ source: '/api/:path*', destination: 'http://localhost:8000/api/:path*' }
```

### 실행 방법
```bash
# 백엔드 (프로젝트 루트)
uvicorn app.main:app --reload --port 8000

# 프론트엔드
cd frontend && npm run dev  # localhost:3000
```

---

## 9. 환경변수 (`.env`)

```
# PwC Internal LLM
PwC_LLM_URL=https://genai-sharedservice-americas.pwcinternal.com/chat/completions
PwC_LLM_API_KEY=your_pwc_api_key_here
PwC_LLM_MODEL=bedrock.anthropic.claude-opus-4-6

# Claude Direct API (미구현 — 향후 추가 예정)
ANTHROPIC_API_KEY=sk-ant-your_key_here
ANTHROPIC_MODEL=claude-opus-4-6

# 앱 설정
MAX_FILE_SIZE_MB=50
TEMP_DIR=./temp
JOB_TTL_MINUTES=60
```

---

## 10. requirements.txt

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
python-docx>=1.1.0
pdfplumber>=0.10.0
openpyxl>=3.1.2
requests>=2.31.0
anthropic>=0.28.0
python-dotenv>=1.0.1
pydantic>=2.7.0
pydantic-settings>=2.2.0
aiofiles>=23.2.1
```

---

## 11. 주의사항 및 금지사항

### 절대 금지
- `parsers/dsd_to_json.py` 원본 로직 수정 금지 (래핑만 허용)
- `app/utils/llm_client.py`를 통하지 않은 직접 LLM 호출 금지
- temp/files 파일 git 커밋 금지
- API 키를 코드에 하드코딩 금지

### 모델 재사용 원칙
- FS도 DSDNote/EnNote/NoteMapping/ReconcileResult 기존 모델 100% 재사용
- `note_number = fs_type` ("balance_sheet" 등)으로 구분
- 새 모델 추가 없이 "특수 주석"처럼 처리

### 엣지케이스 반드시 처리
- Word 자동번호(numbering.xml) vs. 실제 텍스트 번호 구분 (B-prefix fallback)
- PDF 목차 페이지의 FS 제목 오감지 방지 (금액 존재 여부로 구분)
- 영문 Note 분리 실패 시 full_raw_text fallback 모드
- 대사 중 LLM 응답 부분 잘림 → `_recover_partial_json_array()` 복구
- 단위 불일치 (국문 천원 / 영문 KRW) → 3-scale 매칭으로 흡수

### 코딩 컨벤션
- 서비스 함수 기본 async
- 에러: FastAPI HTTPException
- 로그: Python logging (print 금지)
- 타입 힌트 필수 (Pydantic 모델 활용)

---

## 12. 구현 완료 현황

| 기능 | 상태 | 비고 |
|------|------|------|
| DSD 주석 파싱 | ✅ 완료 | LLM 기반, regex fallback |
| DSD FS 본문 파싱 | ✅ 완료 | parse_dsd_all() |
| 영문 PDF 주석 파싱 | ✅ 완료 | 페이지 단위 Note 분리 |
| 영문 PDF FS 파싱 | ✅ 완료 | 페이지 단위 감지 + 목차 구분 |
| 영문 Word 주석 파싱 | ✅ 완료 | 3단계 계층 감지 + numbering.xml |
| 영문 Word FS 파싱 | ✅ 완료 | Notes 경계 감지 시 종료 |
| 주석 매핑 (번호+LLM) | ✅ 완료 | |
| FS 매핑 (타입 직접) | ✅ 완료 | |
| 주석 대사 (LLM) | ✅ 완료 | 3-scale 단위 매칭 |
| FS 대사 (LLM) | ✅ 완료 | 주석과 동일 파이프라인 |
| Excel FS 시트 4종 | ✅ 완료 | |
| Excel Summary (FS+주석) | ✅ 완료 | |
| PwC LLM 클라이언트 | ✅ 완료 | 재시도 로직 포함 |
| Claude Direct API | ❌ 미구현 | 향후 추가 예정 |
| LLM 프로바이더 선택 UI | ❌ 미구현 | Claude API 구현 후 추가 예정 |

---

*이 문서는 실제 코드 상태와 동기화하여 유지할 것.*
*Claude Code는 매 작업 시작 시 이 파일을 먼저 읽을 것.*
