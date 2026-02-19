"""
LLM 클라이언트 팩토리 — PwC Internal LLM / Claude Direct API 추상화.
서비스 레이어는 get_llm_client(provider).chat() / .chat_json() 만 사용.
"""
import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod

import requests

from app.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 추상 기반 클라이언트
# ─────────────────────────────────────────────────────────

class BaseLLMClient(ABC):

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        response_format: dict | None = None,
    ) -> str:
        """messages: [{"role": "user"|"assistant"|"system", "content": "..."}]
        response_format: {"type": "json_object"} 등 OpenAI 호환 포맷 지정 (선택)
        """
        ...

    def chat_json(self, messages: list[dict]) -> dict | list:
        """
        JSON 응답 보장 버전.
        마크다운 코드블록 자동 제거 후 파싱 (안전망).
        응답이 절단된 경우 완전한 객체만 부분 복구.
        파싱 실패 시 ValueError 발생.

        Note: response_format=json_object 는 Bedrock/PwC 엔드포인트에서
        배열을 객체로 감싸서 반환하는 부작용이 있어 사용하지 않음.
        대신 강화된 system prompt로 JSON 준수 유도.
        """
        raw = self.chat(messages, temperature=0.0)
        cleaned = raw.strip()

        # ```json ... ``` 또는 ``` ... ``` 블록 제거
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # 첫 줄(```json 또는 ```) 제거
            lines = lines[1:]
            # 마지막 ``` 제거
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning("LLM JSON 파싱 실패 (%s) — 부분 복구 시도 중...", e)
            # 배열이 절단된 경우: 완전한 JSON 객체만 추출
            recovered = _recover_partial_json_array(cleaned)
            if recovered is not None:
                logger.warning("부분 복구 성공: %d개 객체 추출 (원본 파싱 실패)", len(recovered))
                return recovered
            logger.error("LLM JSON 복구 실패\n응답: %r", raw[:500])
            raise ValueError(f"LLM이 유효한 JSON을 반환하지 않았습니다: {e}") from e

    async def chat_json_async(self, messages: list[dict]) -> dict | list:
        """
        chat_json의 비동기 버전.
        blocking chat_json()을 asyncio.to_thread로 스레드 풀에서 실행.
        여러 주석을 asyncio.gather로 병렬 처리할 때 사용.
        """
        return await asyncio.to_thread(self.chat_json, messages)


def _recover_partial_json_array(text: str) -> list | None:
    """
    절단된 JSON 배열에서 완전한 객체들만 추출.
    예: '[{"a":1}, {"b":2}, {"c":' → [{"a":1}, {"b":2}]
    """
    if not text.strip().startswith("["):
        return None

    objects: list = []
    depth = 0
    in_string = False
    escape_next = False
    obj_start: int | None = None

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    obj = json.loads(text[obj_start: i + 1])
                    objects.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = None

    return objects if objects else None


# ─────────────────────────────────────────────────────────
# 프로바이더 1: PwC Internal LLM (OpenAI-compatible REST)
# ─────────────────────────────────────────────────────────

class PwCLLMClient(BaseLLMClient):
    """
    PwC 내부 엔드포인트 — OpenAI-compatible REST API.
    pwcllm.py의 로직을 클래스로 래핑.
    """

    def __init__(self) -> None:
        self.url = settings.PwC_LLM_URL
        self.headers = {
            "Content-Type": "application/json",
            "api-key": settings.PwC_LLM_API_KEY,
        }
        self.model = settings.PwC_LLM_MODEL

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        response_format: dict | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 65536,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        logger.debug(
            "PwC LLM 호출: model=%s, messages=%d개, json_mode=%s",
            self.model, len(messages), response_format is not None,
        )

        # 재시도 대상 HTTP 상태코드 (일시적 서버 오류)
        RETRYABLE_STATUS = {429, 500, 502, 503, 504}

        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    self.url,
                    headers=self.headers,
                    data=json.dumps(payload, ensure_ascii=False),
                    timeout=600,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                logger.debug("PwC LLM 응답: %d자", len(content))
                return content
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status in RETRYABLE_STATUS and attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1초, 2초, 4초, 8초
                    logger.warning(
                        "PwC LLM HTTP %s 오류 (시도 %d/%d), %d초 후 재시도",
                        status, attempt + 1, max_retries, wait,
                    )
                    time.sleep(wait)
                else:
                    raise
            except requests.exceptions.ConnectionError as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "PwC LLM 연결 오류 (시도 %d/%d), %d초 후 재시도: %s",
                        attempt + 1, max_retries, wait, e,
                    )
                    time.sleep(wait)
                else:
                    raise


# ─────────────────────────────────────────────────────────
# 팩토리 함수
# ─────────────────────────────────────────────────────────

def get_llm_client(provider: str = "pwc") -> BaseLLMClient:
    """PwC Internal LLM 클라이언트 반환."""
    return PwCLLMClient()
