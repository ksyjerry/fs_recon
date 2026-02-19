"""
reconcile_service.py — LLM 직접 판단 방식 대사 서비스 (★핵심★).

핵심 철학:
  국문 구조(앵커)를 들고 영문 원문 전체를 LLM이 직접 읽으며 대사.
  기계적 숫자 추출이 아닌, 회계 전문가가 사람처럼 읽고 비교하는 방식.
"""
import asyncio
import json
import logging
from typing import Callable

from app.models.dsd_model import DSDItem, DSDNote
from app.models.en_doc_model import EnNote
from app.models.reconcile_model import AmountMatch, ReconcileItem, ReconcileResult
from app.services.mapping_service import NoteMapping
from app.utils.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

# 수치 일치 판정 허용 오차
# 비율 오차 없음 — 1원 초과 차이는 모두 불일치
# (1원 허용: 부동소수점 반올림 처리용)
MATCH_TOLERANCE_RATIO = 0.0
MATCH_TOLERANCE_ABS   = 1.0

# 영문 원문 청크 분할 기준 (토큰 절약 fallback용)
CHUNK_ITEM_SIZE = 3

# 동시 LLM 호출 최대 수 (PwC 엔드포인트 rate limit 고려)
MAX_CONCURRENT = 10


# ─────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────

async def reconcile_all(
    mappings: list[NoteMapping],
    llm_client: BaseLLMClient,
    progress_cb: Callable[[int, str], None] | None = None,
) -> list[ReconcileResult]:
    """
    매핑된 주석 쌍 전체를 병렬 대사하여 ReconcileResult 목록 반환.
    asyncio.gather + asyncio.to_thread 조합으로 최대 MAX_CONCURRENT개 동시 처리.
    결과는 입력 순서(주석 번호 순) 보장.

    progress_cb(progress: int, step: str) — 진행 상황 콜백 (선택)
    """
    total = len(mappings)
    completed = 0
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def run_one(mapping: NoteMapping) -> ReconcileResult:
        nonlocal completed
        async with semaphore:
            result = await _reconcile_one(mapping, llm_client)
        async with lock:
            completed += 1
            step_msg = f"주석 {mapping.kr_note.note_number} 대사 완료 ({completed}/{total})"
            logger.info(step_msg)
            if progress_cb:
                progress_cb(int(20 + (completed / total) * 70), step_msg)
        return result

    tasks = [run_one(m) for m in mappings]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    # 예외 발생 주석은 전체 미발견 처리 후 계속 진행
    results: list[ReconcileResult] = []
    for i, r in enumerate(results_raw):
        if isinstance(r, Exception):
            logger.error("주석 %s 대사 실패 (건너뜀): %s", mappings[i].kr_note.note_number, r)
            results.append(_make_failed_result(mappings[i]))
        else:
            results.append(r)
    return results


# ─────────────────────────────────────────────────────────────────
# 주석 1쌍 대사
# ─────────────────────────────────────────────────────────────────

async def _reconcile_one(
    mapping: NoteMapping,
    llm_client: BaseLLMClient,
) -> ReconcileResult:
    kr_note = mapping.kr_note
    en_note = mapping.en_note

    # 영문 Note 없음 → 전체 미발견 처리
    if en_note is None:
        items = [_make_not_found_item(item) for item in kr_note.items]
        return ReconcileResult(
            note_number_kr=kr_note.note_number,
            note_number_en=None,
            note_title_kr=kr_note.note_title,
            note_title_en=None,
            note_mapping_confidence=mapping.confidence,
            items=items,
        )

    # 금액 없는 주석 (텍스트 전용) → 항목만 기록
    non_header_items = [i for i in kr_note.items if not i.is_header_only]
    if not non_header_items:
        return ReconcileResult(
            note_number_kr=kr_note.note_number,
            note_number_en=en_note.note_number,
            note_title_kr=kr_note.note_title,
            note_title_en=en_note.note_title,
            note_mapping_confidence=mapping.confidence,
            items=[_make_header_only_item(item) for item in kr_note.items],
        )

    # LLM 대사 실행
    llm_responses = await _call_llm_reconcile(kr_note, en_note, llm_client)

    # LLM 응답 → ReconcileItem 변환
    items = _build_reconcile_items(kr_note.items, llm_responses)

    return ReconcileResult(
        note_number_kr=kr_note.note_number,
        note_number_en=en_note.note_number,
        note_title_kr=kr_note.note_title,
        note_title_en=en_note.note_title,
        note_mapping_confidence=mapping.confidence,
        items=items,
    )


