"""Authenticated mobile CV tailoring: user-owned preview, explicit approval, and library."""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.ai_budget import AIOperationRoute
from app.database import db
from app.mobile_access import current_user, supabase_backend
from app.resume_ownership import resume_owner
from app.routers.resumes import (
    improve_resume_confirm_endpoint,
    improve_resume_preview_endpoint,
)
from app.schemas.models import (
    ImproveResumeConfirmRequest,
    ImproveResumeRequest,
    PageFitSettings,
)
from app.services.supabase_backend import SupabaseBackend

router = APIRouter(prefix="/mobile", tags=["mobile-tailoring"], route_class=AIOperationRoute)


class MobileTailorRequest(BaseModel):
    """Full tailoring is a server-enforced choice; clients may change only length."""

    resume_id: UUID
    job_description: str = Field(min_length=50, max_length=12000)
    max_pages: Literal[2, 3] = 2
    max_bullets_per_entry: Literal[3, 5] = 5

    @field_validator("job_description")
    @classmethod
    def normalize_description(cls, text: str) -> str:
        text = text.strip()
        if len(text) < 50:
            raise ValueError("Paste at least 50 characters from the job posting")
        return text


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    """Do not send full job text and CV contents in a library-list response."""
    return {
        key: record.get(key)
        for key in (
            "id", "source_resume_id", "engine_resume_id", "job_title", "company",
            "max_pages", "max_bullets_per_entry", "prompt_id", "status",
            "created_at", "updated_at",
        )
    }


async def _owned_tailoring(
    backend: SupabaseBackend, user_id: str, tailoring_id: UUID
) -> dict[str, Any]:
    record = await backend.get_tailored_record(user_id, str(tailoring_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Tailored CV not found")
    return record


@router.post("/tailor/preview", status_code=201)
async def preview_mobile_tailor(
    body: MobileTailorRequest,
    user_id: str = Depends(current_user),
    backend: SupabaseBackend = Depends(supabase_backend),
) -> dict[str, Any]:
    """Generate a factual, unsaved preview using the existing full-tailoring engine."""
    source_id = str(body.resume_id)
    if await backend.get_record(user_id, source_id) is None:
        raise HTTPException(status_code=404, detail="Original CV not found")

    with resume_owner(user_id):
        source = await db.get_resume(source_id)
        if source is None or source.get("processing_status") != "ready":
            raise HTTPException(status_code=409, detail="CV must be Ready before tailoring")

        # All jobs are server-created under a verified source. No arbitrary job IDs
        # from a mobile client are ever accepted by this endpoint.
        jobs = await db.create_jobs([body.job_description], resume_id=source_id)
        job_id = jobs[0]["job_id"]
        try:
            preview = await improve_resume_preview_endpoint(
                ImproveResumeRequest(
                    resume_id=source_id,
                    job_id=job_id,
                    prompt_id="full",
                    max_pages=body.max_pages,
                    max_bullets_per_entry=body.max_bullets_per_entry,
                    page_fit=PageFitSettings(template="swiss-single", pageSize="A4"),
                )
            )
            data = preview.data.model_dump(mode="json")
            if not data.get("preview_id"):
                raise HTTPException(status_code=503, detail="Tailoring preview was not registered")
            stored = await backend.create_tailored_record({
                "user_id": user_id,
                "source_resume_id": source_id,
                "job_id": job_id,
                "job_description": body.job_description,
                "job_title": (await db.get_job(job_id) or {}).get("role"),
                "company": (await db.get_job(job_id) or {}).get("company"),
                "max_pages": body.max_pages,
                "max_bullets_per_entry": body.max_bullets_per_entry,
                "prompt_id": "full",
                "status": "draft",
                "preview_id": data["preview_id"],
                "preview_expires_at": data.get("preview_expires_at"),
                "preview_json": data,
            })
        except Exception:
            # Do not leave a job if its preview cannot be used by the mobile app.
            await db.delete_job(job_id)
            raise
    return {"tailoring_id": stored["id"], "status": "draft", "preview": data,
            "preferences": {"max_pages": body.max_pages,
                            "max_bullets_per_entry": body.max_bullets_per_entry,
                            "tailoring_intensity": "full"}}


@router.post("/tailor/{tailoring_id}/confirm")
async def confirm_mobile_tailor(
    tailoring_id: UUID,
    user_id: str = Depends(current_user),
    backend: SupabaseBackend = Depends(supabase_backend),
) -> dict[str, Any]:
    """Approve exactly the saved server-generated preview, not client-authored facts."""
    record = await _owned_tailoring(backend, user_id, tailoring_id)
    if record["status"] == "ready":
        return {"tailoring_id": record["id"], "status": "ready",
                "tailored_cv": record.get("result_json")}
    if record["status"] != "draft":
        raise HTTPException(status_code=409, detail="Tailoring is not ready for confirmation")
    source_id = record.get("source_resume_id")
    if not source_id or await backend.get_record(user_id, source_id) is None:
        raise HTTPException(status_code=409, detail="The original CV is no longer available")
    expires = record.get("preview_expires_at")
    if expires and datetime.fromisoformat(expires.replace("Z", "+00:00")) < datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Preview expired. Create a new preview")

    saved = record.get("preview_json") or {}
    if not saved.get("preview_id") or saved.get("preview_id") != record.get("preview_id"):
        raise HTTPException(status_code=409, detail="Stored preview is incomplete")

    with resume_owner(user_id):
        source = await db.get_resume(source_id)
        job = await db.get_job(record["job_id"])
        if not source or not job or job.get("resume_id") != source_id:
            raise HTTPException(status_code=409, detail="Preview source is no longer available")
        result = await improve_resume_confirm_endpoint(
            ImproveResumeConfirmRequest(
                resume_id=source_id,
                job_id=record["job_id"],
                preview_id=record["preview_id"],
                improved_data=saved["resume_preview"],
                improvements=saved.get("improvements", []),
            )
        )
        output = result.data.model_dump(mode="json")
        engine_id = output.get("resume_id")
        if not engine_id:
            raise HTTPException(status_code=503, detail="Tailored CV was not saved")
        # Engine confirmation is idempotent; retry this call after transient
        # Supabase failures to persist the already-confirmed result.
        await backend.update_tailored_record(user_id, str(tailoring_id), {
            "engine_resume_id": str(UUID(engine_id)),
            "status": "ready",
            "result_json": output,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    return {"tailoring_id": str(tailoring_id), "status": "ready", "tailored_cv": output}


@router.get("/tailored-cvs")
async def list_mobile_tailored_cvs(
    user_id: str = Depends(current_user),
    backend: SupabaseBackend = Depends(supabase_backend),
) -> list[dict[str, Any]]:
    return [_summary(row) for row in await backend.list_tailored_records(user_id)]


@router.get("/tailored-cvs/{tailoring_id}")
async def get_mobile_tailored_cv(
    tailoring_id: UUID,
    user_id: str = Depends(current_user),
    backend: SupabaseBackend = Depends(supabase_backend),
) -> dict[str, Any]:
    return await _owned_tailoring(backend, user_id, tailoring_id)
