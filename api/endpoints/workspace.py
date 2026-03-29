import asyncio
import logging
import mimetypes
import os
import platform
import subprocess
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from open_agent.core.workspace_manager import workspace_manager
from open_agent.models.workspace import (
    CreateWorkspaceRequest,
    EditFileRequest,
    FileContent,
    FileTreeNode,
    UpdateWorkspaceRequest,
    WorkspaceInfo,
    WriteFileRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ──────────────────────────────────────────────────────────
# Windows 모던 폴더 선택 다이얼로그 (IFileDialog COM)
# FolderBrowserDialog(구형 트리뷰) 대신 Explorer 스타일 사용
# ──────────────────────────────────────────────────────────
_WINDOWS_FOLDER_PICKER_PS = r"""$cs = @'
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
class FileOpenDialog {}

[ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IShellItem {
    void _0(); void _1();
    [PreserveSig] int GetDisplayName(uint n, [MarshalAs(UnmanagedType.LPWStr)] out string s);
    void _3(); void _4();
}

[ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IFileDialog {
    [PreserveSig] int Show(IntPtr w);
    void _1(); void _2(); void _3(); void _4(); void _5();
    void SetOptions(uint o); void GetOptions(out uint o);
    void SetDefaultFolder(IShellItem i); void SetFolder(IShellItem i);
    void _10(out IShellItem i); void _11(out IShellItem i);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string n);
    void _13([MarshalAs(UnmanagedType.LPWStr)] out string n);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string t);
    void _15(); void _16();
    void GetResult(out IShellItem i);
    void _18(); void _19(); void _20(); void _21(); void _22();
}

public class FolderPicker {
    [DllImport("shell32.dll", CharSet=CharSet.Unicode)]
    static extern int SHCreateItemFromParsingName(string p, IntPtr b, ref Guid g, out IShellItem i);

    public static string Pick(string title, string defPath) {
        var d = (IFileDialog)new FileOpenDialog();
        uint o; d.GetOptions(out o); d.SetOptions(o | 0x20);
        if (title != null) d.SetTitle(title);
        if (!string.IsNullOrEmpty(defPath) && System.IO.Directory.Exists(defPath)) {
            Guid g = typeof(IShellItem).GUID; IShellItem f;
            if (SHCreateItemFromParsingName(defPath, IntPtr.Zero, ref g, out f) == 0)
                d.SetFolder(f);
        }
        if (d.Show(IntPtr.Zero) == 0) {
            IShellItem r; d.GetResult(out r); string s;
            r.GetDisplayName(0x80058000u, out s); return s;
        }
        return null;
    }
}
'@
try { Add-Type -TypeDefinition $cs -ErrorAction Stop } catch {}
$r = [FolderPicker]::Pick('Select workspace directory', $env:OPEN_AGENT_DEFAULT_PATH)
if ($r) { $r }
"""


def _pick_directory(default_path: str = "") -> str | None:
    """OS 네이티브 디렉토리 선택 다이얼로그를 열고 선택된 경로를 반환한다."""
    system = platform.system()
    try:
        if system == "Darwin":
            cmd = 'choose folder with prompt "Select workspace directory"'
            if default_path and os.path.isdir(default_path):
                escaped = default_path.replace("\\", "\\\\").replace('"', '\\"')
                cmd += f' default location POSIX file "{escaped}"'
            result = subprocess.run(
                ["osascript", "-e", f"POSIX path of ({cmd})"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return result.stdout.strip().rstrip("/")
        elif system == "Windows":
            env = {**os.environ, "OPEN_AGENT_DEFAULT_PATH": default_path or ""}
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 _WINDOWS_FOLDER_PICKER_PS],
                capture_output=True, text=True, timeout=120, env=env,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        else:
            # Linux — zenity
            cmd = ["zenity", "--file-selection", "--directory",
                   "--title=Select workspace directory"]
            if default_path and os.path.isdir(default_path):
                cmd.extend(["--filename", default_path.rstrip("/") + "/"])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Directory picker failed: {e}")
    return None


class BrowseDirectoryRequest(BaseModel):
    default_path: str = ""


@router.post("/browse-directory")
async def browse_directory(req: BrowseDirectoryRequest = BrowseDirectoryRequest()):
    """OS 네이티브 폴더 선택 다이얼로그를 열어 경로를 반환한다."""
    path = await asyncio.to_thread(_pick_directory, req.default_path)
    if path is None:
        return {"path": None, "cancelled": True}
    return {"path": path, "cancelled": False}


@router.get("/", response_model=list[WorkspaceInfo])
async def list_workspaces():
    return workspace_manager.get_all()


@router.post("/", response_model=WorkspaceInfo)
async def create_workspace(req: CreateWorkspaceRequest):
    return await workspace_manager.create_workspace(req.name, req.path, req.description)


@router.get("/{workspace_id}", response_model=WorkspaceInfo)
async def get_workspace(workspace_id: str):
    ws = workspace_manager.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.patch("/{workspace_id}", response_model=WorkspaceInfo)
async def update_workspace(workspace_id: str, req: UpdateWorkspaceRequest):
    ws = await workspace_manager.update_workspace(workspace_id, name=req.name, description=req.description)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.delete("/{workspace_id}")
async def delete_workspace(workspace_id: str):
    if not await workspace_manager.delete_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"status": "deleted"}


@router.post("/{workspace_id}/activate", response_model=WorkspaceInfo)
async def activate_workspace(workspace_id: str):
    ws = await workspace_manager.set_active(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.post("/deactivate")
async def deactivate_workspace():
    await workspace_manager.deactivate()
    return {"status": "deactivated"}


@router.get("/{workspace_id}/tree", response_model=list[FileTreeNode])
async def get_file_tree(
    workspace_id: str,
    path: str = ".",
    max_depth: int = 3,
):
    return workspace_manager.get_file_tree(workspace_id, path, max_depth)


@router.get("/{workspace_id}/file", response_model=FileContent)
async def read_file(
    workspace_id: str,
    path: str,
    offset: int = 0,
    limit: Optional[int] = None,
):
    return workspace_manager.read_file(workspace_id, path, offset, limit)


# 개발 파일 확장자 MIME 오버라이드 (.ts → video/mp2t 방지 등)
_MIME_OVERRIDES = {
    ".ts": "text/plain", ".tsx": "text/plain", ".jsx": "text/plain",
    ".md": "text/markdown", ".yml": "text/yaml", ".yaml": "text/yaml",
    ".toml": "text/plain", ".rs": "text/plain", ".go": "text/plain",
    ".vue": "text/plain", ".svelte": "text/plain",
}


@router.get("/{workspace_id}/raw")
async def get_raw_file(workspace_id: str, path: str, download: bool = False):
    file_path = workspace_manager.get_raw_file_path(workspace_id, path)

    ext = file_path.suffix.lower()
    media_type = _MIME_OVERRIDES.get(ext)
    if not media_type:
        guessed, _ = mimetypes.guess_type(str(file_path))
        media_type = guessed or "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name,
        content_disposition_type="attachment" if download else "inline",
    )


@router.post("/{workspace_id}/upload")
async def upload_files(
    workspace_id: str,
    files: List[UploadFile] = File(...),
    path: str = Form(default="."),
):
    results = []
    for file in files:
        content = await file.read()
        rel_path = workspace_manager.upload_file(
            workspace_id, path, file.filename or "unnamed", content
        )
        results.append({"filename": file.filename, "path": rel_path})
    return {"status": "ok", "uploaded": results}


class RenameRequest(BaseModel):
    old_path: str
    new_path: str


class MkdirRequest(BaseModel):
    path: str


class DeleteFileRequest(BaseModel):
    path: str


@router.post("/{workspace_id}/rename")
async def rename_file(workspace_id: str, req: RenameRequest):
    result = workspace_manager.rename_file(workspace_id, req.old_path, req.new_path)
    return {"status": "ok", "message": result}


@router.post("/{workspace_id}/mkdir")
async def mkdir(workspace_id: str, req: MkdirRequest):
    result = workspace_manager.mkdir(workspace_id, req.path)
    return {"status": "ok", "message": result}


@router.post("/{workspace_id}/delete")
async def delete_file(workspace_id: str, req: DeleteFileRequest):
    result = workspace_manager.delete_path(workspace_id, req.path)
    return {"status": "ok", "message": result}


@router.post("/{workspace_id}/file")
async def write_file(workspace_id: str, req: WriteFileRequest):
    result = workspace_manager.write_file(workspace_id, req.path, req.content)
    return {"status": "ok", "message": result}


@router.post("/{workspace_id}/edit")
async def edit_file(workspace_id: str, req: EditFileRequest):
    try:
        result = workspace_manager.edit_file(workspace_id, req)
        return {"status": "ok", "message": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
