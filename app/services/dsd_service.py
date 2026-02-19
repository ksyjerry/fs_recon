"""
DSD 파일을 파싱하여 DSDNote 목록으로 변환하는 서비스.
parsers/dsd_to_json.py 원본 수정 없이 래핑만 수행.
"""
import json
import logging
import re
import sys
import tempfile
from pathlib import Path

from app.models.dsd_model import DSDAmount, DSDItem, DSDNote
from app.utils.amount_utils import (
    detect_unit_from_text,
    flatten_dict,
    normalize_unit,
    parse_amount,
)

# parsers 패키지를 찾기 위해 프로젝트 루트를 sys.path에 추가
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from parsers.dsd_to_json import process_dsd_to_json  # noqa: E402

logger = logging.getLogger(__name__)

# 행 레이블로 처리할 컬럼 키 목록 (이 키에 해당하는 컬럼은 label로 사용)
LABEL_COLUMNS = {"계정과목", "항목", "구분", "내용", "과목", "종류", ""}

# 주석 제목 감지 패턴들
# 형식 1: "주석 15. 제목"
NOTE_PATTERN_EXPLICIT = re.compile(
    r"^\s*주석\s*(\d+)[.\s]*(.*)$",
)
# 형식 2: "15. 제목" — "15.1 소제목" 같은 하위 항목 제외
# → 소수점 없는 순수 정수 + ". " + 텍스트
NOTE_PATTERN_SIMPLE = re.compile(
    r"^\s*(\d+)\.\s+(.+)$",
)


async def parse_dsd_file(dsd_path: Path) -> list[DSDNote]:
    """
    DSD 파일을 읽어 DSDNote 목록을 반환.

    1. dsd_to_json.py의 process_dsd_to_json() 호출 → JSON 생성
    2. JSON 로드 후 주석 섹션 분리
    3. 각 주석 내 테이블 행을 DSDItem으로 변환
    """
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        output_json_path = tmp.name

    try:
        process_dsd_to_json(str(dsd_path), output_json_path)

        with open(output_json_path, encoding="utf-8") as f:
            raw_data: list[dict] = json.load(f)
    finally:
        Path(output_json_path).unlink(missing_ok=True)

    # 모든 파일의 content를 순서대로 합침
    all_content: list[dict] = []
    source_map: dict[int, str] = {}  # content index → filename
    for file_entry in raw_data:
        filename = file_entry.get("filename", "unknown")
        for item in file_entry.get("content", []):
            source_map[len(all_content)] = filename
            all_content.append(item)

    notes = _split_into_notes(all_content, source_map)
    logger.info("DSD 파싱 완료: 주석 %d개", len(notes))
    return notes


def _detect_note_header(text: str) -> tuple[str, str] | None:
    """
    텍스트가 주석 최상위 섹션 제목이면 (번호, 제목) 반환, 아니면 None.
    하위 항목(1.1, 2.1 등) 및 &cr; 노이즈는 제외.
    """
    text = text.strip()
    if not text or "&cr;" in text:
        return None

    # 형식 1: "주석 15. 제목"
    m = NOTE_PATTERN_EXPLICIT.match(text)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # 형식 2: "15. 제목" — 단, "15.1 소제목"처럼 소수점 포함 번호는 제외
    # 원문에 소수점 숫자(예: "1.1")가 없을 때만 매칭
    m = NOTE_PATTERN_SIMPLE.match(text)
    if m:
        # 하위 항목 제외: 제목 안에 "X.Y" 패턴이 없어야 함
        # 예: "1.1 연결회사" → NOTE_PATTERN_SIMPLE에서 이미 걸림
        # ("1.1 연결회사" → 첫 숫자=1, 뒤 ".1 연결회사" → 패턴 불일치)
        # 실제로는 "1.1" 같은 경우 NOTE_PATTERN_SIMPLE = r"^\s*(\d+)\.\s+(.+)$" 에서
        # "1.1 연결회사" → (\d+)=1, "1 연결회사" (공백 없음) → 불일치로 OK
        # 하지만 "1. 일반사항" → OK
        return m.group(1).strip(), m.group(2).strip()

    return None


def _split_into_notes(
    content: list[dict],
    source_map: dict[int, str],
) -> list[DSDNote]:
    """
    content 리스트에서 주석 섹션을 분리하여 DSDNote 목록 반환.
    """
    notes: list[DSDNote] = []
    current_note_num: str | None = None
    current_note_title: str = ""
    current_source: str = "unknown"
    current_paragraphs: list[str] = []
    current_tables: list[list[dict]] = []

    def _flush_note():
        if current_note_num is None:
            return
        items = _build_items_from_tables(current_tables, current_note_num)
        note_unit = _detect_unit_from_paragraphs(current_paragraphs)
        # 단위 정규화 적용 (퍼센트 컬럼 제외)
        for item in items:
            item.unit = note_unit
            for amt in item.amounts:
                if amt.value is not None and amt.attributes.get("_is_pct") != "true":
                    amt.value = normalize_unit(amt.value, note_unit)
        notes.append(
            DSDNote(
                note_number=current_note_num,
                note_title=current_note_title,
                source_filename=current_source,
                unit=note_unit,
                raw_paragraphs=list(current_paragraphs),
                items=items,
            )
        )

    for idx, entry in enumerate(content):
        source = source_map.get(idx, "unknown")

        if "p" in entry:
            text = entry["p"]
            header = _detect_note_header(text)
            if header:
                _flush_note()
                current_note_num, current_note_title = header
                current_source = source
                current_paragraphs = [text]
                current_tables = []
            else:
                if current_note_num is not None:
                    current_paragraphs.append(text)

        elif "table" in entry:
            if current_note_num is not None:
                current_tables.append(entry["table"])

    _flush_note()
    return notes


