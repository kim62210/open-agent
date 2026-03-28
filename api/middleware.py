"""FastAPI 미들웨어."""
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """HTTP 요청 로깅 + request_id 부여."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid.uuid4().hex[:8]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        method = request.method
        path = request.url.path

        skip_log = path.startswith("/_next") or path.startswith("/static")

        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 1)

            if not skip_log:
                log = logger.warning if response.status_code >= 400 else logger.info
                log(
                    "request.completed",
                    method=method,
                    path=path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )

            response.headers["X-Request-ID"] = request_id
            return response

        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.exception(
                "request.failed",
                method=method,
                path=path,
                duration_ms=duration_ms,
            )
            raise
        finally:
            structlog.contextvars.clear_contextvars()
