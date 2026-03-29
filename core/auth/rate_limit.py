"""Rate limiting configuration using slowapi."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _get_rate_limit_key(request: Request) -> str:
    """Key function: use authenticated user ID if available, else remote address."""
    user = getattr(request.state, "user", None)
    if user:
        return f"user:{user['id']}"
    return get_remote_address(request)


limiter = Limiter(key_func=_get_rate_limit_key)
