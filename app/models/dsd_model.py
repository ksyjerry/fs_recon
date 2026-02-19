from pydantic import BaseModel


class DSDAmount(BaseModel):
    """
    하나의 금액 셀 = 행 레이블 + 속성 조합으로 식별되는 단일 값
    attributes 예시:
      {"기간": "당기", "수준": "수준2"}
    """
    attributes: dict[str, str]
    value: float | None
    raw_text: str


class DSDItem(BaseModel):
    """
    테이블의 한 행 = 행 레이블 + 해당 행의 모든 금액 셀들
    """
    item_id: int
    label: str
    is_header_only: bool = False
    amounts: list[DSDAmount]
    unit: str = "원"
    raw_row: dict


class DSDNote(BaseModel):
    note_number: str
    note_title: str
    source_filename: str
    unit: str = "원"
    raw_paragraphs: list[str]
    items: list[DSDItem]
