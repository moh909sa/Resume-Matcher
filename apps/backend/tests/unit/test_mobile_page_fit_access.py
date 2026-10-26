"""Print draft route is available only to container-loopback rendering requests."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

from app.config import settings
from app.mobile_access import MobileApiGuardMiddleware


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client_host", "path", "method", "expected"),
    [
        ("127.0.0.1", "/api/v1/resumes/render-drafts/" + "a" * 32, "GET", 200),
        ("::1", "/api/v1/resumes/render-drafts/" + "a" * 32, "GET", 200),
        ("198.51.100.23", "/api/v1/resumes/render-drafts/" + "a" * 32, "GET", 404),
        ("127.0.0.1", "/api/v1/resumes/render-drafts/" + "x" * 32, "GET", 404),
        ("127.0.0.1", "/api/v1/resumes/render-drafts/" + "a" * 32, "POST", 404),
        ("127.0.0.1", "/api/v1/resumes/list", "GET", 404),
        ("198.51.100.23", "/api/v1/health", "GET", 200),
    ],
)
async def test_mobile_guard_page_fit_access(monkeypatch, client_host, path, method, expected):
    monkeypatch.setattr(settings, "mobile_api_enabled", True)

    async def app(scope, receive, send):
        await JSONResponse({"ok": True})(scope, receive, send)

    transport = ASGITransport(
        app=MobileApiGuardMiddleware(app), client=(client_host, 1234)
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path)
    assert response.status_code == expected