# ─────────────────────────────────────────────────────────────────
# LLM 호출
# ─────────────────────────────────────────────────────────────────

async def _call_llm_reconcile(
    kr_note: DSDNote,
    en_note: EnNote,
    llm_client: BaseLLMClient,
) -> list[dict]:
    """
    주석 1쌍에 대해 LLM 대사 호출.
    영문 원문이 길어도 최신 모델은 128k+ 컨텍스트 지원으로 기본 단일 호출.
    실패 시 청크 분할 fallback.
    """
    dsd_items_payload = _build_dsd_items_payload(kr_note.items)

    try:
        return await _llm_single_call(kr_note, en_note, dsd_items_payload, llm_client)
    except (ValueError, Exception) as e:
        logger.warning("주석 %s LLM 단일 호출 실패 (%s) — 청크 fallback 적용", kr_note.note_number, e)
        return await _llm_chunked_call(kr_note, en_note, llm_client)


async def _llm_single_call(
    kr_note: DSDNote,
    en_note: EnNote,
    dsd_items_payload: list[dict],
    llm_client: BaseLLMClient,
) -> list[dict]:
    system_msg = _build_system_prompt()
    user_msg   = _build_user_prompt(kr_note, en_note, dsd_items_payload)

    raw: list[dict] = await llm_client.chat_json_async([
        {"role": "system", "content": system_msg},
        {"role": "user",   "content": user_msg},
    ])

    if not isinstance(raw, list):
        raise ValueError(f"LLM이 list가 아닌 {type(raw).__name__}을 반환함")

    logger.debug("주석 %s LLM 응답: %d개 amount", kr_note.note_number, len(raw))
    return raw


async def _llm_chunked_call(
    kr_note: DSDNote,
    en_note: EnNote,
    llm_client: BaseLLMClient,
) -> list[dict]:
    """DSDItem을 CHUNK_ITEM_SIZE 단위로 나눠 여러 번 LLM 호출."""
    system_msg = _build_system_prompt()
    all_results: list[dict] = []

    items = kr_note.items
    for start in range(0, len(items), CHUNK_ITEM_SIZE):
        chunk = items[start: start + CHUNK_ITEM_SIZE]
        payload = _build_dsd_items_payload(chunk)
        user_msg = _build_user_prompt(kr_note, en_note, payload)

        try:
            chunk_result: list[dict] = await llm_client.chat_json_async([
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": user_msg},
            ])
            if isinstance(chunk_result, list):
                all_results.extend(chunk_result)
        except Exception as e:
            logger.error("청크 호출 실패 (start=%d): %s", start, e)

    return all_results


# ─────────────────────────────────────────────────────────────────
# 프롬프트 빌더
# ─────────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    return (
        "당신은 한국 Big4 회계법인의 시니어 감사 전문가입니다.\n"
        "국문 재무제표(DSD 기반)와 영문 재무제표를 대사(reconciliation)하는 업무를 수행합니다.\n\n"
        "규칙:\n"
        "1. 국문 항목 목록의 각 금액(amount_id별)에 대응하는 영문 금액을 영문 원문에서 찾으세요.\n"
        "2. 기계적 텍스트 매칭이 아닌, 회계 전문가로서 문맥과 의미를 이해하고 판단하세요.\n"
        "3. 영문에서 합계/소계 레이블이 없어도 숫자의 위치와 맥락으로 판단하세요.\n"
        "4. 다차원 속성(기간/만기/수준/잔액 등)을 고려해 어떤 열·행의 금액인지 파악하세요.\n"
        "5. 찾지 못하면 found=false로 명시하세요 (억지로 찾지 마세요).\n"
        "6. 국문 금액은 이미 원(KRW) 단위로 정규화되어 있으나, 영문은 천원(thousands) 단위일 수 있습니다.\n"
        "   → value_en은 영문 원문에 표기된 숫자 그대로 반환하세요 (단위 변환 금지).\n"
        "7. reasoning 필드는 반드시 한국어로 작성하세요.\n"
        "   - found=true이고 금액이 일치할 것으로 보이면 reasoning을 빈 문자열(\"\")로 반환하세요.\n"
        "   - found=false(미발견)이거나 금액 불일치가 의심될 때만 구체적인 이유를 한국어로 작성하세요.\n"
        "8. 반드시 JSON 배열만 반환하세요 (다른 텍스트, 마크다운 금지)."
    )


