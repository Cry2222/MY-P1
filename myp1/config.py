"""Configuration, loaded from the environment.

Nothing in this project reads os.environ outside this module. That keeps the
live-trading gate in exactly one place instead of scattered across callers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

LIVE_CONFIRM_PHRASE = "i-understand-this-trades-real-money"


class ConfigError(RuntimeError):
    """Raised when configuration is missing, malformed, or unsafe."""


def _env(key: str, default: str | None = None) -> str | None:
    value = os.environ.get(key, default)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _float(key: str, default: float) -> float:
    raw = _env(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


def _int(key: str, default: int) -> int:
    raw = _env(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _bool(key: str, default: bool) -> bool:
    raw = _env(key)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RiskConfig:
    """Hard limits. The risk engine cannot be configured to have none."""

    max_position_notional: float = 100.0
    risk_fraction: float = 0.02          # fraction of equity per new position
    max_daily_loss: float = 25.0         # absolute currency, halts trading
    max_orders_per_day: int = 40         # runaway-loop protection
    max_slippage_pct: float = 0.5        # reject if price moved this much
    min_order_notional: float = 5.0      # below exchange minimums, skip

    def validate(self) -> None:
        if self.max_position_notional <= 0:
            raise ConfigError("MYP1_MAX_POSITION_NOTIONAL must be > 0")
        if not 0 < self.risk_fraction <= 1:
            raise ConfigError("MYP1_RISK_FRACTION must be in (0, 1]")
        if self.max_daily_loss <= 0:
            raise ConfigError("MYP1_MAX_DAILY_LOSS must be > 0")
        if self.max_orders_per_day <= 0:
            raise ConfigError("MYP1_MAX_ORDERS_PER_DAY must be > 0")


@dataclass(frozen=True)
class ApiConfig:
    """HTTP control surface for the mobile app.

    Off by default. The bind address defaults to loopback because this API can
    halt trading — exposing it needs a deliberate decision plus a transport
    that authenticates, not just an open port.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8333
    token: str | None = None
    docs_enabled: bool = False
    cors_origins: tuple[str, ...] = ()
    # auto | fastapi | lite. "auto" falls back to the dependency-free server
    # when FastAPI is not installed, which is the on-device case.
    server: str = "auto"

    def validate(self) -> None:
        if not self.enabled:
            return
        if not self.token:
            raise ConfigError(
                "MYP1_API_ENABLED=true requires MYP1_API_TOKEN. Generate one with:\n"
                '  python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if len(self.token) < 24:
            raise ConfigError("MYP1_API_TOKEN must be at least 24 characters")
        if not 1 <= self.port <= 65535:
            raise ConfigError(f"MYP1_API_PORT out of range: {self.port}")
        if self.server not in {"auto", "fastapi", "lite"}:
            raise ConfigError(
                f"MYP1_API_SERVER must be auto, fastapi or lite, got {self.server!r}"
            )


@dataclass(frozen=True)
class TelegramConfig:
    token: str | None = None
    owner_chat_id: int | None = None
    enabled: bool = True

    @property
    def usable(self) -> bool:
        return bool(self.enabled and self.token and self.owner_chat_id)


@dataclass(frozen=True)
class Config:
    mode: str = "paper"                  # paper | live
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "1m"
    poll_seconds: float = 20.0

    api_key: str | None = None
    api_secret: str | None = None

    starting_cash: float = 1000.0        # paper mode only
    fee_pct: float = 0.1                 # per side, percent
    slippage_pct: float = 0.02           # paper fill degradation, percent

    strategy: str = "ema_cross"
    fast_period: int = 12
    slow_period: int = 26
    long_only: bool = True

    journal_path: str = "data/myp1.sqlite3"
    log_level: str = "INFO"

    risk: RiskConfig = field(default_factory=RiskConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    api: ApiConfig = field(default_factory=ApiConfig)

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def has_remote_stop(self) -> bool:
        """Can a human halt this bot without shell access to the host?"""
        return self.telegram.usable or self.api.enabled

    def validate(self) -> None:
        if self.mode not in {"paper", "live"}:
            raise ConfigError(f"MYP1_MODE must be 'paper' or 'live', got {self.mode!r}")
        if self.fast_period >= self.slow_period:
            raise ConfigError("MYP1_FAST_PERIOD must be less than MYP1_SLOW_PERIOD")
        if self.poll_seconds <= 0:
            raise ConfigError("MYP1_POLL_SECONDS must be > 0")
        self.risk.validate()
        self.api.validate()

        if self.is_live:
            # Live mode needs three independent things to line up. Any one of
            # them missing means the operator did not mean to trade real money.
            if _env("MYP1_LIVE_CONFIRM") != LIVE_CONFIRM_PHRASE:
                raise ConfigError(
                    "Live mode requires MYP1_LIVE_CONFIRM="
                    f"{LIVE_CONFIRM_PHRASE!r}. Refusing to start."
                )
            if not (self.api_key and self.api_secret):
                raise ConfigError("Live mode requires MYP1_API_KEY and MYP1_API_SECRET")
            if not self.has_remote_stop:
                raise ConfigError(
                    "Live mode requires a reachable kill switch. Enable either "
                    "the Telegram gateway (MYP1_TELEGRAM_TOKEN + "
                    "MYP1_TELEGRAM_OWNER_ID) or the control API "
                    "(MYP1_API_ENABLED=true + MYP1_API_TOKEN)."
                )


def load_config() -> Config:
    """Build a validated Config from the process environment."""
    owner_raw = _env("MYP1_TELEGRAM_OWNER_ID")
    try:
        owner_id = int(owner_raw) if owner_raw else None
    except ValueError as exc:
        raise ConfigError("MYP1_TELEGRAM_OWNER_ID must be an integer") from exc

    config = Config(
        mode=(_env("MYP1_MODE", "paper") or "paper").lower(),
        exchange=_env("MYP1_EXCHANGE", "binance") or "binance",
        symbol=_env("MYP1_SYMBOL", "BTC/USDT") or "BTC/USDT",
        timeframe=_env("MYP1_TIMEFRAME", "1m") or "1m",
        poll_seconds=_float("MYP1_POLL_SECONDS", 20.0),
        api_key=_env("MYP1_API_KEY"),
        api_secret=_env("MYP1_API_SECRET"),
        starting_cash=_float("MYP1_STARTING_CASH", 1000.0),
        fee_pct=_float("MYP1_FEE_PCT", 0.1),
        slippage_pct=_float("MYP1_SLIPPAGE_PCT", 0.02),
        strategy=_env("MYP1_STRATEGY", "ema_cross") or "ema_cross",
        fast_period=_int("MYP1_FAST_PERIOD", 12),
        slow_period=_int("MYP1_SLOW_PERIOD", 26),
        long_only=_bool("MYP1_LONG_ONLY", True),
        journal_path=_env("MYP1_JOURNAL_PATH", "data/myp1.sqlite3") or "data/myp1.sqlite3",
        log_level=(_env("MYP1_LOG_LEVEL", "INFO") or "INFO").upper(),
        risk=RiskConfig(
            max_position_notional=_float("MYP1_MAX_POSITION_NOTIONAL", 100.0),
            risk_fraction=_float("MYP1_RISK_FRACTION", 0.02),
            max_daily_loss=_float("MYP1_MAX_DAILY_LOSS", 25.0),
            max_orders_per_day=_int("MYP1_MAX_ORDERS_PER_DAY", 40),
            max_slippage_pct=_float("MYP1_MAX_SLIPPAGE_PCT", 0.5),
            min_order_notional=_float("MYP1_MIN_ORDER_NOTIONAL", 5.0),
        ),
        telegram=TelegramConfig(
            token=_env("MYP1_TELEGRAM_TOKEN"),
            owner_chat_id=owner_id,
            enabled=_bool("MYP1_TELEGRAM_ENABLED", True),
        ),
        api=ApiConfig(
            enabled=_bool("MYP1_API_ENABLED", False),
            host=_env("MYP1_API_HOST", "127.0.0.1") or "127.0.0.1",
            port=_int("MYP1_API_PORT", 8333),
            token=_env("MYP1_API_TOKEN"),
            docs_enabled=_bool("MYP1_API_DOCS", False),
            server=(_env("MYP1_API_SERVER", "auto") or "auto").lower(),
            cors_origins=tuple(
                origin.strip()
                for origin in (_env("MYP1_API_CORS_ORIGINS", "") or "").split(",")
                if origin.strip()
            ),
        ),
    )
    config.validate()
    return config