def _detect_unit_from_paragraphs(paragraphs: list[str]) -> str:
    for p in paragraphs:
        unit = detect_unit_from_text(p)
        if unit != "원":
            return unit
    return "원"


def _build_items_from_tables(
    tables: list[list[dict]],
    note_number: str,
) -> list[DSDItem]:
    """
    테이블 목록을 DSDItem 리스트로 변환.
    """
    items: list[DSDItem] = []
    item_id = 0

    for table in tables:
        for raw_row in table:
            flat = flatten_dict(raw_row) if _is_nested(raw_row) else raw_row

            # 레이블 컬럼 찾기
            label = _extract_label(flat)
            if label is None:
                label = ""

            # 금액 컬럼 추출 (레이블 컬럼 제외)
            amounts = _extract_amounts(flat)

            is_header_only = len(amounts) == 0

            items.append(
                DSDItem(
                    item_id=item_id,
                    label=label,
                    is_header_only=is_header_only,
                    amounts=amounts,
                    unit="원",  # 나중에 note 단위로 덮어씀
                    raw_row=raw_row,
                )
            )
            item_id += 1

    return items


def _is_nested(d: dict) -> bool:
    return any(isinstance(v, dict) for v in d.values())


def _extract_label(flat: dict) -> str | None:
    """
    레이블 컬럼 키 우선순위로 레이블 텍스트 반환.
    """
    for col in LABEL_COLUMNS:
        if col in flat and isinstance(flat[col], str) and flat[col].strip():
            return flat[col].strip()

    # LABEL_COLUMNS에 없어도 값이 숫자가 아닌 첫 번째 컬럼을 레이블로 사용
    for k, v in flat.items():
        if isinstance(v, str) and parse_amount(v) is None and v.strip():
            return v.strip()

    return None


def _extract_amounts(flat: dict) -> list[DSDAmount]:
    """
    flat dict에서 금액 컬럼들을 DSDAmount 리스트로 변환.
    attributes는 "." 구분 경로를 split하여 구성.
    """
    amounts: list[DSDAmount] = []

    for key, raw_val in flat.items():
        if not isinstance(raw_val, str):
            continue

        # 레이블 컬럼 스킵
        base_key = key.split(".")[0] if "." in key else key
        if base_key in LABEL_COLUMNS:
            continue
        if key in LABEL_COLUMNS:
            continue

        # 퍼센트/비율 컬럼은 금액 단위 변환 대상 제외 표시
        is_pct_col = "%" in key or "율" in key or "비율" in key

        value = parse_amount(raw_val)

        # 빈 값 & 변환 불가 → 금액 없음 (label-only 컬럼일 수도)
        if value is None and raw_val.strip() not in ("", "-", "—", "–"):
            # 텍스트 값이면 레이블로 보고 스킵
            if not raw_val.strip().lstrip("(").rstrip(")").replace(",", "").replace(".", "").isdigit():
                continue

        # 속성 구성: "당기.수준1" → {"col_0": "당기", "col_1": "수준1"}
        parts = [p.strip() for p in key.split(".") if p.strip()]
        attributes = _parts_to_attributes(parts)

        # 퍼센트 컬럼은 is_pct=True 속성을 attributes에 표시
        if is_pct_col:
            attributes["_is_pct"] = "true"

        amounts.append(
            DSDAmount(
                attributes=attributes,
                value=value,
                raw_text=raw_val,
            )
        )

    return amounts


def _parts_to_attributes(parts: list[str]) -> dict[str, str]:
    """
    헤더 경로 parts → attributes dict.
    첫 번째 depth는 주로 기간(당기/전기).
    """
    if not parts:
        return {}

    # 휴리스틱 키 이름 추정
    PERIOD_VALUES = {"당기", "전기", "current", "prior", "현재", "비교"}
    LEVEL_HINTS = {"수준", "level", "등급"}
    MATURITY_HINTS = {"이내", "초과", "만기", "1년", "이상"}

    attr: dict[str, str] = {}

    for i, part in enumerate(parts):
        lower = part.lower()
        if i == 0:
            if any(v in part for v in PERIOD_VALUES):
                key = "기간"
            else:
                key = "col_0"
        elif i == 1:
            if any(h in lower for h in LEVEL_HINTS):
                key = "수준"
            elif any(h in lower for h in MATURITY_HINTS):
                key = "만기"
            else:
                key = f"col_{i}"
        else:
            key = f"col_{i}"

        # 중복 키 방지
        if key in attr:
            key = f"{key}_{i}"

        attr[key] = part

    return attr
