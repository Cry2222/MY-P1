"""Dependency-free control API.

Same contract as the FastAPI server, implemented on the standard library
alone. This exists for on-device deployment: FastAPI pulls in pydantic-core,
a compiled Rust extension that routinely fails to build under Termux on
Android. With this server the phone install is `pip install ccxt` and nothing
else.

It is a small, deliberately boring HTTP/1.1 server — no keep-alive, no
chunked encoding, no file serving. It answers a handful of JSON routes for a
single known client on loopback, and refusing to do more than that is the
point: less surface, less to get wrong.

Route behaviour lives in routes.py and is shared with the FastAPI server, so
the two cannot disagree.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from . import routes
from .routes import ApiFault

if TYPE_CHECKING:
    from ..config import ApiConfig
    from ..runner import TradingRunner

log = logging.getLogger(__name__)

MIN_TOKEN_LENGTH = 24
MAX_HEADER_BYTES = 16 * 1024
MAX_BODY_BYTES = 64 * 1024
READ_TIMEOUT = 15.0

STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


class LiteApiServer:
    def __init__(self, runner: TradingRunner, config: ApiConfig) -> None:
        if not config.token:
            raise ValueError("API requires MYP1_API_TOKEN")
        if len(config.token) < MIN_TOKEN_LENGTH:
            raise ValueError(
                f"MYP1_API_TOKEN must be at least {MIN_TOKEN_LENGTH} characters. "
                "This token can halt trading; generate one with "
                '`python -c "import secrets; print(secrets.token_urlsafe(32))"`'
            )
        self.runner = runner
        self.config = config
        self._server: asyncio.AbstractServer | None = None

    # -- request handling -----------------------------------------------

    async def _read_request(
        self, reader: asyncio.StreamReader
    ) -> tuple[str, str, dict[str, str]]:
        request_line = await reader.readline()
        if not request_line:
            raise ConnectionResetError("empty request")

        parts = request_line.decode("latin-1").rstrip("\r\n").split()
        if len(parts) < 2:
            raise ApiFault(400, "malformed request line")
        method, target = parts[0].upper(), parts[1]

        headers: dict[str, str] = {}
        consumed = len(request_line)
        while True:
            line = await reader.readline()
            consumed += len(line)
            if consumed > MAX_HEADER_BYTES:
                raise ApiFault(413, "headers too large")
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()

        length = int(headers.get("content-length") or 0)
        if length > MAX_BODY_BYTES:
            raise ApiFault(413, "body too large")
        if length:
            await reader.readexactly(length)  # bodies are accepted and ignored

        return method, target, headers

    def _authorised(self, headers: dict[str, str]) -> bool:
        header = headers.get("authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer":
            supplied = ""
        # Constant-time compare so a wrong token cannot be found by timing.
        return hmac.compare_digest(supplied.strip(), self.config.token or "")

    async def _dispatch(
        self, method: str, path: str, query: dict[str, list[str]], headers: dict[str, str]
    ) -> tuple[int, dict]:
        runner = self.runner

        def first(name: str) -> str | None:
            values = query.get(name)
            return values[0] if values else None

        # The only unauthenticated route.
        if path == "/api/health":
            if method != "GET":
                raise ApiFault(405, "method not allowed")
            return 200, routes.health(runner)

        if not self._authorised(headers):
            raise ApiFault(401, "invalid or missing token")

        if method == "GET":
            if path == "/api/status":
                return 200, routes.status(runner)
            if path == "/api/position":
                return 200, routes.position(runner)
            if path == "/api/pnl":
                return 200, routes.pnl(runner)
            if path == "/api/fills":
                return 200, routes.fills(runner, first("limit"))
            if path == "/api/candles":
                return 200, await routes.candles(runner, first("limit"))
            raise ApiFault(404, "not found")

        if method == "POST":
            prefix = "/api/control/"
            if path.startswith(prefix):
                return 200, routes.control(runner, path[len(prefix):])
            raise ApiFault(404, "not found")

        raise ApiFault(405, "method not allowed")

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        status_code, payload = 500, {"detail": "internal error"}
        origin = ""
        try:
            method, target, headers = await asyncio.wait_for(
                self._read_request(reader), timeout=READ_TIMEOUT
            )
            origin = headers.get("origin", "")
            split = urlsplit(target)
            path = split.path.rstrip("/") or "/"
            query = parse_qs(split.query)

            if method == "OPTIONS":
                status_code, payload = 200, {}
            else:
                status_code, payload = await self._dispatch(method, path, query, headers)
        except ApiFault as fault:
            status_code, payload = fault.status_code, {"detail": fault.detail}
        except TimeoutError:
            status_code, payload = 400, {"detail": "request timed out"}
        except (ConnectionResetError, asyncio.IncompleteReadError, BrokenPipeError):
            writer.close()
            return
        except Exception:
            log.exception("lite api handler failed")
            status_code, payload = 500, {"detail": "internal error"}

        try:
            writer.write(self._response(status_code, payload, origin))
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                pass

    def _response(self, status_code: int, payload: dict, origin: str) -> bytes:
        body = json.dumps(payload).encode("utf-8")
        lines = [
            f"HTTP/1.1 {status_code} {STATUS_TEXT.get(status_code, 'Unknown')}",
            "Content-Type: application/json",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "Cache-Control: no-store",
            "X-Content-Type-Options: nosniff",
        ]
        if status_code == 401:
            lines.append('WWW-Authenticate: Bearer')

        allowed = self.config.cors_origins
        if allowed and (origin in allowed or "*" in allowed):
            lines.append(f"Access-Control-Allow-Origin: {'*' if '*' in allowed else origin}")
            lines.append("Access-Control-Allow-Methods: GET, POST, OPTIONS")
            lines.append("Access-Control-Allow-Headers: Authorization, Content-Type")

        return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> int:
        """Bind and start listening. Returns the bound port."""
        self._server = await asyncio.start_server(
            self._handle, self.config.host, self.config.port, limit=MAX_HEADER_BYTES
        )
        sockets = self._server.sockets
        port = sockets[0].getsockname()[1] if sockets else self.config.port
        log.info("control API (lite) listening on http://%s:%d", self.config.host, port)
        return port

    async def serve(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # pragma: no cover - teardown best effort
                pass
            self._server = None


async def serve(runner: TradingRunner, config: ApiConfig) -> None:
    await LiteApiServer(runner, config).serve()
