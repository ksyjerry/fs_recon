# CLAUDE.md — 재무제표 국문/영문 대사 웹앱 설계문서

> Claude Code가 이 프로젝트를 작업할 때 반드시 이 문서를 우선 참조할 것.

---

## 1. 프로젝트 개요

### 목적
국문 재무제표(DSD 양식 → JSON)와 영문 재무제표(Word 또는 PDF 파일)를 업로드하면,
주석(Note)별로 금액 및 내용을 대사(Reconciliation)하여 Excel 파일로 출력하는 웹 애플리케이션.

### 핵심 워크플로우
```
[사용자]
  ↓ 국문 DSD 파일 + 영문 재무제표 파일(Word .docx 또는 PDF .pdf) 업로드
  ↓ LLM 프로바이더 선택 (PwC AI / Claude API)
[FastAPI 서버]
  ↓ DSD → JSON 변환 (기존 dsd_to_json.py 활용)
  ↓ 영문 문서 → 포맷 자동 감지 후 Note별 raw_text 추출 (Word/PDF 공통)
  ↓ 주석번호 기반 국문↔영문 Note 매핑 (번호 불일치 시 LLM 보조)
  ↓ LLM이 국문 구조(앵커)를 들고 영문 원문 전체를 직접 읽으며 대사
  ↓ 수치 일치 여부 계산 + 신뢰도 스코어 산출
  ↓ Excel 파일 생성
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
| LLM 대사 | PwC Internal LLM / Anthropic Claude API | 사람처럼 직접 읽고 비교 |
| Excel 생성 | `openpyxl` | 서식/색상/스코어 표현 |
| 파일 처리 | `python-multipart` | 파일 업로드 |
| 환경변수 | `python-dotenv` | API 키 관리 |

---

## 3. 디렉토리 구조

```
project-root/
│
├── CLAUDE.md                    # 이 파일 (Claude Code 컨텍스트)
├── README.md
├── .env                         # ANTHROPIC_API_KEY 등 (git 제외)
├── .env.example
├── .gitignore
├── requirements.txt
│
├── app/
│   ├── main.py                  # FastAPI 앱 진입점
│   ├── config.py                # 환경변수, 상수 관리
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py            # /upload, /status/{job_id}, /download/{job_id}
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── dsd_service.py       # DSD 파싱 서비스 (기존 스크립트 래핑)
│   │   ├── en_doc_service.py    # 영문 문서 파싱 (Word/PDF 자동 감지, raw_text 추출)
│   │   ├── mapping_service.py   # 주석 단위 국문↔영문 매핑 (LLM)
│   │   ├── reconcile_service.py # LLM 기반 대사 (국문 구조 + 영문 원문 → LLM 판단)
│   │   └── excel_service.py     # Excel 출력 생성
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── dsd_model.py         # DSD JSON 데이터 모델 (Pydantic)
│   │   ├── en_doc_model.py      # 영문 문서 파싱 결과 모델 (Word/PDF 공통)
│   │   └── reconcile_model.py   # 대사 결과 모델
│   │
│   ├── utils/
│       ├── __init__.py
│       ├── llm_client.py        # LLM 클라이언트 팩토리 (PwC / Claude API 전환)
│       ├── amount_utils.py      # 금액 정규화 + flatten_dict (중첩 dict 평탄화)
│       └── job_store.py         # 임시 작업 상태 저장 (in-memory)
│
├── parsers/
│   └── dsd_to_json.py           # 기존 DSD→JSON 스크립트 (수정 최소화)
│                                # 핵심 함수: process_dsd_to_json(dsd_path_str, output_json_str)
│                                # 출력: List[{filename, content: List[{p}|{table}]}]
│
├── frontend/                    # Next.js 14 App (별도 패키지)
│   ├── package.json
│   ├── next.config.js           # API proxy → FastAPI (localhost:8000)
│   ├── tailwind.config.ts       # PwC 색상 토큰 커스터마이징
│   ├── tsconfig.json
│   ├── public/
│   │   └── pwc-logo.png         # 첨부된 PwC 로고 파일
│   └── src/
│       ├── app/
│       │   ├── layout.tsx       # 루트 레이아웃 (PwC 헤더/푸터 포함)
│       │   ├── page.tsx         # 메인 페이지 (업로드 + 진행상황)
│       │   └── globals.css      # PwC 디자인 토큰 CSS 변수
│       ├── components/
│       │   ├── Header.tsx              # PwC 스타일 상단 네비게이션
│       │   ├── FileUploadZone.tsx      # 드래그앤드롭 (.dsd / .docx / .pdf 허용)
│       │   ├── ProviderSelector.tsx    # LLM 선택 (PwC AI / Claude API)
│       │   ├── ProgressTracker.tsx     # 단계별 진행 상황 표시
│       │   └── DownloadButton.tsx      # 완료 후 Excel 다운로드
│       ├── hooks/
│       │   └── useReconcile.ts  # 업로드→폴링→다운로드 상태 관리 훅
│       └── lib/
│           └── api.ts           # FastAPI 백엔드 호출 함수 모음
│
└── temp/                        # 업로드/출력 임시파일 (git 제외)
    ├── uploads/
    └── outputs/
