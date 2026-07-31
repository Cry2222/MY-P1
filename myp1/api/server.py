"""HTTP control seam.

The mobile app talks to the bot through this and nothing else. It is the same
shape as the Telegram gateway — a view onto the runner plus a remote for its
control state — and like the gateway it holds no trading logic of its own.

Security posture: this API can halt trading and is therefore an authenticated
surface by construction. It binds to localhost by default and refuses to start
without a token. Reaching it from a phone is a transport problem (Tailscale, an
SSH tunnel, or a TLS reverse proxy), deliberately not solved by opening the
port — see docs/deployment.md.
"""

from __future__ import annotations

import hmac
import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from ..config import ApiConfig

if TYPE_CHECKING:
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
            allow_origins=config.cors_origins,
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    auth = [Depends(require_token)]

    # -- unauthenticated ------------------------------------------------

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Liveness only. Deliberately leaks nothing about the account."""
        return HealthResponse(
            ok=True,
            version=__version__,
            mode="live" if runner.config.is_live else "paper",
        )

    # -- read -----------------------------------------------------------

    @app.get("/api/status", dependencies=auth)
    async def get_status() -> dict[str, Any]:
        return runner.status()

    @app.get("/api/position", dependencies=auth)
    async def get_position() -> dict[str, Any]:
        p = runner.position
        return {
            "symbol": p.symbol,
            "side": p.exposure.value,
            "quantity": p.quantity,
            "avg_price": p.avg_price,
            "mark_price": runner.last_price,
            "unrealized": p.unrealized_pnl(runner.last_price),
            "realized": p.realized_pnl,
            "is_flat": p.is_flat,
        }

    @app.get("/api/pnl", dependencies=auth)
    async def get_pnl() -> dict[str, Any]:
        s = runner.status()
        return {
            "realized_today": s["realized_today"],
            "realized_total": s["realized_total"],
            "unrealized": s["unrealized"],
            "net": s["realized_total"] + s["unrealized"],
            "orders_today": s["orders_today"],
        }

    @app.get("/api/fills", dependencies=auth)
    async def get_fills(
        limit: Annotated[int, Query(ge=1, le=200)] = 25,
    ) -> dict[str, Any]:
        return {"fills": runner.journal.recent_fills(limit=limit)}

    @app.get("/api/candles", dependencies=auth)
    async def get_candles(
        limit: Annotated[int, Query(ge=10, le=500)] = 100,
    ) -> dict[str, Any]:
        """Recent candles, so the app can draw a chart without its own feed."""
        try:
            candles = await runner.market_data.fetch_candles(
                runner.symbol, runner.config.timeframe, limit=limit
            )
        except Exception as exc:
            log.warning("candle fetch failed for API: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="market data unavailable",
            ) from exc
        return {
            "symbol": runner.symbol,
            "timeframe": runner.config.timeframe,
            "candles": [
                {
                    "t": c.timestamp, "o": c.open, "h": c.high,
                    "l": c.low, "c": c.close, "v": c.volume,
                }
                for c in candles
            ],
        }

    # -- control --------------------------------------------------------

    def _control(message: str) -> ControlResponse:
        return ControlResponse(
            ok=True, killed=runner.killed, paused=runner.paused, message=message
        )

    @app.post("/api/control/pause", dependencies=auth, response_model=ControlResponse)
    async def pause() -> ControlResponse:
        runner.pause()
        return _control("Paused. Open positions can still exit.")

    @app.post("/api/control/resume", dependencies=auth, response_model=ControlResponse)
    async def resume() -> ControlResponse:
        if runner.killed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="kill switch is engaged; revive first",
            )
        runner.resume()
        return _control("Resumed.")

    @app.post("/api/control/kill", dependencies=auth, response_model=ControlResponse)
    async def kill() -> ControlResponse:
        runner.kill("api")
        return _control("Kill switch engaged. No orders will be placed, including exits.")

    @app.post("/api/control/revive", dependencies=auth, response_model=ControlResponse)
    async def revive() -> ControlResponse:
        runner.revive()
        return _control("Kill switch released.")

    return app


async def serve(app: FastAPI, host: str, port: int) -> None:
    """Run the API inside the bot's existing event loop."""
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    )
    log.info("control API listening on http://%s:%d", host, port)
    await server.serve()
