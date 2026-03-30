import mimetypes
import os
import zipfile
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from open_agent.core.page_manager import page_manager
from open_agent.core.page_wrapper import (
    generate_wrapper,
    inject_storage_bridge,
    is_allowed_extension,
    needs_wrapper,
)
from open_agent.models.page import (
    CreateBookmarkRequest,
    CreateFolderRequest,
    PageInfo,
    UpdatePageRequest,
)
from pydantic import BaseModel

from core.auth.dependencies import require_any, require_user

router = APIRouter()


# --- Folder endpoints (before /{page_id} to avoid route conflicts) ---


@router.post("/folders", response_model=PageInfo)
async def create_folder(
    req: CreateFolderRequest, current_user: Annotated[dict, Depends(require_user)]
):
    return await page_manager.create_folder(
        req.name,
        req.description,
        req.parent_id,
        owner_user_id=current_user["id"],
    )


@router.get("/breadcrumb/{page_id}", response_model=list[PageInfo])
async def get_breadcrumb(page_id: str, current_user: Annotated[dict, Depends(require_any)]):
    page = page_manager.get_page(page_id, owner_user_id=current_user["id"])
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page_manager.get_breadcrumb(page_id)


# --- Bookmark endpoint ---


@router.post("/bookmark", response_model=PageInfo)
async def create_bookmark(
    req: CreateBookmarkRequest, current_user: Annotated[dict, Depends(require_user)]
):
    return await page_manager.add_bookmark(
        name=req.name,
        url=req.url,
        description=req.description,
        parent_id=req.parent_id,
        owner_user_id=current_user["id"],
    )


# --- Frameable check ---


@router.post("/check-frameable/{page_id}")
async def check_frameable(page_id: str, current_user: Annotated[dict, Depends(require_any)]):
    page = page_manager.get_page(page_id, owner_user_id=current_user["id"])
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    frameable = await page_manager.check_and_update_frameable(page_id)
    return {"frameable": frameable}


# --- Active page (for chat // command) ---
# These must come BEFORE /{page_id} to avoid route conflicts


@router.post("/deactivate")
async def deactivate_page(current_user: Annotated[dict, Depends(require_user)]):
    page_manager.deactivate_page()
    return {"status": "deactivated"}


@router.get("/active/current", response_model=PageInfo | None)
async def get_active_page(current_user: Annotated[dict, Depends(require_any)]):
    return page_manager.get_active_page(owner_user_id=current_user["id"])


# --- Publish / Host ---


@router.get("/published/list", response_model=list[PageInfo])
async def list_published_pages(current_user: Annotated[dict, Depends(require_any)]):
    return page_manager.get_published_pages(owner_user_id=current_user["id"])


# --- Page endpoints ---


@router.get("/", response_model=list[PageInfo])
async def list_pages(
    current_user: Annotated[dict, Depends(require_any)], parent_id: str | None = None
):
    if parent_id is not None:
        return page_manager.get_children(
            parent_id if parent_id != "null" else None, owner_user_id=current_user["id"]
        )
    return page_manager.get_all(owner_user_id=current_user["id"])