```

---

## 4. API 설계

### `POST /api/upload`
파일 업로드 및 처리 작업 시작.

**Request:** `multipart/form-data`
- `dsd_file`: 국문 DSD 파일 (`.dsd` — ZIP 내 XML 포함)
- `en_file`: 영문 재무제표 파일 (`.docx` 또는 `.pdf`, 포맷 자동 감지)
- `llm_provider`: `"pwc"` | `"claude"` (기본값: `"pwc"`)

**Response:**
```json
{
  "job_id": "uuid-v4",
  "status": "processing",
  "message": "작업이 시작되었습니다."
}
```

---

### `GET /api/status/{job_id}`
작업 진행 상태 폴링.

**Response:**
```json
{
  "job_id": "uuid-v4",
  "status": "processing | completed | failed",
  "progress": 75,
  "step": "주석 매핑 중... (3/12)",
  "error": null
}
```

---

### `GET /api/download/{job_id}`
완료된 Excel 파일 다운로드.

**Response:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
파일명: `reconciliation_{회사명}_{날짜}.xlsx`

---

## 5. 핵심 데이터 모델

### 설계 원칙 — 다차원 속성(Multi-Attribute) 구조

> 재무제표의 금액 셀은 단순히 "당기/전기"로만 구분되지 않는다.
> 하나의 금액은 **행 레이블 + 복수의 컬럼 헤더 속성**의 조합으로 식별된다.
>
> 예시:
> - 기간:    당기 / 전기
> - 만기:    단기(1년이내) / 장기(1년초과)
> - 공정가치 수준: Level 1 / Level 2 / Level 3
> - 잔액:    기초 / 기말 / 증가 / 감소
> - 구분:    유동 / 비유동
> - 측정:    취득원가 / 장부금액 / 공정가치
>
> 따라서 고정된 current_period/prior_period 필드 대신
> `attributes: dict[str, str]` 로 모든 헤더 조합을 담는다.

---

### DSD 데이터 모델 (`app/models/dsd_model.py`)

```python
class DSDAmount(BaseModel):
    """
    하나의 금액 셀 = 행 레이블 + 속성 조합으로 식별되는 단일 값
    
    예시 — 공정가치 테이블의 한 셀:
      attributes = {
        "기간":       "당기",
        "공정가치수준": "수준 2",
        "구분":       "금융자산"
      }
      value = 1234567.0
    
    예시 — 차입금 만기 분석:
      attributes = {
        "기간":   "당기",
        "만기":   "1년 이내",
        "종류":   "단기차입금"
      }
      value = 500000.0
    """
    attributes: dict[str, str]   # 컬럼 헤더 경로 전체 (flatten된 다차원 속성)
    value: float | None          # 정규화된 금액 (원 단위)
    raw_text: str                # 원본 셀 텍스트 (파싱 검증용)

class DSDItem(BaseModel):
    """
    테이블의 한 행 = 행 레이블 + 해당 행의 모든 금액 셀들
    
    예시 — "매출채권" 행:
      label = "매출채권"
      amounts = [
        DSDAmount(attributes={"기간":"당기"}, value=1234567),
        DSDAmount(attributes={"기간":"전기"}, value=987654),
      ]
    
    예시 — "파생상품자산" 행 (공정가치 테이블):
      label = "파생상품자산"
      amounts = [
        DSDAmount(attributes={"기간":"당기","수준":"수준1"}, value=0),
        DSDAmount(attributes={"기간":"당기","수준":"수준2"}, value=50000),
        DSDAmount(attributes={"기간":"당기","수준":"수준3"}, value=0),
        DSDAmount(attributes={"기간":"당기","수준":"합계"},  value=50000),
        DSDAmount(attributes={"기간":"전기","수준":"수준1"}, value=0),
        ...
      ]
    """
    item_id: int                 # 주석 내 순번 (0-based, LLM 응답 추적용)
    label: str                   # 행 레이블 (합계/소계/중간제목 포함)
    is_header_only: bool = False # 금액 없는 제목행 여부
    amounts: list[DSDAmount]     # 행의 모든 금액 셀 (속성 조합별)
    unit: str = "원"             # 주석 단위 (천원→원 변환 완료 후)
    raw_row: dict                # 원본 row dict (검증용)

class DSDNote(BaseModel):
    note_number: str             # "1", "15" 등 숫자만
    note_title: str              # 주석 제목
    source_filename: str         # 출처 XML 파일명
    unit: str = "원"             # 주석 전체 단위 (p태그에서 감지)
    raw_paragraphs: list[str]    # 주석 내 p태그 전체 (설명 텍스트 보관)
    items: list[DSDItem]         # 모든 행 (버리는 행 없음)
```

**다차원 헤더 → attributes 변환 전략 (dsd_service.py)**
```python
# dsd_to_json.py의 multirow header 출력 예시:
# {"당기": {"수준1": "100", "수준2": "200"}, "전기": {"수준1": "90", "수준2": "180"}}
#
# flatten_dict() 적용 후:
# {"당기.수준1": "100", "당기.수준2": "200", "전기.수준1": "90", "전기.수준2": "180"}
#
# 각 키를 "." 기준으로 split하여 attributes dict 구성:
# DSDAmount(attributes={"기간":"당기", "구분":"수준1"}, value=100.0)
# DSDAmount(attributes={"기간":"당기", "구분":"수준2"}, value=200.0)
#
# 속성 키 이름 정규화 (heuristic):
#   첫 번째 depth → 주로 "기간" (당기/전기)
#   두 번째 depth → 컬럼 의미에 따라 "수준", "만기", "구분" 등
#   → 정규화 실패 시 "col_0", "col_1" 등 인덱스 키로 fallback
#   → LLM이 속성명보다 속성값으로 판단하므로 키 이름 오류는 치명적이지 않음

LABEL_COLUMNS = ["계정과목", "항목", "구분", "내용", "과목", "종류", ""]
# ↑ 이 키를 가진 컬럼은 label로 처리, 나머지는 DSDAmount로 처리
```

---

### 영문 문서 모델 (`app/models/en_doc_model.py`) — Word/PDF 공통

```python
# 포맷 무관하게 동일한 모델 사용
# en_doc_service.py가 Word든 PDF든 이 모델로 변환해서 반환

from enum import Enum

class DocFormat(str, Enum):
    WORD = "word"
    PDF  = "pdf"

class EnNote(BaseModel):
    """
    영문 보고서의 주석 1개.
    숫자 추출/구조화 없음 — LLM이 읽을 원문 텍스트만 보존.
    """
    note_number: str              # "1", "15" 등 (감지 실패 시 "unknown_N")
    note_title: str               # Note 제목 (영문)
    raw_text: str                 # 섹션 전체 원문 텍스트 ← LLM 탐색의 핵심 재료
    source_format: DocFormat      # 원본 포맷 (word / pdf)
    page_range: tuple[int,int] | None  # PDF의 경우 페이지 범위 (디버깅용)

class EnDocument(BaseModel):
    """영문 보고서 전체"""
    filename: str
    format: DocFormat
    notes: list[EnNote]
    full_raw_text: str            # 문서 전체 텍스트 (주석 분리 실패 시 fallback용)
