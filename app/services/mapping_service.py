"""
mapping_service.py — 국문 DSDNote ↔ 영문 EnNote 주석 단위 매핑.

1단계: 번호 기반 (결정론적, confidence=1.0)
2단계: LLM 기반 (번호 불일치 시, 제목 의미 매핑)
3단계: full_raw_text fallback (Note 분리 실패 시)
"""
import json
import logging
from dataclasses import dataclass

from app.models.dsd_model import DSDNote
from app.models.en_doc_model import EnDocument, EnNote
from app.utils.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)


@dataclass
class NoteMapping:
    kr_note: DSDNote
    en_note: EnNote | None        # None = 영문에 대응 주석 없음
    confidence: float
    method: str                   # "number" | "llm" | "fallback" | "unmatched"


async def map_notes(
    kr_notes: list[DSDNote],
    en_doc: EnDocument,
    llm_client: BaseLLMClient,
) -> list[NoteMapping]:
    """
    국문 DSDNote 목록과 영문 EnDocument를 주석 단위로 매핑.

    반환: NoteMapping 리스트 (kr_notes와 1:1 대응, en_note는 None 가능)
    """
    # fallback 모드: en_doc.notes가 없으면 dummy EnNote 하나로 전체 텍스트 사용
    if not en_doc.notes:
        logger.warning("영문 Note 분리 없음 — full_raw_text fallback 적용")
        dummy = _make_full_text_note(en_doc)
        return [
            NoteMapping(kr_note=kr, en_note=dummy, confidence=0.5, method="fallback")
            for kr in kr_notes
        ]

    en_by_num: dict[str, EnNote] = {n.note_number: n for n in en_doc.notes}

    mappings: list[NoteMapping] = []
    unmatched_kr: list[DSDNote] = []
    unmatched_en_nums: set[str] = set(en_by_num.keys())

    # ── 1단계: 번호 기반 매핑 ──────────────────────────────
    for kr in kr_notes:
        if kr.note_number in en_by_num:
            mappings.append(NoteMapping(
                kr_note=kr,
                en_note=en_by_num[kr.note_number],
                confidence=1.0,
                method="number",
            ))
            unmatched_en_nums.discard(kr.note_number)
        else:
            unmatched_kr.append(kr)

    logger.info(
        "번호 매핑: %d쌍 완료, 미매핑 국문=%d개, 미매핑 영문=%d개",
        len(mappings), len(unmatched_kr), len(unmatched_en_nums),
    )

    # ── 2단계: LLM 기반 매핑 (미매핑 주석 처리) ─────────────
    if unmatched_kr:
        unmatched_en = [en_by_num[n] for n in unmatched_en_nums]
        llm_mappings = await _llm_map(unmatched_kr, unmatched_en, llm_client)
        mappings.extend(llm_mappings)
    else:
        # 국문이 모두 매핑된 경우도 남은 영문 주석은 무시
        pass

    # 전체 kr_notes 순서 보존
    kr_order = {kr.note_number: i for i, kr in enumerate(kr_notes)}
    mappings.sort(key=lambda m: kr_order.get(m.kr_note.note_number, 9999))

    return mappings


async def _llm_map(
    unmatched_kr: list[DSDNote],
    unmatched_en: list[EnNote],
    llm_client: BaseLLMClient,
) -> list[NoteMapping]:
    """
    LLM 1회 호출로 미매핑 주석 전체를 의미 기반 매핑.
    """
    if not unmatched_en:
        # 영문에 대응 없음
        return [
            NoteMapping(kr_note=kr, en_note=None, confidence=0.0, method="unmatched")
            for kr in unmatched_kr
        ]

    kr_list = [
        {"num": kr.note_number, "title": kr.note_title}
        for kr in unmatched_kr
    ]
    en_list = [
        {"num": en.note_number, "title": en.note_title}
        for en in unmatched_en
    ]

    system_msg = (
        "당신은 한국 Big4 회계법인의 시니어 감사 전문가입니다.\n"
        "국문 재무제표 주석 제목과 영문 재무제표 주석 제목을 의미 기반으로 매핑해주세요.\n\n"
        "규칙:\n"
        "- 의미가 동일한 항목끼리 매핑\n"
        "- 매핑 불가 항목은 null\n"
        "- confidence: 0.0~1.0 (1.0=확실, 0.5=불확실)\n"
        "- 반드시 JSON만 반환 (다른 텍스트, 마크다운 금지)\n\n"
        '반환 형식: {"mappings": [{"kr_num": "X", "en_num": "Y", "confidence": 0.95}, ...]}'
    )

    user_msg = (
        f"국문 주석 목록:\n{json.dumps(kr_list, ensure_ascii=False, indent=2)}\n\n"
        f"영문 주석 목록:\n{json.dumps(en_list, ensure_ascii=False, indent=2)}\n\n"
        "위 목록을 매핑하여 JSON으로 반환하세요."
    )

    try:
        result = llm_client.chat_json([
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ])
        raw_mappings: list[dict] = result.get("mappings", [])
    except (ValueError, KeyError) as e:
        logger.error("LLM 주석 매핑 실패: %s", e)
        raw_mappings = []

    # LLM 결과 → NoteMapping 변환
    en_by_num = {en.note_number: en for en in unmatched_en}
    mapped_kr_nums: set[str] = set()
    llm_results: list[NoteMapping] = []

    for item in raw_mappings:
        kr_num = str(item.get("kr_num", ""))
        en_num = str(item.get("en_num", "")) if item.get("en_num") else None
        conf   = float(item.get("confidence", 0.5))

        kr_note = next((k for k in unmatched_kr if k.note_number == kr_num), None)
        if kr_note is None:
            continue

        en_note = en_by_num.get(en_num) if en_num else None
        llm_results.append(NoteMapping(
            kr_note=kr_note,
            en_note=en_note,
            confidence=conf,
            method="llm",
        ))
        mapped_kr_nums.add(kr_num)

    # LLM이 매핑하지 못한 나머지 → unmatched
    for kr in unmatched_kr:
        if kr.note_number not in mapped_kr_nums:
            llm_results.append(NoteMapping(
                kr_note=kr, en_note=None, confidence=0.0, method="unmatched",
            ))

    logger.info("LLM 매핑: %d쌍 처리 완료", len(llm_results))
    return llm_results


def _make_full_text_note(en_doc: EnDocument) -> EnNote:
    """Note 분리 실패 시 전체 텍스트를 담는 dummy EnNote 생성."""
    from app.models.en_doc_model import DocFormat
    return EnNote(
        note_number="ALL",
        note_title="(전체 문서 — Note 분리 불가)",
        raw_text=en_doc.full_raw_text,
        source_format=en_doc.format,
    )