def _build_user_prompt(
    kr_note: DSDNote,
    en_note: EnNote,
    dsd_items_payload: list[dict],
) -> str:
    items_json = json.dumps(dsd_items_payload, ensure_ascii=False, indent=2)
    return (
        f"══ 국문 주석 정보 ══\n"
        f"주석 번호: {kr_note.note_number}\n"
        f"주석 제목: {kr_note.note_title}\n"
        f"단위: {kr_note.unit} (이미 원 단위로 정규화됨)\n\n"
        f"국문 항목 목록 (구조화된 JSON):\n{items_json}\n\n"
        f"══ 영문 Note 원문 전체 (가공 없이 그대로) ══\n"
        f"{en_note.raw_text}\n\n"
        "위 영문 원문을 보고, 국문 항목의 각 amount_id별 대응 영문 금액을 찾아 "
        "아래 형식의 JSON 배열로만 반환하세요:\n"
        "[\n"
        '  {"amount_id": "0_0", "en_label_for_row": "...", '
        '"en_attributes": {"period": "current"}, '
        '"value_en": 1234567, "confidence": 0.97, "found": true, '
        '"reasoning": "..."},\n'
        '  {"amount_id": "1_0", ..., "found": false, "value_en": null, "confidence": 0.0}\n'
        "]"
    )


def _build_dsd_items_payload(items: list[DSDItem]) -> list[dict]:
    """
    DSDItem 목록 → LLM에 전달할 JSON 직렬화 가능 구조 변환.
    각 amount마다 amount_id 부여: "{item_id}_{amt_idx}"
    value_kr이 None인 셀(국문 DSD "-"/빈값)은 대사 대상 제외.
    """
    payload = []
    for item in items:
        if item.is_header_only:
            continue
        for amt_idx, amt in enumerate(item.amounts):
            # 국문 금액이 None인 셀 제외 (0은 포함)
            if amt.value is None:
                continue
            amount_id = f"{item.item_id}_{amt_idx}"
            # _is_pct 내부 속성 제거 (LLM 혼란 방지)
            clean_attrs = {k: v for k, v in amt.attributes.items() if not k.startswith("_")}
            payload.append({
                "amount_id":  amount_id,
                "item_id":    item.item_id,
                "label_kr":   item.label,
                "attributes": clean_attrs,
                "value_kr":   amt.value,
                "raw_text_kr": amt.raw_text,
            })
    return payload


# ─────────────────────────────────────────────────────────────────
# LLM 응답 → ReconcileItem 변환
# ─────────────────────────────────────────────────────────────────

def _build_reconcile_items(
    dsd_items: list[DSDItem],
    llm_responses: list[dict],
) -> list[ReconcileItem]:
    """
    LLM 응답을 amount_id 기준으로 인덱싱하여 ReconcileItem 목록 빌드.
    """
    # amount_id → LLM 응답 dict
    response_map: dict[str, dict] = {
        str(r.get("amount_id", "")): r
        for r in llm_responses
        if r.get("amount_id")
    }

    reconcile_items: list[ReconcileItem] = []

    for item in dsd_items:
        if item.is_header_only:
            reconcile_items.append(_make_header_only_item(item))
            continue

        amount_matches: list[AmountMatch] = []

        for amt_idx, amt in enumerate(item.amounts):
            # 국문 금액이 None인 셀은 표시 제외 (0은 포함)
            if amt.value is None:
                continue
            amount_id = f"{item.item_id}_{amt_idx}"
            llm_resp  = response_map.get(amount_id)

            match = _build_amount_match(amount_id, amt, llm_resp)
            amount_matches.append(match)

        # item의 대표 영문 레이블: 첫 번째 found 응답에서 추출
        label_en = None
        for amt_idx in range(len(item.amounts)):
            r = response_map.get(f"{item.item_id}_{amt_idx}")
            if r and r.get("found") and r.get("en_label_for_row"):
                label_en = r["en_label_for_row"]
                break

        reconcile_items.append(ReconcileItem(
            item_id=item.item_id,
            label_kr=item.label,
            label_en=label_en,
            is_header_only=False,
            amount_matches=amount_matches,
        ))

    return reconcile_items