```

---

### 대사 결과 모델 (`app/models/reconcile_model.py`)

```python
class AmountMatch(BaseModel):
    """
    단일 속성 조합에 대한 대사 결과
    국문 DSDAmount 1개 ↔ LLM이 찾은 영문 금액 1개
    """
    attributes_kr: dict[str, str]    # 국문 속성 (예: {"기간":"당기","수준":"수준2"})
    attributes_en: dict[str, str]    # LLM이 판단한 영문 속성 (예: {"period":"current","level":"Level 2"})
    value_kr: float | None           # 국문 금액 (원)
    value_en: float | None           # LLM이 찾은 영문 금액
    is_match: bool | None            # True/False/None(미발견)
    variance: float | None           # value_en - value_kr
    confidence: float                # LLM 탐색 신뢰도 (0.0~1.0)
    found: bool                      # 영문에서 발견 여부
    llm_note: str | None             # LLM 메모

class ReconcileItem(BaseModel):
    """
    국문 DSDItem 1개(행)에 대한 전체 대사 결과
    해당 행의 모든 속성 조합(amounts)을 각각 대사
    """
    item_id: int                     # 국문 항목 순번
    label_kr: str                    # 국문 행 레이블
    label_en: str | None             # LLM이 찾은 대응 영문 레이블
    is_header_only: bool             # 제목행 여부 (금액 대사 불필요)
    amount_matches: list[AmountMatch] # 속성 조합별 대사 결과 리스트
    # ← 당기/전기가 각각 하나씩이면 len=2
    # ← 공정가치 3수준 × 당기/전기이면 len=6
    # ← 만기분석 4구간 × 당기/전기이면 len=8

class ReconcileResult(BaseModel):
    note_number_kr: str
    note_number_en: str | None
    note_title_kr: str
    note_title_en: str | None
    note_mapping_confidence: float
    items: list[ReconcileItem]
    
    # 요약 통계 (Excel Summary 시트용)
    @property
    def total_amounts(self) -> int:
        return sum(len(i.amount_matches) for i in self.items if not i.is_header_only)
    
    @property
    def matched_count(self) -> int:
        return sum(
            1 for i in self.items
            for m in i.amount_matches
            if m.is_match is True
        )
    
    @property
    def match_rate(self) -> float:
        return self.matched_count / self.total_amounts if self.total_amounts else 0.0
```

---

## 6. 서비스 로직 상세

> **핵심 원칙 — "국문 앵커(KR-Anchor)" 방식**
>
> ❌ 기존 방식: 국문 숫자 추출 + 영문 숫자 추출 → 매칭 (구조 다르면 실패)
> ✅ 새 방식:  국문 숫자 추출 → 항목별로 영문 전체를 LLM이 탐색 → 대사
>
> 사람이 대사하는 방식과 동일:
> "국문 주석 15에 '매출채권 합계 1,234,567천원'이 있다.
>  영문 Note 15 전체를 보고 이에 대응하는 숫자를 찾아라."

---

### 6-1. DSD 서비스 (`dsd_service.py`)
```
역할: dsd_to_json.py를 모듈로 import하여 raw JSON을 DSDNote 모델로 변환
주의: dsd_to_json.py 원본 코드 직접 수정 금지

[dsd_to_json.py 출력 구조 - raw]
[
  {
    "filename": "xxx.xml",          ← DSD 내부 XML 파일명 (여러 개일 수 있음)
    "content": [                    ← p태그와 table태그의 순서 보존 리스트
      {"p": "텍스트"},              ← 단락 텍스트 (주석 제목, 설명 등)
      {"table": [                   ← 테이블 (컬럼명은 중첩 dict 구조)
        {"계정과목": "현금", "당기": "1,000", "전기": "800"},
        ...
      ]},
      ...
    ]
  },
  ...
]

[dsd_service.py 처리 흐름]
1. process_dsd_to_json() 호출 → raw JSON 파일 생성
2. raw JSON 로드
3. 전체 content를 순차 탐색하여 주석 섹션 분리:
   - {"p": "주석 N. 제목"} 패턴 감지 → 새 주석 시작
   - 주석 패턴 예시: r'주석\s*(\d+)[.\s]*(.*)'
   - 이후 나오는 p/table 항목들을 해당 주석에 귀속
4. 각 주석의 모든 행을 최대한 보존하여 DSDItem 생성
   → 합계/소계/중간행 포함, 금액 없는 행도 label만으로 보관
5. DSDNote 리스트 반환

[주석 섹션 분리 주의사항]
- DSD XML은 여러 파일(filename)에 걸쳐 있을 수 있음
  → 모든 filename의 content를 순서대로 합쳐서 처리
- 주석 제목 패턴은 회사마다 다를 수 있으므로 유연하게 처리
  예: "주석 1.", "주석1.", "1. 회계정책" 등
- table의 컬럼 구조가 중첩 dict일 수 있음
  예: {"당기": {"금액": "1,000"}} ← multirow header 결과
  → amount_utils.py의 flatten_dict()로 평탄화 후 금액 추출

[DSDItem 추출 원칙 — 다차원 속성 전체 보존]
- 합계행 ("합 계", "소 계", "합계", "소계", "계") → 반드시 포함
- 금액이 없는 제목행 → is_header_only=True인 DSDItem으로 보관
- 모든 컬럼 헤더 경로를 attributes dict에 담아 DSDAmount 생성
- 버리는 셀/행 없음 — LLM이 맥락으로 판단하게 둠
- 테이블 하나에 컬럼이 N개면 한 행에서 DSDAmount N개 생성
```

### 6-1-1. Amount Utils (`amount_utils.py`)
```python
def flatten_dict(d: dict, sep: str = ".") -> dict:
    """
    중첩 dict를 평탄화.
    {"당기": {"금액": "1,000"}} → {"당기.금액": "1,000"}
    dsd_to_json.py의 multirow header 결과 처리용
    """

def parse_amount(text: str) -> float | None:
    """
    금액 문자열 → float 변환
    규칙:
    - 쉼표 제거: "1,234,567" → 1234567.0
    - 괄호 = 음수: "(1,234)" → -1234.0
    - "-" 단독 = None (해당 없음)
    - 빈 문자열 = None
    - 변환 불가 = None (로그 출력)
    """

