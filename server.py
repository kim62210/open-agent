import asyncio
import html as html_lib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)  # JSONResponse imported above
from fastapi.staticfiles import StaticFiles
from open_agent.api.endpoints import (
    auth as auth_router,
)
from open_agent.api.endpoints import (
    chat,
)
from open_agent.api.endpoints import (
    jobs as jobs_router,
)
from open_agent.api.endpoints import (
    mcp as mcp_router,
)
from open_agent.api.endpoints import (
    memory as memory_router,
)
from open_agent.api.endpoints import (
    pages as pages_router,
)
from open_agent.api.endpoints import (
    runs as runs_router,
)
from open_agent.api.endpoints import (
    sandbox as sandbox_router,
)
from open_agent.api.endpoints import (
    sessions as sessions_router,
)
from open_agent.api.endpoints import (
    settings as settings_router,
)
from open_agent.api.endpoints import (
    skills as skills_router,
)
from open_agent.api.endpoints import (
    workspace as workspace_router,
)
from open_agent.api.middleware import RequestLoggingMiddleware
from open_agent.core.auth.rate_limit import limiter
from open_agent.core.exceptions import (
    AlreadyExistsError,
    InvalidPathError,
    JobStateError,
    LLMContextWindowError,
    LLMError,
    LLMRateLimitError,
    MCPConnectionError,
    NotFoundError,
    NotInitializedError,
    OpenAgentError,
    PermissionDeniedError,
    StorageLimitError,
)
from open_agent.core.job_manager import job_manager
from open_agent.core.job_scheduler import job_scheduler
from open_agent.core.logging import setup_logging
from open_agent.core.mcp_manager import mcp_manager
from open_agent.core.memory_manager import memory_manager
from open_agent.core.page_manager import page_manager
from open_agent.core.session_manager import session_manager
from open_agent.core.settings_manager import settings_manager
from open_agent.core.skill_manager import skill_manager
from open_agent.core.workspace_manager import workspace_manager
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

setup_logging()
logger = logging.getLogger(__name__)

# 정적 파일 디렉토리 (wheel 내부)
STATIC_DIR = Path(__file__).parent / "static"


