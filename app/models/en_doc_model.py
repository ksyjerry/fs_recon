from enum import Enum
from pydantic import BaseModel


class DocFormat(str, Enum):
    WORD = "word"
    PDF  = "pdf"


class EnNote(BaseModel):
    """
    영문 보고서의 주석 1개.
    숫자 추출/구조화 없음 — LLM이 읽을 원문 텍스트만 보존.
    """
    note_number: str                        # "1", "15" 등 (감지 실패 시 "unknown_N")
    note_title: str                         # Note 제목 (영문)
    raw_text: str                           # 섹션 전체 원문 텍스트 ← LLM 탐색의 핵심 재료
    source_format: DocFormat                # 원본 포맷 (word / pdf)
    page_range: tuple[int, int] | None = None  # PDF의 경우 페이지 범위 (디버깅용)


class EnDocument(BaseModel):
    """영문 보고서 전체"""
    filename: str
    format: DocFormat
    notes: list[EnNote]
    full_raw_text: str                      # 문서 전체 텍스트 (주석 분리 실패 시 fallback용)