def normalize_unit(amount: float, unit: str) -> float:
    """
    모든 금액을 "원" 단위로 통일
    "천원"   → amount * 1_000
    "백만원"  → amount * 1_000_000
    "천달러" 등 외화는 그대로 (별도 처리)
    """

def detect_unit_from_text(text: str) -> str:
    """
    텍스트에서 단위 감지
    "(단위: 천원)", "(Unit: KRW thousands)" 등 패턴 검색
    """
```

---

### 6-2. 영문 문서 서비스 (`en_doc_service.py`) — Word/PDF 통합 파서

```
역할: 업로드된 영문 파일의 포맷을 자동 감지하고 EnNote 목록으로 변환
      핵심 목표: 각 Note 섹션의 원문 텍스트를 최대한 온전히 보존
      숫자 추출/구조화 절대 금지 — 그것은 LLM의 역할

[포맷 자동 감지]
파일 확장자 우선, 실패 시 magic bytes로 판단:
  .docx → Word 파서
  .pdf  → PDF 파서
  그 외  → 에러 반환 (지원 포맷 안내)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Word 파서 — python-docx]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 문서의 단락(paragraph)과 테이블(table)을 DOM 순서대로 순회
2. 테이블 셀 내용도 텍스트로 플래트닝:
   행 구분: "\t".join(cells)  →  행들을 "\n"으로 연결
3. 전체 텍스트에서 Note 섹션 분리:
   패턴: r'(?i)(note\s*\d+[\.:—\-]?\s*.+?)(?=note\s*\d+|$)'
   또는 heading 스타일(Heading 1/2) 기반 분리 병행
4. 각 섹션 → EnNote(raw_text=섹션 전체 텍스트)

주의:
- 테이블의 merged cell(병합 셀)은 첫 번째 셀에만 텍스트, 나머지는 ""
  → 플래트닝 시 빈 셀도 탭으로 구분하여 열 위치 정보 보존
- 헤더/푸터 텍스트는 제외
- 페이지 번호 단락 제외 (숫자만 있는 짧은 단락)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[PDF 파서 — pdfplumber]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. pdfplumber로 페이지별 텍스트 추출:
   page.extract_text(x_tolerance=3, y_tolerance=3)
2. 테이블이 있는 페이지는 page.extract_tables()로 별도 추출:
   추출된 테이블을 텍스트로 변환: 셀을 탭으로, 행을 줄바꿈으로
   → 일반 텍스트와 합쳐 raw_text 구성
3. 전체 텍스트에서 Note 섹션 분리 (Word와 동일 패턴)
4. 각 섹션 → EnNote(raw_text=섹션 전체 텍스트, page_range=(시작,끝))

주의:
- 두 컬럼 레이아웃 PDF는 텍스트가 뒤섞일 수 있음
  → extract_text(layout=True) 옵션으로 레이아웃 보존 시도
- 하이픈으로 끊긴 단어 처리: "receiv-\nable" → "receivable"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Note 섹션 분리 공통 전략]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1차: 번호 패턴으로 분리
  r'(?i)^\s*note\s+(\d+)[\.\:\-—]?\s*(.*)$'  (줄 시작 기준)

2차: 1차 실패 시 전체 문서를 분리하지 않고
  full_raw_text에 전체 텍스트 보관
  → mapping_service에서 LLM이 Note 경계를 스스로 판단

분리된 Note가 3개 미만이면 2차 fallback 적용
```

---

### 6-3. 대사 서비스 (`reconcile_service.py`) — LLM 직접 판단 방식 ★핵심★

```
핵심 철학:
  ❌ 기계적 추출 방식: 국문 숫자 추출 → 영문 숫자 추출 → 매칭
     (구조 불일치, 합계 누락, 속성 미스매치로 다수 오류)

  ✅ LLM 직접 판단 방식: 국문 구조(앵커) + 영문 원문 전체 → LLM이 사람처럼 읽고 비교
     "국문 주석 15의 이 항목이 영문 Note 15의 어느 숫자와 같은가?"
     → LLM이 문맥, 위치, 레이블 의미를 종합해서 판단

전체 처리 흐름:
┌─────────────────────────────────────────────────────────────┐
│  [국문 DSDNote] + [영문 EnNote]  →  주석 쌍 매핑            │
│   (주석15 ↔ Note 15, 불일치 시 LLM이 제목으로 판단)          │
│                       ↓                                     │
│         매핑된 주석 쌍별 LLM 대사 루프                        │
│         (주석 1쌍 = LLM 1회 호출)                            │
└─────────────────────────────────────────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[LLM 호출 구조 — 주석 1쌍당 1회]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYSTEM:
  당신은 한국 Big4 회계법인의 시니어 감사 전문가입니다.
  국문 재무제표(DSD 기반)와 영문 재무제표를 대사(reconciliation)하는 업무를 수행합니다.
  
  규칙:
  1. 국문 항목 목록의 각 금액(amount_id별)에 대응하는 영문 금액을 영문 원문에서 찾으세요.
  2. 기계적 텍스트 매칭이 아닌, 회계 전문가로서 문맥과 의미를 이해하고 판단하세요.
  3. 영문에서 합계/소계 레이블이 없어도 숫자의 위치와 맥락으로 판단하세요.
  4. 다차원 속성(기간/만기/수준/잔액 등)을 고려해 어떤 열·행의 금액인지 파악하세요.
  5. 찾지 못하면 found=false로 명시하세요 (억지로 찾지 마세요).
  6. 반드시 JSON 배열만 반환하세요 (다른 텍스트, 마크다운 금지).

USER:
  ══ 국문 주석 정보 ══
  주석 번호: {note_number}
  주석 제목: {note_title}
  단위: {unit} (이미 원 단위로 정규화됨)

  국문 항목 목록 (구조화된 JSON):
  {dsd_items_json}
  ← 각 amount마다 amount_id, 행 레이블, 다차원 속성, 금액값 포함

  ══ 영문 Note 원문 전체 (가공 없이 그대로) ══
  {en_note.raw_text}
  ← Word/PDF에서 추출한 원문. 테이블은 탭/줄바꿈으로 구조 보존.

  위 영문 원문을 보고, 국문 항목의 각 amount_id별 대응 영문 금액을 찾아 JSON으로 반환하세요.