def _should_auto_import_gh_token() -> bool:
    return os.environ.get("OPEN_AGENT_DEV") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 데이터 디렉토리 자동 초기화 (init 없이도 start만으로 동작)
    from open_agent.config import init_data_dir

    data_dir = init_data_dir()
    env_path = data_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # GITHUB_TOKEN 자동 설정 (gh CLI 로그인 상태에서 가져옴)
    if (
        _should_auto_import_gh_token()
        and not os.environ.get("GITHUB_TOKEN")
        and not os.environ.get("GH_TOKEN")
    ):
        try:
            import subprocess

            result = await asyncio.to_thread(
                subprocess.run,
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            token = result.stdout.strip()
            if token:
                os.environ["GITHUB_TOKEN"] = token
                logger.info("GITHUB_TOKEN auto-configured from gh CLI")
        except Exception as exc:
            logger.debug("Failed to auto-configure GITHUB_TOKEN", exc_info=exc)

    # Initialize database
    from core.db.engine import init_db

    logger.info("Initializing database...")
    await init_db()

    # Migrate legacy JSON files into database (one-time, idempotent)
    from core.db.migrate import migrate_json_to_db

    await migrate_json_to_db(data_dir)

    # Startup — load from database
    logger.info("Loading settings...")
    await settings_manager.load_from_db()

    logger.info("Loading MCP config and connecting servers...")
    await mcp_manager.load_from_db()
    await mcp_manager.connect_all()

    logger.info("Loading skills...")
    await skill_manager.load_disabled_from_db()
    bundled = str((Path(__file__).parent / "bundled_skills").resolve())
    skill_manager.set_bundled_dir(bundled)
    skill_manager.discover_skills(["skills", bundled])

    logger.info("Loading pages...")
    page_manager.init_pages_dir("pages")
    await page_manager.load_from_db()

    logger.info("Loading sessions...")
    await session_manager.load_from_db()

    logger.info("Loading memories...")
    await memory_manager.load_from_db()

    logger.info("Loading workspaces...")
    await workspace_manager.load_from_db()

    logger.info("Loading jobs...")
    await job_manager.load_from_db()

    logger.info("Starting job scheduler...")
    await job_scheduler.start()
    yield
    # Shutdown
    logger.info("Stopping job scheduler...")
    await job_scheduler.stop()
    logger.info("Disconnecting all MCP servers...")
    await mcp_manager.disconnect_all()
    logger.info("Closing database...")
    from core.db.engine import close_db

    await close_db()


app = FastAPI(title="Open Agent API", lifespan=lifespan)

# ── Rate limiter (slowapi) ──
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── 전역 예외 핸들러 ──


def _register_exception_handlers(target_app: FastAPI) -> None:
    @target_app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @target_app.exception_handler(AlreadyExistsError)
    async def already_exists_handler(request: Request, exc: AlreadyExistsError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @target_app.exception_handler(PermissionDeniedError)
    async def permission_denied_handler(
        request: Request, exc: PermissionDeniedError
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @target_app.exception_handler(InvalidPathError)
    async def invalid_path_handler(request: Request, exc: InvalidPathError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @target_app.exception_handler(StorageLimitError)
    async def storage_limit_handler(request: Request, exc: StorageLimitError) -> JSONResponse:
        return JSONResponse(status_code=413, content={"detail": str(exc)})

    @target_app.exception_handler(JobStateError)
    async def job_state_handler(request: Request, exc: JobStateError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @target_app.exception_handler(LLMRateLimitError)
    async def llm_rate_limit_handler(request: Request, exc: LLMRateLimitError) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    @target_app.exception_handler(LLMContextWindowError)
    async def llm_context_handler(request: Request, exc: LLMContextWindowError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @target_app.exception_handler(LLMError)
    async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @target_app.exception_handler(MCPConnectionError)
    async def mcp_connection_handler(request: Request, exc: MCPConnectionError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @target_app.exception_handler(NotInitializedError)
    async def not_initialized_handler(request: Request, exc: NotInitializedError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "서버 내부 상태 오류"})

    @target_app.exception_handler(OpenAgentError)
    async def open_agent_fallback_handler(request: Request, exc: OpenAgentError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


_register_exception_handlers(app)

# CORS: 개발 모드에서만 전체 허용, 프로덕션에서는 localhost만 허용
_dev_mode = os.environ.get("OPEN_AGENT_DEV") == "1"
if _dev_mode:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:4821",
            "http://localhost:4822",
            "http://127.0.0.1:4821",
            "http://127.0.0.1:4822",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.add_middleware(RequestLoggingMiddleware)

# 라우터 등록
app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(mcp_router.router, prefix="/api/mcp", tags=["mcp"])
app.include_router(skills_router.router, prefix="/api/skills", tags=["skills"])
app.include_router(pages_router.router, prefix="/api/pages", tags=["pages"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(sessions_router.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(memory_router.router, prefix="/api/memory", tags=["memory"])
app.include_router(workspace_router.router, prefix="/api/workspace", tags=["workspace"])
app.include_router(jobs_router.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(runs_router.router, prefix="/api/runs", tags=["runs"])
app.include_router(sandbox_router.router, prefix="/api/sandbox", tags=["sandbox"])

# --- Host info (for --expose LAN URL) ---


@app.get("/api/host-info")
async def host_info():
    """Return server host information for URL construction."""
    expose = os.environ.get("OPEN_AGENT_EXPOSE") == "1"
    port = int(os.environ.get("OPEN_AGENT_PORT", "4821"))
    result: dict = {"expose": expose, "port": port}
    if expose:
        import socket

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                result["lan_ip"] = s.getsockname()[0]
        except Exception as exc:
            logger.warning("Failed to detect LAN IP for host-info", exc_info=exc)
    return result


# --- Hosted pages (public, no auth) ---


@app.get("/hosted/")
async def hosted_directory():
    """Public directory of all published pages."""
    from open_agent.core.page_manager import page_manager as pm

    published = pm.get_published_pages()
    if not published:
        html = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Hosted Pages</title>
<style>body{font-family:system-ui;max-width:800px;margin:40px auto;padding:20px;background:#0a0a0a;color:#e5e5e5}
h1{font-size:1.5em;border-bottom:2px solid #333;padding-bottom:12px}p{color:#888;font-size:14px}</style></head>
<body><h1>Hosted Pages</h1><p>No published pages yet.</p></body></html>"""
        return HTMLResponse(content=html)

    items = ""
    for p in published:
        lock = (
            ' <span style="color:#f97316;font-size:12px">&#128274;</span>'
            if p.host_password_hash
            else ""
        )
        href = f"/hosted/{p.id}/" if p.content_type == "bundle" else f"/hosted/{p.id}"
        items += f'<a href="{href}" style="display:block;padding:12px 16px;margin:4px 0;background:#1a1a1a;border:1px solid #333;text-decoration:none;color:#e5e5e5;border-radius:6px">'
        items += f"<strong>{html_lib.escape(p.name)}</strong>{lock}"
        if p.description:
            items += f'<br><small style="color:#888">{html_lib.escape(p.description)}</small>'
        items += "</a>"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Hosted Pages</title>
<style>body{{font-family:system-ui;max-width:800px;margin:40px auto;padding:20px;background:#0a0a0a;color:#e5e5e5}}
h1{{font-size:1.5em;border-bottom:2px solid #333;padding-bottom:12px}}a:hover{{border-color:#f97316!important}}</style></head>
<body><h1>Hosted Pages</h1>{items}</body></html>"""
    return HTMLResponse(content=html)


def _hosted_password_cookie_val(password_hash: str) -> str:
    import hashlib

    return hashlib.sha256(password_hash.encode()).hexdigest()


def _hosted_password_form(page_id: str, wrong: bool = False) -> HTMLResponse:
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Password Required</title>
<style>body{{font-family:system-ui;max-width:400px;margin:80px auto;padding:20px;background:#0a0a0a;color:#e5e5e5;text-align:center}}
h2{{font-size:1.3em;margin-bottom:8px}}p{{color:#888;font-size:13px;margin-bottom:24px}}
input{{width:100%;padding:12px;background:#1a1a1a;border:1px solid #333;color:#e5e5e5;border-radius:6px;font-size:14px;box-sizing:border-box;margin-bottom:12px}}
input:focus{{outline:none;border-color:#f97316}}
button{{width:100%;padding:12px;background:#f97316;color:#fff;border:none;border-radius:6px;font-weight:bold;cursor:pointer;font-size:14px}}
button:hover{{background:#ea580c}}.err{{color:#ef4444;font-size:12px;margin-bottom:12px}}</style></head>
<body><h2>Password Required</h2><p>This page is password-protected.</p>
{"<p class='err'>Incorrect password.</p>" if wrong else ""}
<form method="post" action="/hosted/{page_id}"><input id="pw" type="password" name="password" placeholder="Enter password">
<button type="submit">Access</button></form>
<script>try{{document.getElementById('pw').focus()}}catch(e){{}}</script></body></html>"""
    return HTMLResponse(content=html)


@app.get("/hosted/{page_id}")
async def hosted_page_root(request: Request, page_id: str):
    """For bundle pages, redirect to trailing-slash URL so relative paths resolve correctly."""
    from open_agent.core.page_manager import page_manager as pm

    page = pm.get_page(page_id)
    if not page or not page.published:
        return HTMLResponse(
            content="<h1>404 — Page not found or not published</h1>", status_code=404
        )

    # Password check via cookie
    if page.host_password_hash:
        cookie = request.cookies.get(f"hosted_pw_{page_id}", "")
        if cookie != _hosted_password_cookie_val(page.host_password_hash):
            return _hosted_password_form(page_id)

    # Bundle: redirect to trailing-slash so relative paths (CSS/JS) resolve correctly
    if page.content_type == "bundle":
        return RedirectResponse(url=f"/hosted/{page_id}/", status_code=301)

    # Non-bundle (single HTML): serve directly
    return await _serve_hosted_content(page, page_id, "")


@app.post("/hosted/{page_id}")
async def hosted_page_password(request: Request, page_id: str):
    """Handle password form submission (POST)."""
    from open_agent.core.page_manager import page_manager as pm

    page = pm.get_page(page_id)
    if not page or not page.published:
        return HTMLResponse(
            content="<h1>404 — Page not found or not published</h1>", status_code=404
        )

    if not page.host_password_hash:
        if page.content_type == "bundle":
            return RedirectResponse(url=f"/hosted/{page_id}/", status_code=302)
        return RedirectResponse(url=f"/hosted/{page_id}", status_code=302)

    # Parse form data
    form = await request.form()
    password = form.get("password", "")

    if password and pm.verify_host_password(page_id, str(password)):
        # Set cookie for future visits (works for same-origin, best-effort for cross-origin)
        cookie_val = _hosted_password_cookie_val(page.host_password_hash)
        # Serve content directly instead of redirecting — avoids cross-origin iframe cookie issues
        # For bundles: inject <base href> so relative paths (CSS/JS) resolve to /hosted/{page_id}/
        base = f"/hosted/{page_id}/" if page.content_type == "bundle" else None
        resp = await _serve_hosted_content(page, page_id, "", base_href=base)
        resp.set_cookie(
            f"hosted_pw_{page_id}", cookie_val, httponly=True, samesite="lax", max_age=86400
        )
        return resp

    return _hosted_password_form(page_id, wrong=True)


@app.get("/hosted/{page_id}/__version__")
async def hosted_page_version(page_id: str):
    """Return page version for live-reload polling."""
    from fastapi.responses import JSONResponse
    from open_agent.core.page_manager import page_manager as pm

    v = pm.get_version(page_id)
    return JSONResponse({"v": v}, headers={"Cache-Control": "no-cache, no-store"})


@app.get("/hosted/{page_id}/{file_path:path}")
async def hosted_page_file(request: Request, page_id: str, file_path: str = ""):
    """Serve hosted page files (entry HTML + sub-resources like JS/CSS/images)."""
    from open_agent.core.page_manager import page_manager as pm

    page = pm.get_page(page_id)
    if not page or not page.published:
        return HTMLResponse(
            content="<h1>404 — Page not found or not published</h1>", status_code=404
        )

    # Password check for entry page only (root access with no file_path)
    # Sub-resources (JS/CSS/images) are served without password — they're useless without the entry HTML
    if page.host_password_hash and not file_path:
        cookie = request.cookies.get(f"hosted_pw_{page_id}", "")
        if cookie != _hosted_password_cookie_val(page.host_password_hash):
            return RedirectResponse(url=f"/hosted/{page_id}", status_code=302)

    return await _serve_hosted_content(page, page_id, file_path)


def _inject_base(html: str, href: str) -> str:
    """Inject <base href> right after <head> so relative paths resolve correctly."""
    import re

    base_tag = f'<base href="{href}">'
    m = re.search(r"(<head[^>]*>)", html, re.IGNORECASE)
    if m:
        return html[: m.end()] + base_tag + html[m.end() :]
    return base_tag + html


async def _serve_hosted_content(page, page_id: str, file_path: str, base_href: str | None = None):
    """Serve the actual file content for a hosted page."""
    import mimetypes as mt

    from open_agent.core.page_manager import page_manager as pm
    from open_agent.core.page_wrapper import (
        generate_wrapper,
        inject_live_reload,
        inject_storage_bridge,
        needs_wrapper,
    )

    hosted_version_url = f"/hosted/{page_id}/__version__"

    def _finalize_html(html: str) -> str:
        """Apply storage bridge, base_href, and live-reload to entry HTML."""
        html = inject_storage_bridge(html, page_id)
        if base_href:
            html = _inject_base(html, base_href)
        return inject_live_reload(html, page_id, version_url=hosted_version_url)

    if page.content_type == "bundle":
        target_path = file_path or page.entry_file or "index.html"
        resolved = pm.get_bundle_file_path(page_id, target_path)
        if not resolved:
            return HTMLResponse(content="<h1>404 — File not found</h1>", status_code=404)
        is_entry = not file_path or file_path == (page.entry_file or "index.html")
        if is_entry and needs_wrapper(target_path):
            return HTMLResponse(
                content=_finalize_html(generate_wrapper(page_id, target_path, resolved))
            )
        if is_entry:
            return HTMLResponse(content=_finalize_html(resolved.read_text(encoding="utf-8")))
        mime, _ = mt.guess_type(str(resolved))
        return FileResponse(path=resolved, media_type=mime or "text/html")

    if page.content_type == "html":
        html_path = pm.get_html_path(page_id)
        if not html_path:
            return HTMLResponse(content="<h1>404 — File not found</h1>", status_code=404)
        filename = page.filename or "index.html"
        if needs_wrapper(filename):
            return HTMLResponse(
                content=_finalize_html(generate_wrapper(page_id, filename, html_path))
            )
        return HTMLResponse(content=_finalize_html(html_path.read_text(encoding="utf-8")))

    return HTMLResponse(content="<h1>400 — Unsupported page type</h1>", status_code=400)


# 정적 파일 서빙 (API 라우터 이후에 등록)
if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    # Next.js static export의 _next/ 디렉토리 서빙
    next_dir = STATIC_DIR / "_next"
    if next_dir.exists():
        app.mount("/_next", StaticFiles(directory=next_dir), name="next-static")

    # SPA fallback: 모든 비-API 경로 처리 (GET + POST + HEAD — Next.js RSC 요청 포함)
    @app.api_route("/{path:path}", methods=["GET", "POST", "HEAD"])
    async def serve_frontend(path: str):
        # API 경로는 SPA fallback에서 제외 — 라우터가 처리하도록 함
        if path.startswith("api/"):
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        # 경로 순회 방지: resolve 후 STATIC_DIR 내부인지 검증
        file_path = (STATIC_DIR / path).resolve()
        if not file_path.is_relative_to(STATIC_DIR.resolve()):
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=400, content={"detail": "Invalid path"})
        # 파일이 존재하면 직접 서빙
        if file_path.is_file():
            return FileResponse(file_path)
        # Next.js export: /pages/viewer → /pages/viewer.html
        html_path = (STATIC_DIR / f"{path}.html").resolve()
        if html_path.is_relative_to(STATIC_DIR.resolve()) and html_path.is_file():
            return FileResponse(html_path)
        # fallback → index.html (SPA navigation)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return {"message": "Welcome to Open Agent API"}
else:

    @app.get("/")
    async def root():
        return {"message": "Welcome to Open Agent API"}
