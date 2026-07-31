"""HTTP control seam (FastAPI).

The full-fat server: OpenAPI docs, validation, and uvicorn. Use it on a
desktop or a server. On a phone, `lite.py` implements the same contract with
no compiled dependencies — see docs/on-device.md.

Both servers delegate to routes.py, so this module is transport only.

Security posture: this API can halt trading and is therefore an authenticated
surface by construction. It binds to localhost by default and refuses to start
without a token. Reaching it from another device is a transport problem
(Tailscale, an SSH tunnel, or a TLS reverse proxy), deliberately not solved by
opening the port — see docs/deployment.md.
"""

from __future__ import annotations

import hmac
import logging
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from . import routes
from .routes import ApiFault

if TYPE_CHECKING:
    from ..config import ApiConfig
    from ..runner import TradingRunner

log = logging.getLogger(__name__)

MIN_TOKEN_LENGTH = 24

_bearer = HTTPBearer(auto_error=False)


class ControlResponse(BaseModel):
    ok: bool
    killed: bool
    paused: bool
    message: str


class HealthResponse(BaseModel):
    ok: bool
    version: str
    mode: str


def _as_http(fault: ApiFault) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if fault.status_code == 401 else None
    return HTTPException(status_code=fault.status_code, detail=fault.detail, headers=headers)


def create_app(runner: TradingRunner, config: ApiConfig) -> FastAPI:
    if not config.token:
        raise ValueError("API requires MYP1_API_TOKEN")
    if len(config.token) < MIN_TOKEN_LENGTH:
        raise ValueError(
            f"MYP1_API_TOKEN must be at least {MIN_TOKEN_LENGTH} characters. "
            "This token can halt trading; generate one with "
            "`python -c \"import secrets; print(secrets.token_urlsafe(32))\"`"
        )

    from .. import __version__

    app = FastAPI(
        title="MY-P1 control API",
        version=__version__,
        docs_url="/api/docs" if config.docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if config.docs_enabled else None,
    )

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    # Note: this module uses `from __future__ import annotations`, so a
    # `Depends(...)` carried inside an Annotated[...] type would be stringized
    # and fail to resolve against this local scope — FastAPI would then read
    # the parameter as a query field. The default-value form avoids that.
    async def require_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> None:
        supplied = credentials.credentials if credentials else ""
        # Constant-time compare so a wrong token cannot be discovered by timing.
        if not hmac.compare_digest(supplied, config.token or ""):
            raise _as_http(ApiFault(401, "invalid or missing token"))

    auth = [Depends(require_token)]

    # Limits are validated in routes.py rather than by Query(ge=, le=) so the
    # lite server produces byte-identical errors for the same input.
    def _limit(request: Request) -> str | None:
        return request.query_params.get("limit")

    # -- unauthenticated ------------------------------------------------

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> dict[str, Any]:
        return routes.health(runner)

    # -- read -----------------------------------------------------------

    @app.get("/api/status", dependencies=auth)
    async def get_status() -> dict[str, Any]:
        return routes.status(runner)

    @app.get("/api/position", dependencies=auth)
    async def get_position() -> dict[str, Any]:
        return routes.position(runner)

    @app.get("/api/pnl", dependencies=auth)
    async def get_pnl() -> dict[str, Any]:
        return routes.pnl(runner)

    @app.get("/api/fills", dependencies=auth)
    async def get_fills(request: Request) -> dict[str, Any]:
        try:
            return routes.fills(runner, _limit(request))
        except ApiFault as fault:
            raise _as_http(fault) from None

    @app.get("/api/candles", dependencies=auth)
    async def get_candles(request: Request) -> dict[str, Any]:
        try:
            return await routes.candles(runner, _limit(request))
        except ApiFault as fault:
            raise _as_http(fault) from None

    # -- control --------------------------------------------------------

    @app.post("/api/control/{action}", dependencies=auth, response_model=ControlResponse)
    async def post_control(action: str) -> dict[str, Any]:
        try:
            return routes.control(runner, action)
        except ApiFault as fault:
            raise _as_http(fault) from None

    return app


async def serve(app: FastAPI, host: str, port: int) -> None:
    """Run the API inside the bot's existing event loop."""
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    )
    log.info("control API listening on http://%s:%d", host, port)
    await server.serve()


__all__ = ["create_app", "serve"]