LLM 응답 형식 (JSON 배열):
[
  {
    "amount_id": "0_0",
    "en_label_for_row": "Forward exchange contracts — Assets",
    "en_attributes": {"period": "current", "type": "Notional amount"},
    "value_en": 500000,
    "confidence": 0.97,
    "found": true,
    "reasoning": "영문 테이블 3행 2열, 'Notional amount' 헤더 아래 당기 컬럼"
  },
  {
    "amount_id": "2_0",
    "en_label_for_row": null,
    "en_attributes": {"period": "current"},
    "value_en": 47000,
    "confidence": 0.88,
    "found": true,
    "reasoning": "합계 레이블 없이 테이블 마지막 행 숫자로 위치 판단"
  },
  {
    "amount_id": "1_3",
    "en_label_for_row": null,
    "en_attributes": {},
    "value_en": null,
    "confidence": 0.0,
    "found": false,
    "reasoning": "영문 보고서에 해당 속성 조합의 금액이 존재하지 않음"
  }
]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[대사 결과 처리 — LLM 응답 후]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LLM이 찾아온 value_en vs 국문 value_kr:
  - 수치 일치 판정: abs(value_kr - value_en) <= max(1, abs(value_kr) * 0.0001)
    (단위 반올림 허용 오차)
  - is_match = True / False / None (found=false인 경우)
  - variance = value_en - value_kr

주의: "일치"는 LLM이 판단하는 게 아니라 코드가 계산 (LLM은 찾기만, 비교는 코드)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[토큰 제한 대응 — 영문 원문이 너무 긴 경우]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

영문 Note raw_text가 4,000자 초과 시:
  전략 A (기본): 그대로 전송 — 최신 Claude/GPT-4는 128k+ 컨텍스트 지원
  전략 B (fallback): DSDItem을 청크(5개)로 나눠 여러 번 LLM 호출
                     각 청크마다 영문 원문 전체를 함께 전송

컨텍스트 한도 초과 에러 발생 시 전략 B 자동 적용
```

---

### 6-4. 매핑 서비스 (`mapping_service.py`) — 주석 단위 매핑

```
역할: 국문 DSDNote 목록 ↔ 영문 EnNote 목록을 주석 단위로 매핑
      (항목 레벨 매핑은 6-3 reconcile_service의 LLM이 담당)

1단계 — 번호 기반 매핑 (결정론적):
  "주석 15" ↔ "Note 15" → 자동 매핑, confidence=1.0

2단계 — 제목 기반 매핑 (LLM, 번호 불일치 시):
  국문 주석 제목 목록 + 영문 Note 제목 목록 → LLM이 의미 기반 매핑
  LLM 1회 호출로 전체 주석 매핑 완료

3단계 — 전체 문서 fallback (Note 분리 실패 시):
  en_doc.full_raw_text 전체를 영문 원문으로 사용
  LLM이 문서 내에서 스스로 Note 경계 파악

출력: List[Tuple[DSDNote, EnNote | None, confidence]]
  → EnNote가 None인 경우 = 영문 보고서에 대응 주석 없음
     Excel Mapping_Log에 "영문 미존재"로 기록
```

---

### 6-5. Excel 서비스 (`excel_service.py`)

**시트 구성:**

| 시트명 | 내용 |
|--------|------|
| `Summary` | 전체 대사 결과 요약 (주석별 일치율, 총 불일치/미발견 건수) |
| `Note_01`, `Note_02`, ... | 주석별 상세 대사 결과 (다차원 속성 포함) |
| `Mismatches` | 불일치 + 미발견 항목만 모아서 표시 |
| `Mapping_Log` | 주석 단위 매핑 신뢰도 로그 |

**셀 서식 규칙 (openpyxl):**

```python
# 색상 코드
COLOR_MATCH     = "C6EFCE"   # 연초록 — 일치
COLOR_MISMATCH  = "FFC7CE"   # 연빨강 — 불일치
COLOR_LOW_CONF  = "FFEB9C"   # 연노랑 — 신뢰도 낮음 (< 0.8)
COLOR_NOT_FOUND = "D9D9D9"   # 회색 — 영문 미발견
COLOR_HEADER    = "4472C4"   # 파랑 — 헤더
COLOR_KR_COL    = "DCE6F1"   # 연청색 — 국문 열 배경
COLOR_EN_COL    = "E2EFDA"   # 연녹색 — 영문 열 배경
COLOR_ATTR      = "FFF2CC"   # 연노랑 — 속성(dimensions) 열 배경

