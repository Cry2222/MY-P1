"""Control API.

Two server implementations behind one contract:

- `server.py`  FastAPI + uvicorn. OpenAPI docs, used on desktops and servers.
- `lite.py`    Standard library only. Used on phones, where pydantic-core
               cannot be compiled.

Both delegate to `routes.py`, so the wire contract is identical and the
contract tests run against both.
"""

from __future__ import annotations


def fastapi_available() -> bool:
    """True when the full server's dependencies are importable."""
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        return False
    return True


def resolve_backend(preference: str) -> str:
    """Pick a server implementation from config.

    'auto' prefers FastAPI when it is installed and silently falls back to the
    stdlib server when it is not, so an on-device install needs no config
    change beyond not installing FastAPI.
    """
    if preference not in {"auto", "fastapi", "lite"}:
        raise ValueError(f"unknown API server {preference!r}")
    if preference == "auto":
        return "fastapi" if fastapi_available() else "lite"
    if preference == "fastapi" and not fastapi_available():
        raise RuntimeError(
            "MYP1_API_SERVER=fastapi but fastapi/uvicorn are not installed. "
            "Install them, or use MYP1_API_SERVER=lite (no dependencies)."
        )
    return preference
