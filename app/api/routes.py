"""
FastAPI 라우터 — /api/upload, /api/status/{job_id}, /api/download/{job_id}
"""
import asyncio
import logging
import uuid
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.services.dsd_service       import parse_dsd_file
from app.services.en_doc_service    import parse_en_file
from app.services.excel_service     import generate_excel
from app.services.mapping_service   import map_notes
from app.services.reconcile_service import reconcile_all
from app.utils.job_store import (
    append_log,
    cleanup_expired_jobs,
    complete_job,
    create_job,
    fail_job,
    get_job,
    update_job,
)
from app.utils.llm_client import get_llm_client

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# POST /api/upload
# ─────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload(
    background_tasks: BackgroundTasks,
    dsd_file: UploadFile = File(..., description="국문 DSD 파일 (.dsd)"),
    en_file:  UploadFile = File(..., description="영문 재무제표 (.docx 또는 .pdf)"),
):
    # 파일 크기 제한 확인
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024

    # 만료된 job 정리 (요청마다 가볍게 실행)
    cleanup_expired_jobs()

    # job 생성 및 파일 저장
    job_id = str(uuid.uuid4())
    job = create_job(job_id, "pwc")

    uploads_dir = settings.uploads_dir / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # 파일명 None 방어 (일부 브라우저/클라이언트에서 filename이 None으로 올 수 있음)
    dsd_filename = dsd_file.filename or "upload.dsd"
    en_filename  = en_file.filename  or "upload.docx"

    dsd_path = uploads_dir / dsd_filename
    en_path  = uploads_dir / en_filename

    dsd_content = await dsd_file.read()
    en_content  = await en_file.read()

    if len(dsd_content) > max_bytes or len(en_content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"파일 크기는 {settings.MAX_FILE_SIZE_MB}MB 이하여야 합니다.")

    dsd_path.write_bytes(dsd_content)
    en_path.write_bytes(en_content)

    # 백그라운드로 처리 시작
    background_tasks.add_task(_run_reconciliation, job_id, dsd_path, en_path, "pwc")

    return {"job_id": job_id, "status": "processing", "message": "작업이 시작되었습니다."}


# ─────────────────────────────────────────────────────────────────
# GET /api/status/{job_id}
# ─────────────────────────────────────────────────────────────────

@router.get("/status/{job_id}")
async def get_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="해당 job_id를 찾을 수 없습니다.")

    return {
        "job_id":   job["job_id"],
        "status":   job["status"],
        "progress": job["progress"],
        "step":     job["step"],
        "error":    job["error"],
        "logs":     job.get("logs", []),
    }


# ─────────────────────────────────────────────────────────────────
# GET /api/download/{job_id}
# ─────────────────────────────────────────────────────────────────

@router.get("/download/{job_id}")
async def download(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="해당 job_id를 찾을 수 없습니다.")

    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"아직 완료되지 않은 작업입니다. 현재 상태: {job['status']}")

    output_path = job.get("output_path")
    if not output_path or not Path(output_path).exists():
        raise HTTPException(status_code=404, detail="출력 파일을 찾을 수 없습니다.")

    filename = Path(output_path).name
    return FileResponse(
        path=output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────
# 백그라운드 작업
# ─────────────────────────────────────────────────────────────────

async def _run_reconciliation(
    job_id: str,
    dsd_path: Path,
    en_path: Path,
    provider: str,
) -> None:
    """
    실제 대사 처리 파이프라인.
    진행 상황을 job_store에 업데이트하며 실행.
    """
    def progress(pct: int, msg: str) -> None:
        update_job(job_id, progress=pct, step=msg)

    try:
        append_log(job_id, "처리 파이프라인 시작")
        llm_client = get_llm_client(provider)

        # Step 1: DSD 파싱 (5%)
        progress(5, "DSD 파일 변환 중...")
        kr_notes = await parse_dsd_file(dsd_path, llm_client)
        msg1 = f"DSD 파싱 완료: 주석 {len(kr_notes)}개 감지"
        logger.info("[%s] %s", job_id, msg1)
        append_log(job_id, msg1)

        # Step 2: 영문 문서 파싱 (15%)
        progress(15, "영문 재무제표 파싱 중...")
        en_doc = await parse_en_file(en_path)
        msg2 = f"영문 문서 파싱 완료: Note {len(en_doc.notes)}개 (포맷: {en_doc.format.value.upper()})"
        logger.info("[%s] %s", job_id, msg2)
        append_log(job_id, msg2)

        # Step 3: 주석 매핑 (20%)
        progress(20, "주석 매핑 중...")
        mappings = await map_notes(kr_notes, en_doc, llm_client)
        msg3 = f"주석 매핑 완료: 국문↔영문 {len(mappings)}쌍"
        logger.info("[%s] %s", job_id, msg3)
        append_log(job_id, msg3)

        # Step 4: 대사 (20~90%, reconcile_all 내부에서 진행률 업데이트)
        def progress_with_log(pct: int, msg: str) -> None:
            update_job(job_id, progress=pct, step=msg)

        def warn_log(msg: str) -> None:
            logger.warning("[%s] %s", job_id, msg)
            append_log(job_id, msg)

        results = await reconcile_all(
            mappings, llm_client,
            progress_cb=progress_with_log,
            warn_cb=warn_log,
        )
        msg4 = f"LLM 대사 완료: {len(results)}개 주석 처리됨"
        logger.info("[%s] %s", job_id, msg4)
        append_log(job_id, msg4)

        # Step 5: Excel 생성 (95%)
        progress(95, "Excel 파일 생성 중...")
        company_name = _extract_company_name(kr_notes)
        output_path = await generate_excel(
            results=results,
            mappings=mappings,
            company_name=company_name,
            output_dir=settings.outputs_dir,
        )
        logger.info("[%s] Excel 저장: %s", job_id, output_path)

        complete_job(job_id, str(output_path))

    except Exception as exc:
        logger.exception("[%s] 처리 중 오류 발생", job_id)
        fail_job(job_id, str(exc))
    finally:
        # 임시 업로드 파일 정리 (오류 여부 무관)
        try:
            import shutil
            shutil.rmtree(dsd_path.parent, ignore_errors=True)
        except Exception:
            pass


def _extract_company_name(kr_notes) -> str:
    """DSDNote의 source_filename에서 회사명 추출 (없으면 "Unknown")."""
    if kr_notes:
        fname = kr_notes[0].source_filename
        # 예: "DSD_GWSS.dsd" → "GWSS"
        stem = Path(fname).stem
        parts = stem.split("_")
        if len(parts) > 1:
            return "_".join(parts[1:])
        return stem
    return "Unknown"