# 열 구성 (Note_XX 시트) — 다차원 속성 방식
#
# 고정 열 (항상 존재):
A: 항목번호 (item_id, 국문 행 순서)
B: 국문 레이블 (행 레이블, 합계/소계/제목행 포함)
C: 영문 레이블 (LLM이 매핑한 영문 행 레이블, 없으면 "Not found")
D: 항목 신뢰도 (%)
#
# 동적 속성 열 (해당 주석 테이블의 다차원 헤더 수에 따라 가변):
# 예시 — 단순 당기/전기 테이블:
E: 속성: 기간         (당기 / 전기)
F: 국문 금액
G: 영문 금액
H: 차이 (G-F)
I: 일치 (✓/✗/-)
J: 신뢰도(%)
K: LLM 메모
#
# 예시 — 공정가치 수준별 테이블 (당기 Level1/2/3 + 전기 Level1/2/3 = 6개 금액):
E:  속성: 기간        (당기)
F:  속성: 수준        (수준1)
G:  국문 금액
H:  영문 금액
I:  차이
J:  일치
K:  신뢰도
L:  속성: 기간        (당기)
M:  속성: 수준        (수준2)
N:  국문 금액
...  (수준3, 전기 수준1/2/3 반복)
#
# → 행 방향 펼치기 (wide format): 한 DSDItem(행)의 모든 AmountMatch를 가로로 배치
# → 속성 조합별로 "속성열들 + 국문금액 + 영문금액 + 차이 + 일치 + 신뢰도 + 메모" 블록 반복
# → 주석 내 모든 DSDItem의 최대 amounts 수를 기준으로 열 수 결정 (부족한 셀은 공백)
#
# 헤더 행 구성 (2행):
# 행1: "속성1" | "속성2" | "국문금액" | "영문금액" | "차이" | "일치" | "신뢰도" | "메모" (블록 반복)
# 행2: 각 속성의 값 범주 표시 (예: "기간: 당기/전기", "수준: L1/L2/L3")
```

## 7. 프론트엔드 — Next.js 14 + PwC 디자인 시스템

### 7-1. PwC 디자인 토큰 (`globals.css`)

```css
:root {
  /* PwC Brand Colors */
  --pwc-orange:     #E8400C;   /* Primary — CTA 버튼, 강조 */
  --pwc-orange-dk:  #C4380A;   /* Hover 상태 */
  --pwc-red:        #E0301E;   /* 오류, 불일치 강조 */
  --pwc-black:      #1A1A1A;   /* 본문 텍스트 */
  --pwc-grey-90:    #2D2D2D;   /* 헤더 배경 */
  --pwc-grey-70:    #4D4D4D;   /* 서브텍스트 */
  --pwc-grey-20:    #CCCCCC;   /* 구분선 */
  --pwc-grey-05:    #F5F5F5;   /* 카드 배경 */
  --pwc-white:      #FFFFFF;

  /* Semantic */
  --color-success:  #22A354;   /* 일치 항목 */
  --color-warning:  #F5A623;   /* 신뢰도 낮음 */
  --color-danger:   #E0301E;   /* 불일치 항목 */

  /* Typography */
  --font-display: 'PwC Helvetica Neue', 'Helvetica Neue', Helvetica, sans-serif;
  --font-body:    'PwC Helvetica Neue', 'Helvetica Neue', Helvetica, sans-serif;

  /* Spacing (8px grid) */
  --space-xs:  4px;
  --space-sm:  8px;
  --space-md:  16px;
  --space-lg:  24px;
  --space-xl:  40px;
  --space-2xl: 64px;
}
```

### 7-2. Tailwind 커스터마이징 (`tailwind.config.ts`)

```typescript
// CSS 변수를 Tailwind 유틸리티로 연결
colors: {
  'pwc-orange': 'var(--pwc-orange)',
  'pwc-red':    'var(--pwc-red)',
  'pwc-black':  'var(--pwc-black)',
  'pwc-grey': {
    90: 'var(--pwc-grey-90)',
    70: 'var(--pwc-grey-70)',
    20: 'var(--pwc-grey-20)',
    5:  'var(--pwc-grey-05)',
  }
}
```

### 7-3. 레이아웃 구조 (`layout.tsx`)

```
┌──────────────────────────────────────────────────────┐
│  [PwC Logo]    Financial Statement Reconciliation    │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │  ← 헤더: #2D2D2D 배경, 오렌지 하단 라인
├──────────────────────────────────────────────────────┤
│                                                      │
│  재무제표 국문/영문 대사 시스템                           │  ← Hero: 흰 배경, 큰 타이포
│  Korean-English Financial Statement Reconciliation   │
│                                                      │
├──────────────────────────────────────────────────────┤
│  [Step 1: 파일 업로드]  →  [Step 2: 처리 중]  →  [Step 3: 완료]  │  ← 스텝 인디케이터
├──────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌──────────────────────────┐   │
│  │  📄 국문 DSD 파일    │  │  📋 영문 재무제표 파일     │   │  ← 드래그앤드롭 카드
│  │  .dsd 파일 업로드    │  │  .docx 또는 .pdf 업로드   │   │     hover 시 오렌지 테두리
│  └─────────────────────┘  └──────────────────────────┘   │
│                                                      │
│              [  대사 시작  ]                          │  ← PwC 오렌지 버튼
├──────────────────────────────────────────────────────┤
│  처리 진행 상황                                        │  ← 처리 중일 때만 표시
│  ──────────────────────────────── 75%               │
│  ● DSD 파일 변환  ✓                                  │
│  ● Word 파싱      ✓                                  │
│  ● 주석 매핑      진행중... (9/12)                    │
│  ● Excel 생성     대기중                             │
└──────────────────────────────────────────────────────┘
│  Footer: © 2025 Samil PwC. All rights reserved.     │  ← #2D2D2D 배경
└──────────────────────────────────────────────────────┘
```

### 7-4. 컴포넌트 상세

**Header.tsx**
```
- 배경: pwc-grey-90 (#2D2D2D)
- 좌측: pwc-logo.png (높이 32px)
- 우측: 페이지 제목 텍스트 (흰색)
- 하단: 2px solid pwc-orange 라인 (PwC 시그니처 오렌지 바)
```

**FileUploadZone.tsx**
```
- 국문 영역: .dsd 파일만 허용
- 영문 영역: .docx 또는 .pdf 허용 (둘 다 동일 영역에 표시)
  업로드 후 포맷 배지 표시: [Word] 또는 [PDF]
- 기본: 흰 배경, 1px dashed #CCCCCC 테두리, 둥근 모서리
- Hover/Drag: 2px solid pwc-orange, 연한 오렌지 배경 (rgba(232,64,12,0.04))
- 업로드 완료: 초록 체크 아이콘 + 파일명 + 포맷 배지 표시
- 잘못된 포맷 업로드 시: 빨간 테두리 + 에러 메시지
```

**ProgressTracker.tsx**
```
- 4단계 수직 스텝 리스트
- 완료: 오렌지 체크 원형 아이콘
- 진행중: 애니메이션 스피너 (pwc-orange 색상)
- 대기: 회색 원형 아이콘
- 진행바: 상단 가로 프로그레스바 (pwc-orange fill)
```

**DownloadButton.tsx**
```
- 완료 전: 비활성 (회색, disabled)
- 완료 후: pwc-orange 배경, 흰 텍스트, 다운로드 아이콘
- Hover: pwc-orange-dk로 어두워짐
- 클릭: /api/download/{job_id} → Excel 파일 다운로드
```

### 7-5. 폴링 훅 (`useReconcile.ts`)
```typescript
// 상태: 'idle' | 'uploading' | 'processing' | 'completed' | 'failed'
// 업로드 완료 → job_id 저장 → 2초 인터벌로 GET /api/status/{job_id} 폴링
// completed → 인터벌 클리어, 다운로드 URL 활성화
// failed → 에러 메시지 표시, 재시도 버튼 활성화
// 컴포넌트 언마운트 시 인터벌 클리어 (메모리 누수 방지)
```

### 7-6. API 프록시 설정 (`next.config.js`)
```javascript
// Next.js → FastAPI 프록시 (CORS 우회)
async rewrites() {
  return [{ source: '/api/:path*', destination: 'http://localhost:8000/api/:path*' }]
}
```

### 7-7. 실행 방법
```bash
# 백엔드
cd app && uvicorn main:app --reload --port 8000

# 프론트엔드
cd frontend && npm run dev  # localhost:3000
```

---

## 8. 환경변수 (`.env`)

```
# PwC Internal LLM
PwC_LLM_URL=https://genai-sharedservice-americas.pwcinternal.com/chat/completions
PwC_LLM_API_KEY=your_pwc_api_key_here
PwC_LLM_MODEL=bedrock.anthropic.claude-opus-4-6

# Claude Direct API (Anthropic)
ANTHROPIC_API_KEY=sk-ant-your_key_here
ANTHROPIC_MODEL=claude-opus-4-6

# 앱 설정
MAX_FILE_SIZE_MB=50
TEMP_DIR=./temp
JOB_TTL_MINUTES=60
```

---

## 8-1. LLM 클라이언트 설계 — 멀티 프로바이더 (`app/utils/llm_client.py`)

### 설계 원칙
```
- 두 프로바이더(PwC / Claude API)를 동일한 인터페이스로 추상화
- 서비스 레이어(reconcile_service 등)는 어떤 클라이언트인지 몰라도 됨
- 프로바이더 선택은 요청 시점에 주입 (job 단위로 결정)
- 두 프로바이더 모두 chat() / chat_json() 동일 인터페이스 제공
```

```python
# app/utils/llm_client.py
import requests, json, anthropic
from abc import ABC, abstractmethod
from app.config import settings

# ─────────────────────────────────────────
# 추상 기반 클라이언트
# ─────────────────────────────────────────
class BaseLLMClient(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], temperature: float = 0.0) -> str:
        """messages: [{"role": "user"|"assistant"|"system", "content": "..."}]"""
        ...

    def chat_json(self, messages: list[dict]) -> dict | list:
        """JSON 응답 보장 버전. 마크다운 코드블록 자동 제거 + 파싱."""
        raw = self.chat(messages, temperature=0.0)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned.strip())


