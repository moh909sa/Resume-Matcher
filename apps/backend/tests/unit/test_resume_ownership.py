"""Real database isolation and defaults across verified user scopes."""

import asyncio
import sqlite3

import pytest

from app.database import Database, MasterResumeLimitError, ResumeNotFoundError
from app.resume_ownership import resume_owner

A = "760c63e9-c782-4631-a1fb-471e988740a1"
B = "760c63e9-c782-4631-a1fb-471e988740b2"


@pytest.mark.unit
async def test_defaults_and_lists_are_per_user_including_legacy(
    isolated_db: Database,
) -> None:
    legacy = await isolated_db.create_resume_atomic_master("Legacy")
    with resume_owner(A):
        first = await isolated_db.create_resume_atomic_master(
            "A", processing_status="processing"
        )
    with resume_owner(B):
        second = await isolated_db.create_resume_atomic_master(
            "B", processing_status="processing"
        )
        assert [row["resume_id"] for row in await isolated_db.list_resumes()] == [
            second["resume_id"]
        ]
        assert await isolated_db.get_resume(first["resume_id"]) is None
    with resume_owner(A):
        assert [row["resume_id"] for row in await isolated_db.list_resumes()] == [
            first["resume_id"]
        ]
        assert await isolated_db.get_resume(second["resume_id"]) is None
    assert [row["resume_id"] for row in await isolated_db.list_resumes()] == [
        legacy["resume_id"]
    ]
    assert (
        first["is_default_master"]
        and second["is_default_master"]
        and legacy["is_default_master"]
    )


@pytest.mark.unit
async def test_master_limit_is_not_shared_between_users(isolated_db: Database) -> None:
    with resume_owner(A):
        for i in range(5):
            await isolated_db.create_resume_atomic_master(f"A {i}")
        with pytest.raises(MasterResumeLimitError):
            await isolated_db.create_resume_atomic_master("Sixth")
    with resume_owner(B):
        assert (await isolated_db.create_resume_atomic_master("B"))["is_default_master"]


@pytest.mark.unit
async def test_cross_user_bulk_processing_and_deletion_are_denied(
    isolated_db: Database,
) -> None:
    with resume_owner(A):
        row = await isolated_db.create_resume_atomic_master(
            "A", processing_status="processing"
        )
        token = await isolated_db.claim_resume_processing(row["resume_id"])
    with resume_owner(B):
        with pytest.raises(ResumeNotFoundError):
            await isolated_db.claim_resume_processing(row["resume_id"])
        assert (
            await isolated_db.finish_resume_processing(
                row["resume_id"], token, processing_status="failed"
            )
            == "missing"
        )
        assert not await isolated_db.delete_resume(row["resume_id"])
        assert not await isolated_db.set_default_master_resume(row["resume_id"])
    assert await isolated_db.get_resume(row["resume_id"]) is None
    assert not await isolated_db.delete_resume(row["resume_id"])
    with resume_owner(A):
        assert (
            await isolated_db.finish_resume_processing(
                row["resume_id"], token, processing_status="failed"
            )
            == "committed"
        )


@pytest.mark.unit
async def test_owner_cannot_be_reassigned(isolated_db: Database) -> None:
    with resume_owner(A):
        row = await isolated_db.create_resume_atomic_master("A")
        with pytest.raises(ValueError, match="ownership"):
            await isolated_db.update_resume(row["resume_id"], {"owner_id": B})
        assert await isolated_db.get_resume(row["resume_id"]) is not None
    with resume_owner(B):
        assert await isolated_db.get_resume(row["resume_id"]) is None


@pytest.mark.unit
async def test_concurrent_requests_and_background_contexts_do_not_leak(
    isolated_db: Database,
) -> None:
    async def worker(owner: str) -> str:
        with resume_owner(owner):
            row = await isolated_db.create_resume_atomic_master(owner)
            await asyncio.sleep(0)
            assert {item["resume_id"] for item in await isolated_db.list_resumes()} == {
                row["resume_id"]
            }
            return row["resume_id"]

    first, second = await asyncio.gather(worker(A), worker(B))
    with resume_owner(A):
        pending = asyncio.create_task(isolated_db.get_resume(first))
    with resume_owner(B):
        assert (await pending)["resume_id"] == first
        assert await isolated_db.get_resume(first) is None
        assert (await isolated_db.get_resume(second))["resume_id"] == second


@pytest.mark.unit
async def test_reinitialization_preserves_each_users_default(
    isolated_db: Database,
) -> None:
    rows = {}
    for owner in (A, B):
        with resume_owner(owner):
            rows[owner] = await isolated_db.create_resume_atomic_master(owner)
    await isolated_db.close()
    for owner in (A, B):
        with resume_owner(owner):
            assert (await isolated_db.get_master_resume())["resume_id"] == rows[owner][
                "resume_id"
            ]


@pytest.mark.unit
async def test_private_engine_rows_are_not_in_legacy_file(
    isolated_db: Database,
) -> None:
    with resume_owner(A):
        row = await isolated_db.create_resume_atomic_master("Private customer CV")
    assert isolated_db.db_path is not None
    # Also exercises the unsafe/old client that knows nothing about owner_id.
    with sqlite3.connect(isolated_db.db_path) as legacy:
        assert legacy.execute("select count(*) from resumes").fetchone()[0] == 0
    await isolated_db.reset_database()
    with resume_owner(A):
        assert await isolated_db.get_resume(row["resume_id"]) is not None