@router.get("/{page_id}", response_model=PageInfo)
async def get_page(page_id: str, current_user: Annotated[dict, Depends(require_any)]):
    page = page_manager.get_page(page_id, owner_user_id=current_user["id"])
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.get("/{page_id}/raw")
async def get_page_raw(page_id: str, current_user: Annotated[dict, Depends(require_any)]):
    page = page_manager.get_page(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    file_path = page_manager.get_html_path(page_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="Page file not found")
    mime, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(path=file_path, media_type=mime or "application/octet-stream")


@router.get("/{page_id}/__version__")
async def get_page_version(page_id: str, current_user: Annotated[dict, Depends(require_any)]):
    """Return page version for live-reload polling."""
    v = page_manager.get_version(page_id)
    return JSONResponse({"v": v}, headers={"Cache-Control": "no-cache, no-store"})


@router.get("/{page_id}/content/{file_path:path}")
async def get_bundle_file(
    page_id: str, file_path: str, current_user: Annotated[dict, Depends(require_any)]
):
    page = page_manager.get_page(page_id)
    resolved = page_manager.get_bundle_file_path(page_id, file_path)
    if not resolved:
        raise HTTPException(status_code=404, detail="File not found")
    if page and page.content_type == "bundle":
        is_entry = file_path == (page.entry_file or "index.html")
        if is_entry and needs_wrapper(file_path):
            html = generate_wrapper(page_id, file_path, resolved)
            return HTMLResponse(content=inject_storage_bridge(html, page_id))
        if is_entry:
            html = resolved.read_text(encoding="utf-8")
            return HTMLResponse(content=inject_storage_bridge(html, page_id))
    mime, _ = mimetypes.guess_type(str(resolved))
    return FileResponse(path=resolved, media_type=mime or "application/octet-stream")


@router.get("/{page_id}/content")
async def get_page_content(page_id: str, current_user: Annotated[dict, Depends(require_any)]):
    page = page_manager.get_page(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    if page.content_type == "url" and page.url:
        return RedirectResponse(url=page.url)

    if page.content_type == "bundle" and page.entry_file:
        return RedirectResponse(url=f"/api/pages/{page_id}/content/{page.entry_file}")

    html_path = page_manager.get_html_path(page_id)
    if not html_path:
        raise HTTPException(status_code=404, detail="Page content not found")

    if page.filename and needs_wrapper(page.filename):
        html = generate_wrapper(page_id, page.filename, html_path)
        return HTMLResponse(content=inject_storage_bridge(html, page_id))

    html = html_path.read_text(encoding="utf-8")
    return HTMLResponse(content=inject_storage_bridge(html, page_id))


@router.post("/upload-bundle", response_model=PageInfo)
async def upload_bundle(
    current_user: Annotated[dict, Depends(require_user)],
    files: Annotated[list[UploadFile], File(...)],
    name: Annotated[str, Form(...)],
    description: Annotated[str, Form()] = "",
    parent_id: Annotated[str | None, Form()] = None,
):
    if not files:
        raise HTTPException(status_code=400, detail="파일이 없습니다.")

    try:
        # Single ZIP file
        if len(files) == 1 and files[0].filename and files[0].filename.lower().endswith(".zip"):
            data = await files[0].read()
            bundle_files = _extract_zip(data)
        else:
            # Multiple files
            bundle_files = []
            for f in files:
                content = await f.read()
                bundle_files.append((f.filename or "untitled", content))

        if not bundle_files:
            raise HTTPException(status_code=400, detail="유효한 파일이 없습니다.")

        return await page_manager.add_bundle(
            name=name,
            description=description,
            files=bundle_files,
            parent_id=parent_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _extract_zip(data: bytes) -> list[tuple[str, bytes]]:
    """Extract ZIP, filter macOS artifacts, strip common prefix directory."""
    buf = BytesIO(data)
    if not zipfile.is_zipfile(buf):
        raise ValueError("유효한 ZIP 파일이 아닙니다.")
    buf.seek(0)

    result: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(buf, "r") as zf:
        for info in zf.infolist():
            # Skip directories
            if info.is_dir():
                continue
            name = info.filename
            # Filter macOS artifacts
            if "__MACOSX" in name or os.path.basename(name) == ".DS_Store":
                continue
            # Zip-slip defense
            normalized = os.path.normpath(name)
            if normalized.startswith("..") or os.path.isabs(normalized):
                continue
            result.append((normalized, zf.read(info)))

    # Strip common prefix directory
    if result:
        parts_list = [p.split(os.sep) for p, _ in result]
        if all(len(parts) > 1 for parts in parts_list):
            first_dir = parts_list[0][0]
            if all(parts[0] == first_dir for parts in parts_list):
                result = [(os.sep.join(p.split(os.sep)[1:]), c) for p, c in result]

    return result


@router.post("/upload", response_model=PageInfo)
async def upload_page(
    current_user: Annotated[dict, Depends(require_user)],
    file: Annotated[UploadFile, File(...)],
    name: Annotated[str, Form(...)],
    description: Annotated[str, Form()] = "",
    parent_id: Annotated[str | None, Form()] = None,
):
    if not file.filename or not is_allowed_extension(file.filename):
        raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식입니다.")
    try:
        data = await file.read()
        return await page_manager.add_page(
            name, description, data, file.filename, parent_id=parent_id
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class ImportPathRequest(BaseModel):
    path: str
    name: str
    description: str = ""
    parent_id: str | None = None


@router.post("/import", response_model=PageInfo)
async def import_page_from_path(
    req: ImportPathRequest, current_user: Annotated[dict, Depends(require_user)]
):
    try:
        return await page_manager.add_page_from_path(
            req.name, req.description, req.path, parent_id=req.parent_id
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/{page_id}", response_model=PageInfo)
async def update_page(
    page_id: str, req: UpdatePageRequest, current_user: Annotated[dict, Depends(require_user)]
):
    # Distinguish "not provided" vs "explicitly null" for parent_id
    parent_id = req.parent_id if "parent_id" in req.model_fields_set else "__unset__"
    page = await page_manager.update_page(
        page_id,
        name=req.name,
        description=req.description,
        parent_id=parent_id,
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.delete("/{page_id}")
async def delete_page(page_id: str, current_user: Annotated[dict, Depends(require_user)]):
    if not await page_manager.delete_page(page_id):
        raise HTTPException(status_code=404, detail="Page not found")
    return {"status": "deleted"}


# --- Active page activation (requires page_id, safe after /{page_id}) ---


@router.post("/{page_id}/activate", response_model=PageInfo)
async def activate_page(page_id: str, current_user: Annotated[dict, Depends(require_user)]):
    page = page_manager.activate_page(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found or is a folder")
    return page


# --- Publish / Host (requires page_id, safe after /{page_id}) ---


class PublishRequest(BaseModel):
    password: str | None = None


@router.post("/{page_id}/publish", response_model=PageInfo)
async def publish_page(
    page_id: str,
    current_user: Annotated[dict, Depends(require_user)],
    req: PublishRequest = PublishRequest(),
):
    page = await page_manager.publish_page(page_id, True, password=req.password)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found or not publishable")
    return page


@router.post("/{page_id}/unpublish", response_model=PageInfo)
async def unpublish_page(page_id: str, current_user: Annotated[dict, Depends(require_user)]):
    page = await page_manager.publish_page(page_id, False)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


# --- Page file operations (for inline editor) ---


@router.get("/{page_id}/files")
async def list_page_files(page_id: str, current_user: Annotated[dict, Depends(require_any)]):
    files = page_manager.list_page_files(page_id)
    if files is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"files": files}


@router.get("/{page_id}/files/{file_path:path}")
async def read_page_file(
    page_id: str, file_path: str, current_user: Annotated[dict, Depends(require_any)]
):
    content = page_manager.read_page_file(page_id, file_path)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"name": file_path, "content": content}


@router.put("/{page_id}/files/{file_path:path}")
async def write_page_file(
    page_id: str, file_path: str, body: dict, current_user: Annotated[dict, Depends(require_user)]
):
    content = body.get("content")
    if content is None:
        raise HTTPException(status_code=400, detail="content is required")
    result = await page_manager.write_page_file(page_id, file_path, content)
    if result is None:
        raise HTTPException(status_code=400, detail="Failed to write file")
    return {"status": "ok", "path": result}


# --- KV Storage ---


class KVSetRequest(BaseModel):
    value: str


@router.get("/{page_id}/kv")
async def kv_list_keys(page_id: str, current_user: Annotated[dict, Depends(require_any)]):
    keys = page_manager.kv_list(page_id)
    if keys is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return JSONResponse(keys, headers={"Cache-Control": "no-cache, no-store"})


@router.get("/{page_id}/kv/{key:path}")
async def kv_get(page_id: str, key: str, current_user: Annotated[dict, Depends(require_any)]):
    if not page_manager.get_page(page_id):
        raise HTTPException(status_code=404, detail="Page not found")
    value = page_manager.kv_get(page_id, key)
    if value is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return JSONResponse(
        {"key": key, "value": value}, headers={"Cache-Control": "no-cache, no-store"}
    )


@router.put("/{page_id}/kv/{key:path}")
async def kv_set(
    page_id: str, key: str, req: KVSetRequest, current_user: Annotated[dict, Depends(require_user)]
):
    if not page_manager.get_page(page_id):
        raise HTTPException(status_code=404, detail="Page not found")
    page_manager.kv_set(page_id, key, req.value)
    return {"key": key, "value": req.value}


@router.delete("/{page_id}/kv/{key:path}")
async def kv_delete(page_id: str, key: str, current_user: Annotated[dict, Depends(require_user)]):
    if not page_manager.get_page(page_id):
        raise HTTPException(status_code=404, detail="Page not found")
    if not page_manager.kv_delete(page_id, key):
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "deleted"}