# ─────────────────────────────────────────
# 프로바이더 1: PwC Internal LLM
# ─────────────────────────────────────────
class PwCLLMClient(BaseLLMClient):
    """
    PwC 내부 엔드포인트 (OpenAI-compatible REST API)
    pwcllm.py의 로직을 클래스로 래핑
    """
    def __init__(self):
        self.url = settings.PwC_LLM_URL
        self.headers = {
            "Content-Type": "application/json",
            "api-key": settings.PwC_LLM_API_KEY
        }
        self.model = settings.PwC_LLM_MODEL

    def chat(self, messages: list[dict], temperature: float = 0.0) -> str:
        # system 메시지를 별도 처리 (PwC 엔드포인트 호환성)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature
        }
        resp = requests.post(
            self.url, headers=self.headers,
            data=json.dumps(payload), timeout=120
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ─────────────────────────────────────────
# 프로바이더 2: Claude Direct API (Anthropic)
# ─────────────────────────────────────────
class ClaudeDirectClient(BaseLLMClient):
    """
    Anthropic Python SDK 사용
    messages 형식은 PwCLLMClient와 동일하게 맞춤
    """
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.ANTHROPIC_MODEL

    def chat(self, messages: list[dict], temperature: float = 0.0) -> str:
        # system 메시지 분리 (Anthropic API는 system을 별도 파라미터로)
        system_msgs = [m["content"] for m in messages if m["role"] == "system"]
        user_msgs   = [m for m in messages if m["role"] != "system"]
        system_text = "\n".join(system_msgs) if system_msgs else None

        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": user_msgs,
            "temperature": temperature,
        }
        if system_text:
            kwargs["system"] = system_text

        resp = self.client.messages.create(**kwargs)
        return resp.content[0].text


# ─────────────────────────────────────────
# 팩토리 함수
# ─────────────────────────────────────────
LLMProvider = Literal["pwc", "claude"]

def get_llm_client(provider: LLMProvider) -> BaseLLMClient:
    """
    provider: "pwc" | "claude"
    요청마다 호출하여 job 단위로 프로바이더 전환 가능
    """
    if provider == "pwc":
        return PwCLLMClient()
    elif provider == "claude":
        return ClaudeDirectClient()
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
```

**주의사항:**
- `pwcllm.py` 원본 파일 수정 금지 (참고용으로만 사용)
- 모든 LLM 호출은 반드시 `get_llm_client(provider).chat()` 경유
- `chat_json()` 사용 시 항상 try/except로 파싱 실패 처리
- API 키는 절대 코드에 하드코딩 금지, `.env`에서만 로드
- provider 값은 API 요청 body에서 수신하여 job_store에 저장

---

## 8-2. 프로바이더 선택 — API 및 UI 연동

### 백엔드 API 변경 (`POST /api/upload`)

```python
# Request body 추가 필드
class UploadRequest:
    dsd_file:  UploadFile                              # 국문 DSD
    en_file:   UploadFile                              # 영문 재무제표 (Word/PDF 자동 감지)
    llm_provider: Literal["pwc", "claude"] = "pwc"    # 기본값: PwC

# job_store에 provider 저장
job_store[job_id] = {
    "status": "processing",
    "provider": llm_provider,   # ← 저장
    ...
}

