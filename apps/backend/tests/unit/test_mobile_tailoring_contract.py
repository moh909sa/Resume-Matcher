"""Mobile tailoring defaults and user-facing contract regression tests."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from unittest.mock import AsyncMock

from app.routers.mobile_tailoring import (
    MobileTailorRequest,
    _preview_length_options,
    preview_mobile_tailor,
)


def test_defaults_are_full_tailoring_unlimited_pages_and_all_bullets():
    request = MobileTailorRequest(
        resume_id=uuid4(), job_description="Senior engineer required. " * 4
    )
    assert request.max_pages is None
    assert request.max_bullets_per_entry is None
    # Crucial: passing neither preference must SKIP both page fitting and truncation.
    assert _preview_length_options(request) == {}
    assert not hasattr(request, "prompt_id")


def test_optional_explicit_length_limits_are_applied_only_when_requested():
    request = MobileTailorRequest(
        resume_id=uuid4(),
        job_description="Senior engineer required. " * 4,
        max_pages=3,
        max_bullets_per_entry=3,
    )
    options = _preview_length_options(request)
    assert options["max_pages"] == 3
    assert options["max_bullets_per_entry"] == 3
    assert options["page_fit"].pageSize == "A4"

    bullet_only = request.model_copy(update={"max_pages": None})
    assert "page_fit" not in _preview_length_options(bullet_only)
    assert "max_pages" not in _preview_length_options(bullet_only)


@pytest.mark.parametrize("options", [
    {"max_pages": 1},
    {"max_pages": 4},
    {"max_bullets_per_entry": 2},
    {"max_bullets_per_entry": 6},
])
def test_unsupported_preference_rejected(options):
    with pytest.raises(ValidationError):
        MobileTailorRequest(
            resume_id=uuid4(),
            job_description="Senior engineer required. " * 4,
            **options,
        )


def test_short_job_description_is_rejected():
    with pytest.raises(ValidationError):
        MobileTailorRequest(resume_id=uuid4(), job_description="Not enough")


@pytest.mark.asyncio
async def test_unowned_cv_rejected_before_any_ai_call():
    user_id = str(uuid4())
    backend = AsyncMock()
    backend.get_record.return_value = None
    body = MobileTailorRequest(
        resume_id=uuid4(), job_description="Senior engineer required. " * 4
    )
    with pytest.raises(HTTPException) as err:
        await preview_mobile_tailor(body, user_id=user_id, backend=backend)
    assert err.value.status_code == 404
    backend.get_record.assert_awaited_once_with(user_id, str(body.resume_id))
    backend.create_tailored_record.assert_not_called()
