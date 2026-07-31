"""One contract, two servers.

Every assertion here runs against both the FastAPI server and the stdlib-only
lite server. That is the point: on-device deployment swaps the transport, and
these tests are what guarantee the mobile app cannot tell the difference.

The lite server is exercised over a real socket, not a test client, so HTTP
parsing, status lines and header handling are covered rather than mocked.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from myp1.api import resolve_backend
from myp1.api.lite import LiteApiServer
from myp1.api.server import create_app
from myp1.config import ApiConfig, Config
from myp1.execution.paper import PaperVenue
from myp1.marketdata.replay_source import ReplayMarketData
from myp1.risk.engine import RiskEngine
from myp1.runner import TradingRunner
from myp1.state.journal import Journal
from myp1.strategy.ema_cross import EmaCrossStrategy

from .conftest import make_candles, ramp

TOKEN = "contract-token-long-enough-1234567"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

BACKENDS = ["fastapi", "lite"]


def build_runner(config: Config) -> tuple[TradingRunner, Journal]:
    journal = Journal(config.journal_path)
    runner = TradingRunner(
        config,
        market_data=ReplayMarketData(
            make_candles(ramp(90, 100, 2), config.symbol), warmup=25
        ),
        strategy=EmaCrossStrategy(config.fast_period, config.slow_period),
        risk=RiskEngine(config.risk),
        venue=PaperVenue(config.starting_cash),
        journal=journal,
    )
    return runner, journal


@pytest.fixture(params=BACKENDS)
async def api(request, config):
    """Yield (client, runner) for each backend, over real HTTP for lite."""
    runner, journal = build_runner(config)
    api_config = ApiConfig(enabled=True, host="127.0.0.1", port=0, token=TOKEN)

    if request.param == "fastapi":
        app = create_app(runner, api_config)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client, runner
    else:
        server = LiteApiServer(runner, api_config)
        port = await server.start()
        task = asyncio.create_task(server.serve())
        try:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                yield client, runner
        finally:
            await server.stop()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    journal.close()


# -- authorisation ------------------------------------------------------

@pytest.mark.parametrize(
    "route", ["/api/status", "/api/position", "/api/pnl", "/api/fills", "/api/candles"]
)
async def test_reads_require_a_token(api, route):
    client, _ = api
    assert (await client.get(route)).status_code == 401


@pytest.mark.parametrize("action", ["pause", "resume", "kill", "revive"])
async def test_controls_require_a_token(api, action):
    client, runner = api
    response = await client.post(f"/api/control/{action}")
    assert response.status_code == 401
    assert runner.killed is False
    assert runner.paused is False


async def test_wrong_token_is_rejected(api):
    client, _ = api
    assert (
        await client.get("/api/status", headers={"Authorization": "Bearer wrong"})
    ).status_code == 401


async def test_malformed_auth_header_is_rejected(api):
    client, _ = api
    for header in ["", "Bearer", f"Basic {TOKEN}", TOKEN]:
        response = await client.get("/api/status", headers={"Authorization": header})
        assert response.status_code == 401, header


async def test_health_is_open_and_minimal(api):
    client, _ = api
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert set(body) == {"ok", "version", "mode"}


# -- reads --------------------------------------------------------------

async def test_status_shape(api):
    client, runner = api
    body = (await client.get("/api/status", headers=AUTH)).json()
    assert body["symbol"] == runner.symbol
    assert body["mode"] == "paper"
    assert body["killed"] is False


async def test_position_shape(api):
    client, _ = api
    body = (await client.get("/api/position", headers=AUTH)).json()
    assert set(body) == {
        "symbol", "side", "quantity", "avg_price",
        "mark_price", "unrealized", "realized", "is_flat",
    }


async def test_pnl_shape(api):
    client, _ = api
    body = (await client.get("/api/pnl", headers=AUTH)).json()
    assert set(body) == {
        "realized_today", "realized_total", "unrealized", "net", "orders_today"
    }


async def test_candles_shape(api):
    client, _ = api
    body = (await client.get("/api/candles?limit=40", headers=AUTH)).json()
    assert len(body["candles"]) > 0
    assert set(body["candles"][0]) == {"t", "o", "h", "l", "c", "v"}


@pytest.mark.parametrize(
    "query,expected",
    [
        ("?limit=5", 200),
        ("?limit=200", 200),
        ("?limit=0", 422),
        ("?limit=201", 422),
        ("?limit=-1", 422),
        ("?limit=abc", 422),
        ("", 200),
    ],
)
async def test_fills_limit_bounds_agree(api, query, expected):
    client, _ = api
    assert (await client.get(f"/api/fills{query}", headers=AUTH)).status_code == expected


@pytest.mark.parametrize(
    "query,expected",
    [("?limit=10", 200), ("?limit=500", 200), ("?limit=9", 422), ("?limit=501", 422)],
)
async def test_candles_limit_bounds_agree(api, query, expected):
    client, _ = api
    assert (await client.get(f"/api/candles{query}", headers=AUTH)).status_code == expected


async def test_unknown_route_is_404(api):
    client, _ = api
    assert (await client.get("/api/nope", headers=AUTH)).status_code == 404


# -- control ------------------------------------------------------------

async def test_pause_resume_cycle(api):
    client, runner = api
    body = (await client.post("/api/control/pause", headers=AUTH)).json()
    assert body["paused"] is True
    assert runner.paused is True

    body = (await client.post("/api/control/resume", headers=AUTH)).json()
    assert body["paused"] is False


async def test_kill_and_revive(api):
    client, runner = api
    body = (await client.post("/api/control/kill", headers=AUTH)).json()
    assert body["killed"] is True
    assert runner.killed is True
    assert runner.journal.get_control("kill_switch") is True

    body = (await client.post("/api/control/revive", headers=AUTH)).json()
    assert body["killed"] is False


async def test_resume_while_killed_is_409(api):
    client, _ = api
    await client.post("/api/control/kill", headers=AUTH)
    response = await client.post("/api/control/resume", headers=AUTH)
    assert response.status_code == 409
    assert "kill switch" in response.json()["detail"]


async def test_unknown_control_action_is_404(api):
    client, _ = api
    assert (await client.post("/api/control/explode", headers=AUTH)).status_code == 404


async def test_control_response_shape(api):
    client, _ = api
    body = (await client.post("/api/control/pause", headers=AUTH)).json()
    assert set(body) == {"ok", "killed", "paused", "message"}


# -- backend resolution -------------------------------------------------

def test_auto_prefers_fastapi_when_installed():
    assert resolve_backend("auto") == "fastapi"


def test_lite_can_be_forced():
    assert resolve_backend("lite") == "lite"


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError):
        resolve_backend("something-else")


async def test_lite_refuses_a_short_token(config):
    runner, journal = build_runner(config)
    with pytest.raises(ValueError, match="at least"):
        LiteApiServer(runner, ApiConfig(enabled=True, token="tiny"))
    journal.close()


async def test_lite_survives_a_garbage_request(config):
    """A malformed request must not take the server down with the bot."""
    runner, journal = build_runner(config)
    server = LiteApiServer(runner, ApiConfig(enabled=True, host="127.0.0.1", port=0, token=TOKEN))
    port = await server.start()
    task = asyncio.create_task(server.serve())
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"this is not http\r\n\r\n")
        await writer.drain()
        await reader.read(64)
        writer.close()

        # Still serving afterwards.
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            assert (await client.get("/api/health")).status_code == 200
    finally:
        await server.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        journal.close()