# reconcile_service 호출 시 전달
client = get_llm_client(job["provider"])
await reconcile_service.run(dsd_notes, word_notes, llm_client=client)
```

### 프론트엔드 UI (`FileUploadZone.tsx` 또는 별도 `ProviderSelector.tsx`)

```
┌──────────────────────────────────────────┐
│  LLM 선택                                 │
│                                          │
│  ◉  PwC AI          ○  Claude API        │
│     (내부 엔드포인트)    (Anthropic 직접)  │
│                                          │
│  ⚠ Claude API 선택 시 Anthropic 요금 발생  │
└──────────────────────────────────────────┘
```

**UI 구현 상세:**
```typescript
// components/ProviderSelector.tsx
type LLMProvider = "pwc" | "claude";

// 라디오 버튼 2개: PwC AI / Claude API
// 선택값을 useReconcile 훅에 전달
// 업로드 FormData에 llm_provider 필드 포함

// PwC 스타일: 선택된 옵션 = 오렌지 테두리 + 오렌지 라디오 버튼
// 비선택: 회색 테두리
// 기본값: "pwc"
```

**useReconcile.ts 수정:**
```typescript
// provider 상태 추가
const [provider, setProvider] = useState<"pwc" | "claude">("pwc");

// 업로드 시 FormData에 포함
formData.append("llm_provider", provider);
```

---

## 9. requirements.txt

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
python-docx>=1.1.0           # Word (.docx) 파싱
pdfplumber>=0.10.0           # PDF 텍스트/테이블 추출
openpyxl>=3.1.2
requests>=2.31.0
anthropic>=0.28.0            # Claude Direct API (ClaudeDirectClient용)
python-dotenv>=1.0.1
pydantic>=2.7.0
pydantic-settings>=2.2.0
aiofiles>=23.2.1
```

## 9-1. frontend/package.json (주요 의존성)

```json
{
  "dependencies": {
    "next": "14.x",
    "react": "^18",
    "react-dom": "^18",
    "typescript": "^5"
  },
  "devDependencies": {
    "tailwindcss": "^3",
    "autoprefixer": "^10",
    "postcss": "^8",
    "@types/react": "^18",
    "@types/node": "^20"
  }
}
```

---

## 10. 개발 순서 (Claude Code 작업 지시 순서)

```
Phase 1 — 기반 구조
  1. 디렉토리 구조 생성 및 빈 파일 초기화
  2. config.py, main.py (FastAPI 기본 설정)
  3. Next.js 프로젝트 초기화 (npx create-next-app frontend --typescript --tailwind)
     → pwc-logo.png를 frontend/public/ 에 복사
     → globals.css에 PwC 디자인 토큰 CSS 변수 설정
     → tailwind.config.ts에 PwC 색상 토큰 등록

  3. dsd_to_json.py 모듈화 (dsd_service.py 래핑)

Phase 2 — 파싱
  4. en_doc_service.py 구현 (Word + PDF 통합, 포맷 자동 감지)
  5. amount_utils.py 구현 (금액 정규화, flatten_dict)
  6. 파싱 단위 테스트 (샘플 Word/PDF 파일로 raw_text 추출 검증)

Phase 3 — 매핑 & 대사
  7. mapping_service.py 구현 (번호 기반 → LLM 기반)
  8. reconcile_service.py 구현 (금액 대사 로직)

Phase 4 — 출력
  9. excel_service.py 구현 (서식 포함)

Phase 5 — API & UI
  10. routes.py 구현 (비동기 처리, 폴링)
  11. job_store.py 구현
  12. Next.js 컴포넌트 구현 순서:
      a. globals.css + tailwind.config.ts (PwC 디자인 토큰)
      b. Header.tsx (PwC 로고 + 오렌지 하단 바)
      c. FileUploadZone.tsx (드래그앤드롭)
      d. ProgressTracker.tsx (4단계 스텝)
      e. DownloadButton.tsx
      f. useReconcile.ts 훅 (폴링 로직)
      g. page.tsx 조립 + layout.tsx 마무리

Phase 6 — 통합 테스트
  13. 실제 DSD + 영문 Word 파일로 End-to-End 테스트
  14. 실제 DSD + 영문 PDF 파일로 End-to-End 테스트
  15. 엣지케이스 처리 (주석 번호 불일치, 단위 혼용, 2컬럼 PDF 레이아웃)
```

---

## 11. 주의사항 및 금지사항

### 절대 금지
- `parsers/dsd_to_json.py` 원본 로직 수정 금지 (래핑만 허용)
- `app/utils/llm_client.py`를 통하지 않은 직접 LLM 호출 금지
- temp 파일 영구 보관 금지 (TTL 후 자동 삭제)
- API 키를 코드에 하드코딩 금지

### 엣지케이스 반드시 처리
- 영문 파일이 Word(.docx)인 경우와 PDF(.pdf)인 경우 모두 정상 처리
- 영문 문서에 테이블 없이 텍스트만 있는 주석
- 국문과 영문의 주석 번호 체계가 다른 경우
- 금액 단위가 섞인 경우 (일부는 천원, 일부는 백만원)
- DSD 파싱 실패 시 사용자에게 명확한 에러 메시지
- 동일 job_id로 중복 요청 시 기존 결과 반환

### 코딩 컨벤션
- 모든 서비스 클래스는 async 메서드 기본
- 에러는 FastAPI HTTPException으로 통일
- 로그는 Python logging 모듈 사용 (print 금지)
- 타입 힌트 필수 (Pydantic 모델 활용)
- 함수당 50줄 이하 유지, 초과 시 분리

---

## 12. 샘플 LLM 프롬프트 (참고용)

### 주석 제목 매핑
```
당신은 한국 회계 전문가입니다. 
국문 재무제표 주석 제목과 영문 재무제표 주석 제목을 매핑해주세요.

국문 주석 목록:
{kr_notes_json}

영문 주석 목록:
{en_notes_json}

규칙:
- 의미가 동일한 항목끼리 매핑
- 매핑 불가 항목은 null
- confidence: 0.0~1.0 (1.0=확실, 0.5=불확실)

반드시 아래 JSON 형식만 반환 (다른 텍스트 금지):
{"mappings": [{"kr": "주석 번호", "en": "Note 번호", "confidence": 0.95}, ...]}
```

---

*이 문서는 프로젝트 진행에 따라 업데이트할 것.*
*Claude Code는 매 작업 시작 시 이 파일을 먼저 읽을 것.*
