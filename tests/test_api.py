"""Control API tests.

This surface can halt trading, so authorisation is tested on every route
rather than sampled.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from myp1.api.server import create_app
from myp1.config import ApiConfig, Config, ConfigError
from myp1.execution.paper import PaperVenue
from myp1.marketdata.replay_source import ReplayMarketData
from myp1.risk.engine import RiskEngine
from myp1.runner import TradingRunner
from myp1.state.journal import Journal
from myp1.strategy.ema_cross import EmaCrossStrategy

from .conftest import make_candles, ramp

TOKEN = "test-token-that-is-long-enough-123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

READ_ROUTES = ["/api/status", "/api/position", "/api/pnl", "/api/fills"]
CONTROL_ROUTES = [
    "/api/control/pause",
    "/api/control/resume",
    "/api/control/kill",
    "/api/control/revive",
]


@pytest.fixture
def runner(config: Config):
    journal = Journal(config.journal_path)
    r = TradingRunner(
        config,
        market_data=ReplayMarketData(make_candles(ramp(80, 100, 2), config.symbol), warmup=20),
        strategy=EmaCrossStrategy(config.fast_period, config.slow_period),
        risk=RiskEngine(config.risk),
        venue=PaperVenue(config.starting_cash),
        journal=journal,
    )
    yield r
    journal.close()


@pytest.fixture
def client(runner):
    app = create_app(runner, ApiConfig(enabled=True, token=TOKEN))
    with TestClient(app) as c:
        yield c


# -- authorisation ------------------------------------------------------

def test_health_needs_no_token(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_health_does_not_leak_account_detail(client):
    body = client.get("/api/health").json()
    assert set(body) == {"ok", "version", "mode"}


@pytest.mark.parametrize("route", READ_ROUTES)
def test_read_routes_reject_a_missing_token(client, route):
    assert client.get(route).status_code == 401


@pytest.mark.parametrize("route", CONTROL_ROUTES)
def test_control_routes_reject_a_missing_token(client, route):
    assert client.post(route).status_code == 401


@pytest.mark.parametrize("route", CONTROL_ROUTES)
def test_control_routes_reject_a_wrong_token(client, route):
    assert client.post(route, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_a_wrong_token_cannot_halt_trading(client, runner):
    client.post("/api/control/kill", headers={"Authorization": "Bearer wrong"})
    assert runner.killed is False


# -- construction guards ------------------------------------------------

def test_app_refuses_to_build_without_a_token(runner):
    with pytest.raises(ValueError, match="MYP1_API_TOKEN"):
        create_app(runner, ApiConfig(enabled=True, token=None))


def test_app_refuses_a_short_token(runner):
    with pytest.raises(ValueError, match="at least"):
        create_app(runner, ApiConfig(enabled=True, token="short"))


def test_config_refuses_to_enable_the_api_without_a_token():
    with pytest.raises(ConfigError, match="MYP1_API_TOKEN"):
        Config(api=ApiConfig(enabled=True)).validate()


def test_docs_are_off_by_default(client):
    assert client.get("/api/docs").status_code == 404


def test_docs_can_be_opted_into(runner):
    app = create_app(runner, ApiConfig(enabled=True, token=TOKEN, docs_enabled=True))
    with TestClient(app) as c:
        assert c.get("/api/docs").status_code == 200


# -- reads --------------------------------------------------------------

def test_status_reports_the_runner(client, runner):
    body = client.get("/api/status", headers=AUTH).json()
    assert body["mode"] == "paper"
    assert body["symbol"] == runner.symbol
    assert body["killed"] is False


def test_position_is_flat_before_trading(client):
    body = client.get("/api/position", headers=AUTH).json()
    assert body["is_flat"] is True
    assert body["quantity"] == 0.0


@pytest.mark.asyncio
async def test_position_reflects_a_real_fill(runner):
    for _ in range(12):
        if (await runner.tick()).fill:
            break
    app = create_app(runner, ApiConfig(enabled=True, token=TOKEN))
    with TestClient(app) as c:
        body = c.get("/api/position", headers=AUTH).json()
    assert body["is_flat"] is False
    assert body["side"] == "long"
    assert body["quantity"] > 0


def test_pnl_shape(client):
    body = client.get("/api/pnl", headers=AUTH).json()
    assert set(body) == {
        "realized_today", "realized_total", "unrealized", "net", "orders_today"
    }


def test_fills_are_empty_before_trading(client):
    assert client.get("/api/fills", headers=AUTH).json()["fills"] == []


def test_fills_limit_is_bounded(client):
    assert client.get("/api/fills?limit=0", headers=AUTH).status_code == 422
    assert client.get("/api/fills?limit=9999", headers=AUTH).status_code == 422
    assert client.get("/api/fills?limit=5", headers=AUTH).status_code == 200


def test_candles_are_served_for_the_chart(client, runner):
    body = client.get("/api/candles?limit=50", headers=AUTH).json()
    assert body["symbol"] == runner.symbol
    assert len(body["candles"]) > 0
    assert set(body["candles"][0]) == {"t", "o", "h", "l", "c", "v"}


def test_candles_report_a_feed_outage_as_503(runner):
    class DeadFeed:
        name = "dead"

        async def fetch_candles(self, *_args, **_kwargs):
            raise RuntimeError("exchange unreachable")

        async def close(self):
            return None

    runner.market_data = DeadFeed()
    app = create_app(runner, ApiConfig(enabled=True, token=TOKEN))
    with TestClient(app) as c:
        assert c.get("/api/candles", headers=AUTH).status_code == 503


# -- control ------------------------------------------------------------

def test_pause_and_resume_round_trip(client, runner):
    assert client.post("/api/control/pause", headers=AUTH).json()["paused"] is True
    assert runner.paused is True

    assert client.post("/api/control/resume", headers=AUTH).json()["paused"] is False
    assert runner.paused is False


def test_kill_engages_and_persists(client, runner):
    body = client.post("/api/control/kill", headers=AUTH).json()
    assert body["killed"] is True
    assert runner.killed is True
    # Same state the Telegram gateway and a restart would see.
    assert runner.journal.get_control("kill_switch") is True


def test_resume_is_refused_while_killed(client, runner):
    client.post("/api/control/kill", headers=AUTH)
    response = client.post("/api/control/resume", headers=AUTH)
    assert response.status_code == 409
    assert "kill switch" in response.json()["detail"]


def test_revive_then_resume_works(client, runner):
    client.post("/api/control/kill", headers=AUTH)
    client.post("/api/control/revive", headers=AUTH)
    assert runner.killed is False
    assert client.post("/api/control/resume", headers=AUTH).status_code == 200


def test_api_counts_as_a_remote_stop_for_live_mode(config):
    from myp1.config import TelegramConfig

    without = dataclasses.replace(config, telegram=TelegramConfig())
    assert without.has_remote_stop is False

    with_api = dataclasses.replace(
        without, api=ApiConfig(enabled=True, token=TOKEN)
    )
    assert with_api.has_remote_stop is True
