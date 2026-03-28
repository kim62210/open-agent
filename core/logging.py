"""structlog 기반 구조화 로깅 설정."""
import logging
import os
import sys

import structlog


def _is_dev_mode() -> bool:
    return os.getenv("OPEN_AGENT_DEV", "") == "1" or os.getenv("OPEN_AGENT_ENV", "prod") == "dev"


def setup_logging(*, level: str | None = None) -> None:
    """애플리케이션 로깅 초기화. server.py에서 1회 호출."""
    log_level = level or os.getenv("OPEN_AGENT_LOG_LEVEL", "INFO")
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if _is_dev_mode():
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric_level)

    for name in ("uvicorn.access", "httpx", "httpcore", "litellm"):
        logging.getLogger(name).setLevel(max(numeric_level, logging.WARNING))

    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.addHandler(handler)
        uv_logger.propagate = False


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """structlog 바운드 로거 반환."""
    return structlog.get_logger(name)
