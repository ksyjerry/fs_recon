"""
DSD 파일을 LLM으로 파싱하여 DSDNote 목록으로 변환하는 서비스.

기존 dsd_to_json.py + regex 방식의 한계 (주석 누락)를 극복하기 위해
DSD ZIP에서 XML을 직접 추출 후 LLM이 주석 경계 감지 및 금액 추출.
"""
import asyncio
import json
import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from app.models.dsd_model import DSDAmount, DSDItem, DSDNote

logger = logging.getLogger(__name__)

# ── LLM 프롬프트 ────────────────────────────────────────────────────

_BOUNDARY_SYSTEM = "당신은 한국 재무제표 DSD 파일 분석 전문가입니다."

_BOUNDARY_USER = """\
아래는 DSD 재무제표 파일에서 추출한 단락 목록입니다 (인덱스: 텍스트 형식).

이 목록에서 각 "주석(Note)" 섹션의 시작 위치를 찾아주세요.

주석 헤더 형식 예시:
 - "주석 1. 일반사항"
 - "1. 현금및현금성자산"
 - "주석15. 법인세"
 - "16 종업원급여"

재무상태표·손익계산서 등 재무제표 본문의 계정 행은 주석 헤더가 아닙니다.
오직 새로운 주석 섹션을 여는 상위 제목만 포함하세요.

반드시 JSON 배열만 반환 (다른 텍스트 금지):
[
  {{"segment_index": 42, "note_number": "1", "note_title": "일반사항"}},
  {{"segment_index": 67, "note_number": "2", "note_title": "재무제표 작성기준"}},
  ...
]

단락 목록:
{para_list}
"""

_EXTRACT_SYSTEM = """\
당신은 한국 재무제표 주석(Notes to Financial Statements) 데이터 추출 전문가입니다.
회계 테이블의 다차원 헤더(당기/전기, 레벨1/2/3, 만기구간 등)를 정확히 파악하세요.
"""

_EXTRACT_USER = """\
아래는 재무제표 주석 {note_number}. {note_title}의 전체 내용입니다.

[DSD 특수 형식 안내 — 반드시 숙지]
DSD 파일에서 테이블은 각 셀이 별도 줄로 나타납니다. 예시:
  구분          ← 헤더 레이블
  2025년        ← 헤더 컬럼1
  2024년        ← 헤더 컬럼2
  1년 이하      ← 행 레이블
  1,366,255     ← 행1 컬럼1 금액 (2025년)
  707,200       ← 행1 컬럼2 금액 (2024년)
  5년 초과      ← 행 레이블 (다음에 금액 줄이 없으면 value=null)
  합계          ← 행 레이블
  6,274,247     ← 합계 컬럼1 금액
  925,199       ← 합계 컬럼2 금액

규칙:
- 헤더(레이블 컬럼명 행) 다음에 오는 숫자들은 해당 헤더 컬럼 순서로 대응
- 레이블 바로 다음에 다른 레이블이 오면(숫자 없음) → amounts=[] 또는 value=null
- "&cr;" 은 줄바꿈 마커(무시)
- 단락 텍스트 안에 포함된 금액도 별도 항목으로 추출 (예: "리스료는 1,059,251천원...")
- "NNN천원(전기: MMM천원)" 형태에서 당기와 전기를 각각 별도 amounts로 추출:
  amounts: [
    {{"attributes": {{"기간": "당기"}}, "value": NNN*1000, "raw_text": "NNN천원"}},
    {{"attributes": {{"기간": "전기"}}, "value": MMM*1000, "raw_text": "MMM천원"}}
  ]

[추출 규칙]
1. 모든 행(합계·소계·제목행 포함)을 추출하세요.
2. 금액이 없는 순수 제목행은 is_header_only=true, amounts=[]
3. 단위 감지: "(단위: 천원)" 등에서 unit 파악
4. 금액을 원 단위로 정규화 (단위 "천원" → 값×1000, "백만원" → 값×1000000)
5. 다차원 헤더를 attributes 딕셔너리로 표현
   예) 당기/전기 × 수준1/수준2 → {{"기간":"당기","수준":"수준1"}}
   컬럼 헤더가 연도(2025년/2024년)이면 {{"연도":"2025"}} 형식 사용
6. "-" 또는 빈 셀은 value=null
7. 괄호 금액은 음수: "(1,234,567)" → -1234567000 (천원 단위 가정)
8. reasoning 없이 JSON만 반환 (마크다운·설명 금지)

반환 형식:
{{
  "note_number": "{note_number}",
  "note_title": "{note_title}",
  "unit": "천원",
  "items": [
    {{
      "item_id": 0,
      "label": "행 레이블",
      "is_header_only": false,
      "amounts": [
        {{
          "attributes": {{"기간": "당기"}},
          "value": 1234567000,
          "raw_text": "1,234,567"
        }}
      ]
    }}
  ]
}}

주석 내용:
{note_content}
"""

