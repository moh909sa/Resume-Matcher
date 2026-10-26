"""Mobile tailoring defaults and user-facing contract regression tests."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from unittest.mock import AsyncMock

from app.routers.mobile_tailoring import MobileTailorRequest, preview_mobile_tailor


def test_defaults_are_full_tailoring_two_pages_five_bullets():
    request = MobileTailorRequest(
        resume_id=uuid4(), job_description="Senior engineer required. " * 4
    )
    assert request.max_pages == 2
    assert request.max_bullets_per_entry == 5
    assert not hasattr(request, "prompt_id")


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
