from pydantic import BaseModel, computed_field


class AmountMatch(BaseModel):
    """
    단일 속성 조합에 대한 대사 결과.
    국문 DSDAmount 1개 ↔ LLM이 찾은 영문 금액 1개.
    """
    amount_id: str                       # "{item_id}_{amt_idx}" 형식 (LLM 응답 키)
    attributes_kr: dict[str, str]        # 국문 속성 (예: {"기간":"당기","수준":"수준2"})
    attributes_en: dict[str, str]        # LLM이 판단한 영문 속성
    value_kr: float | None               # 국문 금액 (원)
    value_en: float | None               # LLM이 찾은 영문 금액
    is_match: bool | None                # True/False/None(미발견)
    variance: float | None               # value_en - value_kr
    confidence: float                    # LLM 탐색 신뢰도 (0.0~1.0)
    found: bool                          # 영문에서 발견 여부
    llm_note: str | None = None          # LLM 메모


class ReconcileItem(BaseModel):
    """
    국문 DSDItem 1개(행)에 대한 전체 대사 결과.
    """
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

    @computed_field
    @property
    def total_amounts(self) -> int:
        return sum(
            len(i.amount_matches)
            for i in self.items
            if not i.is_header_only
        )

    @computed_field
    @property
    def matched_count(self) -> int:
        return sum(
            1
            for i in self.items
            for m in i.amount_matches
            if m.is_match is True
        )

    @computed_field
    @property
    def match_rate(self) -> float:
        return self.matched_count / self.total_amounts if self.total_amounts else 0.0
