"""Server-only Supabase Auth, private Storage, and CV registry integration."""

import logging
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)
BUCKET = "resume-files"
MAX_ORIGINAL_BYTES = 4 * 1024 * 1024


class SupabaseUnavailable(RuntimeError):
    """The trusted upstream could not complete an operation."""


class InvalidSession(RuntimeError):
    """Supabase Auth rejected the access token."""


class ResumeQuotaExceeded(RuntimeError):
    """An account already holds the allowed number of original CVs."""


class OriginalFileMissing(RuntimeError):
    """A registry entry has no recoverable original object."""


class SupabaseBackend:
    """A request-local HTTP client; the secret stays in its apikey header.

    The user JWT is sent only to Auth /user. It is never substituted for the
    server credential on Storage or database writes (which are server-only).
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            logger.warning(
                "Supabase transport failed: %s %s (%s)",
                method,
                path.split("?")[0],
                type(error).__name__,
            )
            raise SupabaseUnavailable("Storage service unavailable") from error
        if response.status_code == 409 and path.endswith("/reserve_user_resume"):
            raise ResumeQuotaExceeded("Original resume limit reached")
        if response.is_error:
            # Never log response bodies, credentials, file bytes, or user JWTs.
            logger.warning(
                "Supabase request failed: %s %s status=%s",
                method,
                path.split("?")[0],
                response.status_code,
            )
            raise SupabaseUnavailable("Storage service unavailable")
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as error:
            raise SupabaseUnavailable("Invalid storage service response") from error

    async def verify_user(self, access_token: str) -> str:
        """Use the configured project's Auth server, not unverified JWT claims."""
        try:
            response = await self.client.get(
                "/auth/v1/user", headers={"Authorization": f"Bearer {access_token}"}
            )
        except httpx.HTTPError as error:
            raise SupabaseUnavailable("Authentication service unavailable") from error
        if response.status_code in (400, 401, 403, 404):
            raise InvalidSession("Sign in again")
        if response.is_error:
            raise SupabaseUnavailable("Authentication service unavailable")
        data = self._json(response)
        if not isinstance(data, dict):
            raise SupabaseUnavailable("Invalid authentication response")
        if data.get("is_anonymous"):
            raise InvalidSession("A permanent account is required")
        try:
            return str(UUID(data["id"]))
        except (KeyError, ValueError, TypeError, AttributeError) as error:
            raise SupabaseUnavailable("Invalid authentication response") from error

    @staticmethod
    def object_path(user_id: str, resume_id: str, suffix: str) -> str:
        """Keys are generated IDs; a supplied filename never controls a path."""
        if suffix not in (".pdf", ".docx"):
            raise ValueError("Unsupported original file type")
        return f"{UUID(user_id)}/{UUID(resume_id)}/original{suffix}"

    @staticmethod
    def checked_path(record: dict[str, Any], user_id: str) -> str:
        """Refuse unexpected object paths even with a privileged credential."""
        path = record.get("storage_path")
        allowed = {
            SupabaseBackend.object_path(user_id, record["id"], suffix)
            for suffix in (".pdf", ".docx")
        }
        if (
            record.get("user_id") != user_id
            or record.get("storage_bucket") != BUCKET
            or path not in allowed
        ):
            raise SupabaseUnavailable("Invalid original file reference")
        return str(path)

    async def create_record(self, values: dict[str, Any]) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/reserve_user_resume",
            json={
                "p_user_id": values["user_id"],
                "p_resume_id": values["id"],
                "p_filename": values["original_filename"],
                "p_storage_path": values["storage_path"],
                "p_mime_type": values["mime_type"],
                "p_file_size": values["file_size_bytes"],
            },
        )
        rows = self._json(response)
        if not isinstance(rows, list) or len(rows) != 1:
            raise SupabaseUnavailable("Invalid registry response")
        return rows[0]

    async def list_records(self, user_id: str) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            "/rest/v1/user_resumes",
            params={
                "user_id": f"eq.{UUID(user_id)}",
                "select": "*",
                "order": "created_at.desc",
                "limit": "100",
            },
        )
        rows = self._json(response)
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or row.get("user_id") != user_id for row in rows
        ):
            raise SupabaseUnavailable("Invalid registry response")
        return rows

    async def get_record(self, user_id: str, resume_id: str) -> dict[str, Any] | None:
        response = await self._request(
            "GET",
            "/rest/v1/user_resumes",
            params={
                "user_id": f"eq.{UUID(user_id)}",
                "id": f"eq.{UUID(resume_id)}",
                "select": "*",
            },
        )
        rows = self._json(response)
        if not isinstance(rows, list):
            raise SupabaseUnavailable("Invalid registry response")
        if not rows:
            return None
        row = rows[0]
        if (
            not isinstance(row, dict)
            or row.get("user_id") != user_id
            or row.get("id") != resume_id
        ):
            raise SupabaseUnavailable("Invalid registry response")
        return row

    async def update_record(
        self, user_id: str, resume_id: str, values: dict[str, Any]
    ) -> None:
        await self._request(
            "PATCH",
            "/rest/v1/user_resumes",
            params={"user_id": f"eq.{UUID(user_id)}", "id": f"eq.{UUID(resume_id)}"},
            json=values,
        )

    async def delete_record(self, user_id: str, resume_id: str) -> None:
        await self._request(
            "DELETE",
            "/rest/v1/user_resumes",
            params={"user_id": f"eq.{UUID(user_id)}", "id": f"eq.{UUID(resume_id)}"},
        )

    async def sync_records(
        self, user_id: str, snapshot: list[dict[str, Any]], observed_at: str
    ) -> None:
        await self._request(
            "POST",
            "/rest/v1/rpc/sync_user_resume_registry",
            json={
                "p_user_id": str(UUID(user_id)),
                "p_snapshot": snapshot,
                "p_observed_at": observed_at,
            },
        )

    async def upload_original(self, path: str, content: bytes, mime_type: str) -> None:
        await self._request(
            "POST",
            f"/storage/v1/object/{BUCKET}/{quote(path, safe='/')}",
            content=content,
            headers={"Content-Type": mime_type, "x-upsert": "false"},
        )

    async def delete_original(self, path: str) -> None:
        # The Storage API removes bytes and metadata together; never SQL-delete objects.
        await self._request(
            "DELETE", f"/storage/v1/object/{BUCKET}", json={"prefixes": [path]}
        )

    async def download_original(self, path: str) -> bytes:
        try:
            async with self.client.stream(
                "GET",
                f"/storage/v1/object/authenticated/{BUCKET}/{quote(path, safe='/')}",
            ) as response:
                if response.status_code in (400, 404):
                    raise OriginalFileMissing("Original file is unavailable")
                if response.is_error:
                    raise SupabaseUnavailable("Storage service unavailable")
                content = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    content.extend(chunk)
                    if len(content) > MAX_ORIGINAL_BYTES:
                        raise SupabaseUnavailable("Original exceeds the upload limit")
                return bytes(content)
        except httpx.HTTPError as error:
            raise SupabaseUnavailable("Storage service unavailable") from error
