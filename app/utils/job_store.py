"""
임시 작업 상태 저장소 (in-memory).
서버 재시작 시 초기화됨. 프로덕션에서는 Redis 등으로 교체 가능.
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Literal

from app.config import settings

logger = logging.getLogger(__name__)

JobStatus = Literal["processing", "completed", "failed"]

# job_id → job dict
_store: dict[str, dict[str, Any]] = {}
_lock = asyncio.Lock()

MAX_LOGS = 200  # 최대 로그 보관 수


def create_job(job_id: str, provider: str) -> dict:
    job = {
        "job_id": job_id,
        "status": "processing",
        "progress": 0,
        "step": "작업을 시작하는 중...",
        "provider": provider,
        "error": None,
        "output_path": None,
        "created_at": time.time(),
        "logs": [],  # {"time": "HH:MM:SS", "msg": str}
    }
    _store[job_id] = job
    return job


def get_job(job_id: str) -> dict | None:
    return _store.get(job_id)


def append_log(job_id: str, msg: str) -> None:
    """로그 항목 추가. step 변경 외 중요 이벤트에도 직접 호출 가능."""
    if job_id not in _store:
        return
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg}
    logs: list = _store[job_id].setdefault("logs", [])
    logs.append(entry)
    if len(logs) > MAX_LOGS:
        _store[job_id]["logs"] = logs[-MAX_LOGS:]


def update_job(job_id: str, **kwargs) -> None:
    if job_id not in _store:
        logger.warning("update_job: job_id=%s 없음", job_id)
        return
    # step이 바뀌면 자동으로 로그에도 기록
    if "step" in kwargs and kwargs["step"]:
        append_log(job_id, kwargs["step"])
    _store[job_id].update(kwargs)


def complete_job(job_id: str, output_path: str) -> None:
    append_log(job_id, "Excel 파일 생성 완료 — 다운로드 가능합니다.")
    update_job(job_id, status="completed", progress=100, step="완료", output_path=output_path)


def fail_job(job_id: str, error: str) -> None:
    append_log(job_id, f"오류 발생: {error}")
    update_job(job_id, status="failed", error=error, step="오류 발생")


def cleanup_expired_jobs() -> int:
    """TTL 초과 job 정리. 반환값: 삭제된 job 수."""
    ttl_sec = settings.JOB_TTL_MINUTES * 60
    now = time.time()
    expired = [
        jid for jid, job in list(_store.items())
        if now - job.get("created_at", now) > ttl_sec
    ]
    for jid in expired:
        del _store[jid]
    if expired:
        logger.info("만료된 job %d개 정리 완료", len(expired))
    return len(expired)
