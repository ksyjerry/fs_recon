import re
import logging
from typing import Any

logger = logging.getLogger(__name__)


def flatten_dict(d: dict, sep: str = ".", parent_key: str = "") -> dict:
    """
    중첩 dict를 평탄화.
    {"당기": {"금액": "1,000"}} → {"당기.금액": "1,000"}
    dsd_to_json.py의 multirow header 결과 처리용
    """
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, sep=sep, parent_key=new_key).items())
        else:
            items.append((new_key, v))
    return dict(items)


def parse_amount(text: str) -> float | None:
    """
    금액 문자열 → float 변환
    - 쉼표 제거: "1,234,567" → 1234567.0
    - 괄호 = 음수: "(1,234)" → -1234.0
    - "-" 단독 = None (해당 없음)
    - 빈 문자열 = None
    - 변환 불가 = None
    """
    if not text or not isinstance(text, str):
        return None

    text = text.strip()

    if text in ("-", "—", "–", ""):
        return None

    is_negative = text.startswith("(") and text.endswith(")")
    if is_negative:
        text = text[1:-1]

    text = text.replace(",", "").replace(" ", "")

    try:
        value = float(text)
        return -value if is_negative else value
    except ValueError:
        logger.debug("금액 변환 실패: %r", text)
        return None


def normalize_unit(amount: float, unit: str) -> float:
    """
    모든 금액을 "원" 단위로 통일
    "천원"   → amount * 1_000
    "백만원"  → amount * 1_000_000
    외화(달러 등)는 그대로
    """
    unit = unit.strip()
    if "백만" in unit or "million" in unit.lower():
        return amount * 1_000_000
    if "천" in unit or "thousand" in unit.lower():
        return amount * 1_000
    return amount


def detect_unit_from_text(text: str) -> str:
    """
    텍스트에서 단위 감지.
    "(단위: 천원)", "(Unit: KRW thousands)" 등 패턴 검색.
    감지 실패 시 "원" 반환.
    """
    patterns = [
        r"\(단위\s*:\s*([^)]+)\)",
        r"\(Unit\s*:\s*([^)]+)\)",
        r"단위\s*:\s*(\S+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            if "백만" in raw or "million" in raw.lower():
                return "백만원"
            if "천" in raw or "thousand" in raw.lower():
                return "천원"
            return raw
    return "원"