# ── 1. DSD XML 추출 ──────────────────────────────────────────────────

def _read_contents_xml(dsd_path: Path) -> str:
    """DSD ZIP에서 contents.xml 원문 반환."""
    with zipfile.ZipFile(dsd_path, "r") as zf:
        for name in zf.namelist():
            if "contents" in name.lower() and name.lower().endswith(".xml"):
                data = zf.read(name)
                for enc in ("utf-8", "euc-kr", "cp949", "utf-8-sig"):
                    try:
                        return data.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return data.decode("utf-8", errors="replace")
    raise ValueError(f"DSD에서 contents.xml을 찾을 수 없음: {dsd_path.name}")


# ── 2. XML → 텍스트 세그먼트 ────────────────────────────────────────

# 단락으로 처리할 태그 이름 (upper-case)
_PARA_TAGS = {"P", "PARA", "PARAGRAPH", "TEXT", "TITLE", "SUBTITLE", "LI", "ITEM", "NOTE"}
# 건너뛸 메타데이터 태그
_SKIP_TAGS = {"DOCUMENT-HEADER", "DOCUMENT-INFO", "GENERATOR", "EXTRACTION",
              "SCHEMA", "HEADER", "METADATA"}


def _traverse(elem: ET.Element, segments: list[dict]):
    tag = (elem.tag or "").upper().split("}")[-1]  # 네임스페이스 제거

    # 메타데이터 건너뜀
    if any(s in tag for s in _SKIP_TAGS):
        return

    # 테이블 처리
    if "TABLE" in tag or tag in ("TBL", "TABL"):
        rows = _get_table_rows(elem)
        if rows:
            segments.append({"type": "table", "rows": rows, "text": _rows_to_text(rows)})
        return  # 테이블 내부 재귀 금지

    # 단락 처리: 단락 태그이거나 자식이 없는 리프 노드
    is_para_tag = tag in _PARA_TAGS
    is_leaf = len(list(elem)) == 0

    if is_para_tag or is_leaf:
        text = " ".join(elem.itertext()).strip()
        text = re.sub(r"\s+", " ", text)
        # "&cr;"만으로 구성된 세그먼트 제외, 단일문자 "-"(null 금액) 허용
        if text and text not in ("&cr;",) and (len(text) > 1 or text == "-"):
            segments.append({"type": "p", "text": text})
        # 단락 태그면 내부 재귀 금지
        if is_para_tag:
            return

    # 요소 자체의 직접 텍스트 (tail 포함)
    if elem.text and elem.text.strip():
        t = re.sub(r"\s+", " ", elem.text.strip())
        if t and t not in ("&cr;",) and (len(t) > 1 or t == "-"):
            segments.append({"type": "p", "text": t})

    # 자식 재귀
    for child in elem:
        _traverse(child, segments)
        if child.tail and child.tail.strip():
            tail = re.sub(r"\s+", " ", child.tail.strip())
            if tail and len(tail) > 1:
                segments.append({"type": "p", "text": tail})


