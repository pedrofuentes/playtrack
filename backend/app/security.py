from __future__ import annotations

import ipaddress
import logging
import uuid
from collections.abc import Iterable

from starlette.datastructures import FormData, MutableHeaders
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


_DEVELOPMENT_ORIGINS = frozenset(
    {"http://localhost:5173", "http://127.0.0.1:5173"}
)
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)
_MULTIPART_OVERHEAD_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


class UploadLimitExceeded(MultiPartException):
    pass


class LimitedUploadParser(MultiPartParser):
    def __init__(self, *args: object, max_file_bytes: int, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.max_file_bytes = max_file_bytes
        self._current_file_bytes = 0

    def on_part_begin(self) -> None:
        super().on_part_begin()
        self._current_file_bytes = 0

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._current_part.file is not None:
            self._current_file_bytes += end - start
            if self._current_file_bytes > self.max_file_bytes:
                raise UploadLimitExceeded(
                    f"Upload exceeds the {self.max_file_bytes}-byte limit"
                )
        super().on_part_data(data, start, end)


async def parse_limited_upload_form(
    request: Request, *, max_file_bytes: int
) -> FormData:
    raw_length = request.headers.get("content-length")
    if raw_length is not None:
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise MultiPartException("Invalid Content-Length header") from exc
        if content_length < 0:
            raise MultiPartException("Invalid Content-Length header")
        if content_length > max_file_bytes + _MULTIPART_OVERHEAD_BYTES:
            raise UploadLimitExceeded(
                f"Upload exceeds the {max_file_bytes}-byte limit"
            )
    parser = LimitedUploadParser(
        request.headers,
        request.stream(),
        max_files=1,
        max_fields=1,
        max_part_size=4096,
        max_file_bytes=max_file_bytes,
    )
    return await parser.parse()


class ErrorCorrelationMiddleware:
    """Attach request IDs and hide unexpected exception details from clients."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        response_started = False

        async def send_with_request_id(message: dict[str, object]) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                MutableHeaders(scope=message)["X-Request-ID"] = request_id  # type: ignore[arg-type]
            await send(message)  # type: ignore[arg-type]

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception("Unhandled request error id=%s", request_id)
            if response_started:
                raise
            response = JSONResponse(
                {
                    "detail": "Internal server error",
                    "code": "internal_error",
                    "errorId": request_id,
                },
                status_code=500,
                headers={"X-Request-ID": request_id},
            )
            await response(scope, receive, send)


class RequestBoundaryMiddleware:
    """Reject DNS-rebinding hosts and cross-site browser traffic."""

    def __init__(self, app: ASGIApp, *, allowed_hosts: Iterable[str] = ()) -> None:
        self.app = app
        self.allowed_hosts = frozenset(
            host.strip().lower().rstrip(".") for host in allowed_hosts if host.strip()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        raw_host = headers.get("host", "")
        host = _host_name(raw_host)
        if host is None or not self._host_allowed(host):
            await self._reject(scope, receive, send, 400, "Invalid Host header")
            return

        origin = headers.get("origin")
        fetch_site = headers.get("sec-fetch-site", "").strip().lower()
        if fetch_site == "cross-site" or (
            origin is not None and not _origin_allowed(origin, scope, raw_host)
        ):
            await self._reject(
                scope, receive, send, 403, "Cross-site requests are not allowed"
            )
            return

        await self.app(scope, receive, send)

    def _host_allowed(self, host: str) -> bool:
        if host in {"localhost", "testserver"} or host in self.allowed_hosts:
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return (
            address.is_loopback
            or address.is_link_local
            or any(address in network for network in _PRIVATE_NETWORKS)
        )

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        detail: str,
    ) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4403, "reason": detail})
            return
        response = JSONResponse({"detail": detail}, status_code=status)
        await response(scope, receive, send)


def _host_name(raw_host: str) -> str | None:
    value = raw_host.strip()
    if not value or any(character.isspace() for character in value):
        return None
    if value.startswith("["):
        closing = value.find("]")
        if closing <= 1:
            return None
        host = value[1:closing]
        remainder = value[closing + 1 :]
        if remainder and (not remainder.startswith(":") or not remainder[1:].isdigit()):
            return None
    else:
        if value.count(":") > 1:
            return None
        host, separator, port = value.partition(":")
        if separator and (not port or not port.isdigit()):
            return None
    host = host.lower().rstrip(".")
    if not host or any(character in host for character in "/\\@"):
        return None
    return host


def _origin_allowed(origin: str, scope: Scope, raw_host: str) -> bool:
    normalized = origin.strip().rstrip("/").lower()
    if normalized in _DEVELOPMENT_ORIGINS:
        return True
    scheme = str(scope.get("scheme", "http")).lower()
    if scheme == "ws":
        scheme = "http"
    elif scheme == "wss":
        scheme = "https"
    return normalized == f"{scheme}://{raw_host.lower()}"