def _build_amount_match(
    amount_id: str,
    dsd_amt,
    llm_resp: dict | None,
) -> AmountMatch:
    """단일 DSDAmount + LLM 응답 → AmountMatch."""
    clean_attrs_kr = {k: v for k, v in dsd_amt.attributes.items() if not k.startswith("_")}

    if llm_resp is None or not llm_resp.get("found", False):
        return AmountMatch(
            amount_id=amount_id,
            attributes_kr=clean_attrs_kr,
            attributes_en={},
            value_kr=dsd_amt.value,
            value_en=None,
            is_match=None,
            variance=None,
            confidence=llm_resp.get("confidence", 0.0) if llm_resp else 0.0,
            found=False,
            llm_note=llm_resp.get("reasoning") if llm_resp else None,
        )

    value_en_raw = llm_resp.get("value_en")
    value_en_raw_f: float | None = float(value_en_raw) if value_en_raw is not None else None

    # 수치 일치 판정 + 단위 정규화 (코드가 계산, LLM이 찾기만)
    # value_en_norm: 원 단위로 정규화된 영문 금액 (×1000 감지 시 스케일링 적용)
    is_match, variance, value_en_norm = _calc_match(dsd_amt.value, value_en_raw_f)

    # 일치 항목은 메모 불필요 — 미발견/미일치만 기록
    raw_note = llm_resp.get("reasoning") or ""
    llm_note = None if is_match is True else (raw_note or None)

    return AmountMatch(
        amount_id=amount_id,
        attributes_kr=clean_attrs_kr,
        attributes_en=llm_resp.get("en_attributes") or {},
        value_kr=dsd_amt.value,
        value_en=value_en_norm,   # 원 단위로 정규화된 값 저장
        is_match=is_match,
        variance=variance,
        confidence=float(llm_resp.get("confidence", 0.5)),
        found=True,
        llm_note=llm_note,
    )


def _calc_match(
    value_kr: float | None,
    value_en: float | None,
) -> tuple[bool | None, float | None, float | None]:
    """
    수치 일치 판정 + 영문 금액 단위 정규화.
    영문은 천원(thousands) 단위일 수 있으므로 ×1000 비교도 수행.

    반환: (is_match, variance, normalized_value_en)
      - normalized_value_en: 원 단위로 정규화된 영문 금액
        * 직접 일치 또는 단위 무관 → value_en 그대로
        * ×1000 일치 또는 ×1000 관계 감지 → value_en × 1000
    """
    if value_kr is None or value_en is None:
        return None, None, value_en

    tol = max(MATCH_TOLERANCE_ABS, abs(value_kr) * MATCH_TOLERANCE_RATIO)

    # 1) 직접 비교 (같은 단위)
    diff = abs(value_kr - value_en)
    if diff <= tol:
        return True, value_en - value_kr, value_en

    # 2) ×1000 비교 (영문이 천원 단위)
    value_en_scaled = value_en * 1000
    diff_scaled = abs(value_kr - value_en_scaled)
    if diff_scaled <= tol:
        return True, value_en_scaled - value_kr, value_en_scaled

    # 3) 불일치 — 단위 추론하여 표시값 결정
    # 비율이 500~2000배면 ×1000 관계로 간주, 스케일된 값으로 variance 계산
    if value_en != 0 and abs(value_kr) > 0:
        ratio = abs(value_kr / value_en)
        if 500 <= ratio <= 2000:
            return False, value_en_scaled - value_kr, value_en_scaled

    return False, value_en - value_kr, value_en


# ─────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────

def _make_failed_result(mapping: NoteMapping) -> ReconcileResult:
    """대사 실패 주석 — 전체 항목을 미발견으로 처리."""
    items = [_make_not_found_item(item) for item in mapping.kr_note.items]
    en_note = mapping.en_note
    return ReconcileResult(
        note_number_kr=mapping.kr_note.note_number,
        note_number_en=en_note.note_number if en_note else None,
        note_title_kr=mapping.kr_note.note_title,
        note_title_en=en_note.note_title if en_note else None,
        note_mapping_confidence=mapping.confidence,
        items=items,
    )


def _make_not_found_item(item: DSDItem) -> ReconcileItem:
    """영문 Note 없음 — 전체 금액 미발견 처리."""
    matches = [
        AmountMatch(
            amount_id=f"{item.item_id}_{i}",
            attributes_kr={k: v for k, v in amt.attributes.items() if not k.startswith("_")},
            attributes_en={},
            value_kr=amt.value,
            value_en=None,
            is_match=None,
            variance=None,
            confidence=0.0,
            found=False,
            llm_note="영문 Note 미존재",
        )
        for i, amt in enumerate(item.amounts)
    ]
    return ReconcileItem(
        item_id=item.item_id,
        label_kr=item.label,
        label_en=None,
        is_header_only=item.is_header_only,
        amount_matches=matches,
    )


def _make_header_only_item(item: DSDItem) -> ReconcileItem:
    return ReconcileItem(
        item_id=item.item_id,
        label_kr=item.label,
        label_en=None,
        is_header_only=True,
        amount_matches=[],
    )