def _get_table_rows(table_elem: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    row_tags = {"ROW", "TR", "R"}

    # 직접 자식 중 ROW 계열 찾기
    for elem in table_elem.iter():
        tag = (elem.tag or "").upper().split("}")[-1]
        if tag in row_tags:
            cells = []
            for cell in elem:
                cell_text = " ".join(cell.itertext()).strip()
                cells.append(re.sub(r"\s+", " ", cell_text))
            if any(cells):
                rows.append(cells)

    # ROW 구조가 없으면 전체 텍스트를 1행으로
    if not rows:
        text = " ".join(table_elem.itertext()).strip()
        if text:
            rows.append([text])

    return rows


def _rows_to_text(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(cells) for cells in rows)


def _extract_segments(dsd_path: Path) -> list[dict]:
    xml_str = _read_contents_xml(dsd_path)
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        # 불완전한 XML일 경우 repair 시도
        xml_str = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", xml_str)
        root = ET.fromstring(xml_str)

    segments: list[dict] = []
    _traverse(root, segments)

    # 중복 단락 제거 (연속 중복)
    deduped: list[dict] = []
    for seg in segments:
        if not deduped or seg != deduped[-1]:
            deduped.append(seg)

    logger.debug("XML 세그먼트 추출: %d개", len(deduped))
    return deduped


# ── 3. LLM 주석 경계 감지 ────────────────────────────────────────────

async def _llm_find_boundaries(segments: list[dict], llm_client) -> list[dict]:
    """
    단락 목록을 LLM에 보내 주석 시작 위치 반환.
    [{"segment_index": int, "note_number": str, "note_title": str}, ...]
    """
    # 단락만 추출 (테이블 제외) — LLM에 줄 목록
    para_lines: list[str] = []
    for i, seg in enumerate(segments):
        if seg["type"] == "p":
            # &cr; 제거 후 첫 번째 줄(= 제목부)만 표시 (긴 단락은 제목만 보임)
            text = seg["text"].replace("&cr;", " ").strip()
            text = text.split("\n")[0][:120]
            para_lines.append(f"{i}: {text}")

    if not para_lines:
        return []

    # 너무 많으면 뒤쪽 1000줄만 (주석은 보통 후반부)
    if len(para_lines) > 1000:
        para_lines = para_lines[-1000:]

    para_text = "\n".join(para_lines)

    messages = [
        {"role": "system", "content": _BOUNDARY_SYSTEM},
        {"role": "user",   "content": _BOUNDARY_USER.format(para_list=para_text)},
    ]
    try:
        result = await asyncio.to_thread(llm_client.chat_json, messages)
        if isinstance(result, list) and result:
            # segment_index 유효성 검사
            valid = [
                b for b in result
                if isinstance(b.get("segment_index"), int)
                and 0 <= b["segment_index"] < len(segments)
            ]
            if valid:
                logger.info("LLM 주석 경계 감지: %d개", len(valid))
                return sorted(valid, key=lambda x: x["segment_index"])
    except Exception as e:
        logger.warning("LLM 주석 경계 감지 실패: %s — regex fallback 사용", e)

    return _regex_find_boundaries(segments)


def _regex_find_boundaries(segments: list[dict]) -> list[dict]:
    """LLM 실패 시 regex fallback."""
    PAT_EXPLICIT = re.compile(r"^\s*주\s*석\s*(\d+)\s*[.\s]*(.*)\s*$")
    PAT_SIMPLE   = re.compile(r"^\s*(\d+)\s*[.\s]\s*([가-힣\w\s]{2,40})\s*$")

    # 감사보고서 섹션 키워드 — 이 단어를 포함하는 제목은 재무주석이 아님
    _AUDITOR_KEYWORDS = re.compile(
        r"감사대상|감사참여|감사실시|감사의견|핵심감사|감사범위|감사기준|"
        r"경영진의\s*책임|감사인의\s*책임|감사보고|내부통제|계속기업",
        re.IGNORECASE,
    )

    results: list[dict] = []
    for i, seg in enumerate(segments):
        if seg["type"] != "p":
            continue
        text = seg["text"]
        for pat in [PAT_EXPLICIT, PAT_SIMPLE]:
            m = pat.match(text)
            if m:
                title = m.group(2).strip()
                # 감사보고서 섹션 제목은 재무주석이 아니므로 제외
                if _AUDITOR_KEYWORDS.search(title):
                    logger.debug("감사보고서 섹션 제외: %r", text)
                    break
                results.append({
                    "segment_index": i,
                    "note_number": m.group(1).strip(),
                    "note_title": title,
                })
                break
    logger.info("Regex 주석 경계 감지: %d개", len(results))
    return results


# ── 4. LLM 주석 금액 추출 ─────────────────────────────────────────────

def _build_note_text(note_segments: list[dict]) -> str:
    lines: list[str] = []
    for seg in note_segments:
        if seg["type"] == "p":
            # &cr; → 줄바꿈으로 변환 (DSD 특수 개행 마커)
            text = seg["text"].replace("&cr;", "\n").strip()
            if text:
                lines.append(text)
        elif seg["type"] == "table":
            lines.append("[테이블]")
            lines.append(seg.get("text", ""))
    return "\n".join(lines)


async def _llm_parse_note(
    note_number: str,
    note_title: str,
    note_segments: list[dict],
    llm_client,
    sem: asyncio.Semaphore,
) -> DSDNote | None:
    note_content = _build_note_text(note_segments)

    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM},
        {"role": "user",   "content": _EXTRACT_USER.format(
            note_number=note_number,
            note_title=note_title,
            note_content=note_content[:10000],
        )},
    ]

    async with sem:
        try:
            result = await asyncio.to_thread(llm_client.chat_json, messages)
        except Exception as e:
            logger.error("주석 %s 금액 추출 실패: %s", note_number, e)
            return None

    return _build_dsd_note(result, fallback_number=note_number, fallback_title=note_title)


