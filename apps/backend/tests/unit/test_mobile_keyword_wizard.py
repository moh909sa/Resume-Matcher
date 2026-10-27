"""Contract tests for the mobile three-step keyword wizard."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import mobile_tailoring as mobile


def test_review_has_original_engine_score_keywords_and_grouped_changes():
    preview = {
        "preview_id": "new",
        "ats_score": {
            "overall_score": 61.5,
            "injectable_keywords": ["Ethernet/IP", "Modbus RTU"],
            "missing_keywords": ["Ethernet/IP", "OPC-UA"],
        },
        "forced_keywords": ["Ethernet/IP"],
        "_mobile": {"ats_history": [53.1, 61.5]},
        "diff_summary": {"skills_added": 4, "descriptions_modified": 3,
                         "high_risk_changes": 4},
        "detailed_changes": [{"field_type": "summary", "original_value": "old",
                              "new_value": "new"},
                             {"field_type": "description", "original_value": "x",
                              "new_value": "y"}],
    }
    output = mobile._review_ui(preview)
    assert output["step_order"] == ["keywords", "changes", "confirm"]
    assert output["keyword_options"]["supported"] == ["Modbus RTU"]
    assert output["keyword_options"]["needs_attestation"] == ["OPC-UA"]
    assert output["keyword_options"]["applied"] == ["Ethernet/IP"]
    assert output["score_history"] == [53.1, 61.5]
    assert output["change_summary"]["skills_added"] == 4
    assert [x["type"] for x in output["change_sections"]] == ["summary", "description"]


@pytest.mark.parametrize("keywords", [[], [{"keyword": "x", "attested": True}] * 31])
def test_keyword_request_limits(keywords):
    with pytest.raises(ValidationError):
        mobile.MobileApplyKeywordsRequest(expected_preview_id="abc", keywords=keywords)


@pytest.mark.asyncio
async def test_unowned_review_is_404():
    backend = AsyncMock()
    backend.get_tailored_record.return_value = None
    with pytest.raises(HTTPException) as err:
        await mobile.get_mobile_tailor_review(
            uuid4(), user_id=str(uuid4()), backend=backend)
    assert err.value.status_code == 404


@pytest.mark.asyncio
async def test_stale_preview_cannot_claim_or_apply():
    backend = AsyncMock()
    backend.get_tailored_record.return_value = {
        "status": "draft", "preview_id": "new", "preview_json": {}
    }
    with pytest.raises(HTTPException) as err:
        await mobile.apply_mobile_tailor_keywords(
            uuid4(),
            mobile.MobileApplyKeywordsRequest(
                expected_preview_id="old",
                keywords=[{"keyword": "OPC-UA", "attested": True}]),
            user_id=str(uuid4()), backend=backend)
    assert err.value.status_code == 409
    backend.claim_tailored_operation.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_attestation_required_for_new_skill():
    user_id, source_id, tailoring_id, job_id = map(str, [uuid4() for _ in range(4)])
    backend = AsyncMock()
    backend.get_tailored_record.return_value = {
        "status": "draft", "preview_id": "preview-A", "job_id": job_id,
        "source_resume_id": source_id,
        "preview_json": {
            "preview_id": "preview-A", "resume_preview": {"test": "structured"},
            "ats_score": {"missing_keywords": ["OPC-UA"],
                          "injectable_keywords": []},
        },
        "preview_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    with pytest.raises(HTTPException) as err:
        await mobile.apply_mobile_tailor_keywords(
            uuid4(), mobile.MobileApplyKeywordsRequest(
                expected_preview_id="preview-A",
                keywords=[{"keyword": "OPC-UA", "attested": False}]),
            user_id=user_id, backend=backend)
    assert err.value.status_code == 422
    backend.claim_tailored_operation.assert_not_called()


@pytest.mark.asyncio
async def test_apply_updates_latest_preview_without_modifying_original(monkeypatch):
    user_id, source_id, tailoring_id, job_id = map(str, [uuid4() for _ in range(4)])
    backend = AsyncMock()
    backend.get_tailored_record.return_value = {
        "status": "draft", "preview_id": "preview-A", "job_id": job_id,
        "source_resume_id": source_id,
        "preview_json": {
            "preview_id": "preview-A", "resume_preview": {"mock": "resume"},
            "ats_score": {"overall_score": 53.1, "missing_keywords": ["OPC-UA"],
                          "injectable_keywords": []},
            "_mobile": {"ats_history": [53.1]},
        },
        "preview_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    backend.claim_tailored_operation.return_value = str(uuid4())
    monkeypatch.setattr(mobile, "resume_owner", lambda owner: nullcontext())
    monkeypatch.setattr(mobile.db, "get_resume", AsyncMock(return_value={"id": source_id}))
    monkeypatch.setattr(mobile.db, "get_job",
                        AsyncMock(return_value={"resume_id": source_id}))
    monkeypatch.setattr(mobile.ResumeData, "model_validate", lambda value: value)
    monkeypatch.setattr(mobile, "ApplyKeywordsRequest", lambda **kwargs: kwargs)
    next_data = {
        "preview_id": "preview-B",
        "preview_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "resume_preview": {"mock": "new resume"},
        "ats_score": {"overall_score": 61.5, "missing_keywords": [],
                      "injectable_keywords": []},
        "forced_keywords": ["OPC-UA"],
        "keyword_placements": [{"keyword": "OPC-UA", "paths": ["technicalSkills"]}],
    }
    monkeypatch.setattr(mobile, "apply_keywords_endpoint", AsyncMock(
        return_value=SimpleNamespace(data=SimpleNamespace(
            model_dump=lambda mode: dict(next_data)))))
    result = await mobile.apply_mobile_tailor_keywords(
        uuid4(), mobile.MobileApplyKeywordsRequest(
            expected_preview_id="preview-A",
            keywords=[{"keyword": "OPC-UA", "attested": True}]),
        user_id=user_id, backend=backend)
    assert result["preview"]["preview_id"] == "preview-B"
    assert result["review"]["score_history"] == [53.1, 61.5]
    assert result["review"]["keyword_options"]["applied"] == ["OPC-UA"]
    assert backend.finish_tailored_operation.await_count == 1
    changes = backend.finish_tailored_operation.await_args.args[3]
    assert changes["preview_id"] == "preview-B"
    assert "original_cv" not in changes
    backend.release_tailored_operation.assert_awaited_once()