def _build_dsd_note(
    data: dict,
    fallback_number: str = "?",
    fallback_title: str = "",
) -> DSDNote | None:
    """LLM JSON 응답 → DSDNote.
    LLM이 note_number를 누락한 경우 경계 감지 단계의 fallback_number 사용.
    """
    try:
        note_number = str(data.get("note_number") or fallback_number)
        note_title  = str(data.get("note_title")  or fallback_title)
        unit        = str(data.get("unit",         "원"))

        items: list[DSDItem] = []
        for item_data in data.get("items", []):
            amounts: list[DSDAmount] = []
            for amt in item_data.get("amounts", []):
                amounts.append(DSDAmount(
                    attributes=dict(amt.get("attributes") or {}),
                    value=_to_float(amt.get("value")),
                    raw_text=str(amt.get("raw_text", "")),
                ))
            items.append(DSDItem(
                item_id=item_data.get("item_id", len(items)),
                label=str(item_data.get("label", "")),
                is_header_only=bool(item_data.get("is_header_only", False)),
                amounts=amounts,
                unit=unit,
                raw_row={},
            ))

        return DSDNote(
            note_number=note_number,
            note_title=note_title,
            source_filename="",
            unit=unit,
            raw_paragraphs=[],
            items=items,
        )
    except Exception as e:
        logger.error("DSDNote 변환 실패: %s | 데이터: %s", e, str(data)[:300])
        return None


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ── 5. 메인 진입점 ────────────────────────────────────────────────────

async def parse_dsd_file(dsd_path: Path, llm_client) -> list[DSDNote]:
    """
    DSD 파일 → DSDNote 목록.

    1. DSD ZIP에서 contents.xml 직접 추출
    2. XML → 텍스트 세그먼트 변환
    3. LLM이 주석 경계(번호·제목) 감지
    4. LLM이 각 주석 금액 구조화 추출 (병렬, Semaphore 10)
    """
    logger.info("DSD 파싱 시작 (LLM 모드): %s", dsd_path.name)

    # 1. 세그먼트 추출
    try:
        segments = _extract_segments(dsd_path)
    except Exception as e:
        raise RuntimeError(f"DSD XML 추출 실패: {e}") from e
    logger.info("  세그먼트: %d개 (단락+테이블)", len(segments))

    # 2. 주석 경계 감지
    boundaries = await _llm_find_boundaries(segments, llm_client)
    if not boundaries:
        logger.error("주석을 하나도 감지하지 못했습니다.")
        return []
    logger.info("  주석 경계: %d개", len(boundaries))

    # 3. 각 주석의 세그먼트 구간 계산
    chunks: list[tuple[str, str, list[dict]]] = []
    for i, b in enumerate(boundaries):
        start = b["segment_index"]
        end   = boundaries[i + 1]["segment_index"] if i + 1 < len(boundaries) else len(segments)
        chunks.append((
            str(b.get("note_number", str(i + 1))),
            str(b.get("note_title",  "")),
            segments[start:end],
        ))

    # 4. 병렬 금액 추출
    sem = asyncio.Semaphore(10)
    tasks = [
        _llm_parse_note(num, title, segs, llm_client, sem)
        for num, title, segs in chunks
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    notes: list[DSDNote] = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning("주석 파싱 오류 (건너뜀): %s", r)
        elif r is not None:
            notes.append(r)

    notes.sort(key=lambda n: int(n.note_number) if n.note_number.isdigit() else 999)
    logger.info("DSD 파싱 완료: 주석 %d개", len(notes))
    return notes
