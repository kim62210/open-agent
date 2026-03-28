import hashlib
import json
import logging
import os
import shutil
import ssl
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from open_agent.models.page import PageInfo

logger = logging.getLogger(__name__)


def _check_frameable(url: str) -> bool:
    """Check if a URL allows being framed by inspecting response headers."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header(
            "User-Agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            xfo = (resp.headers.get("X-Frame-Options") or "").upper()
            if xfo in ("DENY", "SAMEORIGIN"):
                return False
            csp = resp.headers.get("Content-Security-Policy") or ""
            for directive in csp.split(";"):
                if "frame-ancestors" in directive:
                    sources = directive.strip().split()[1:]
                    if "*" in sources:
                        return True
                    return False
            return True
    except Exception:
        return True


class PageManager:
    def __init__(self):
        self._pages: Dict[str, PageInfo] = {}
        self._pages_dir: Optional[Path] = None
        self._config_path: Optional[Path] = None
        self._active_page_id: Optional[str] = None
        self._versions: Dict[str, int] = {}  # page_id -> version (ms timestamp)

    def bump_version(self, page_id: str) -> None:
        """Increment page version — triggers live-reload for viewers."""
        self._versions[page_id] = int(time.time() * 1000)

    def get_version(self, page_id: str) -> int:
        """Get current page version for live-reload polling."""
        return self._versions.get(page_id, 0)

    def load_config(self, config_path: str, pages_dir: str) -> None:
        pages_path = Path(pages_dir)
        if not pages_path.is_absolute():
            from open_agent.config import get_pages_dir
            pages_path = get_pages_dir()
        self._pages_dir = pages_path
        self._pages_dir.mkdir(parents=True, exist_ok=True)

        path = Path(config_path)
        if not path.is_absolute():
            from open_agent.config import get_config_path
            path = get_config_path(config_path)
        self._config_path = path

        if not path.exists():
            path.write_text(json.dumps({"pages": {}}, indent=2), encoding="utf-8")
            self._pages = {}
            return

        data = json.loads(path.read_text(encoding="utf-8"))

        # --- Migration: old format with "categories" key ---
        needs_migration = "categories" in data and data["categories"]
        if needs_migration:
            logger.info("Migrating old categories format to folder-based tree structure...")
            cat_to_folder: Dict[str, str] = {}

            # Convert categories to folder pages
            for cid, info in data["categories"].items():
                folder_id = cid  # reuse category id
                self._pages[folder_id] = PageInfo(
                    id=folder_id,
                    name=info["name"],
                    description=info.get("description", ""),
                    content_type="folder",
                    parent_id=None,
                )
                cat_to_folder[cid] = folder_id

            # Load pages with category_id -> parent_id conversion
            for pid, info in data.get("pages", {}).items():
                content_type = info.get("content_type", "html")
                filename = info.get("filename")
                size = 0
                if filename and self._pages_dir:
                    file_path = self._pages_dir / filename
                    size = file_path.stat().st_size if file_path.exists() else 0

                old_cat_id = info.get("category_id")
                parent_id = cat_to_folder.get(old_cat_id) if old_cat_id else None

                self._pages[pid] = PageInfo(
                    id=pid,
                    name=info["name"],
                    description=info.get("description", ""),
                    content_type=content_type,
                    parent_id=parent_id,
                    filename=filename,
                    size_bytes=size,
                    url=info.get("url"),
                    frameable=info.get("frameable"),
                )

            self._save_config()
            logger.info(f"Migration complete: {len(cat_to_folder)} categories -> folders")
        else:
            # Normal load (new format)
            for pid, info in data.get("pages", {}).items():
                content_type = info.get("content_type", "html")
                filename = info.get("filename")
                entry_file = info.get("entry_file")
                size = 0
                if content_type == "bundle" and self._pages_dir:
                    bundle_dir = self._pages_dir / pid
                    size = self._compute_size(bundle_dir)
                elif filename and self._pages_dir:
                    file_path = self._pages_dir / filename
                    size = file_path.stat().st_size if file_path.exists() else 0

                self._pages[pid] = PageInfo(
                    id=pid,
                    name=info["name"],
                    description=info.get("description", ""),
                    content_type=content_type,
                    parent_id=info.get("parent_id"),
                    filename=filename,
                    size_bytes=size,
                    entry_file=entry_file,
                    url=info.get("url"),
                    frameable=info.get("frameable"),
                    published=info.get("published", False),
                    host_password_hash=info.get("host_password_hash"),
                )

        logger.info(f"Loaded {len(self._pages)} pages from {path}")

    def _save_config(self) -> None:
        if not self._config_path:
            return
        data: dict = {"pages": {}}
        for pid, p in self._pages.items():
            page_data: dict = {
                "name": p.name,
                "description": p.description,
                "content_type": p.content_type,
            }
            if p.parent_id:
                page_data["parent_id"] = p.parent_id
            if p.filename:
                page_data["filename"] = p.filename
            if p.entry_file:
                page_data["entry_file"] = p.entry_file
            if p.url:
                page_data["url"] = p.url
            if p.frameable is not None:
                page_data["frameable"] = p.frameable
            if p.published:
                page_data["published"] = True
            if p.host_password_hash:
                page_data["host_password_hash"] = p.host_password_hash
            data["pages"][pid] = page_data

        self._config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # --- Folder operations ---

    def create_folder(self, name: str, description: str = "", parent_id: Optional[str] = None) -> PageInfo:
        folder_id = uuid.uuid4().hex[:8]
        folder = PageInfo(
            id=folder_id,
            name=name,
            description=description,
            content_type="folder",
            parent_id=parent_id,
        )
        self._pages[folder_id] = folder
        self._save_config()
        logger.info(f"Created folder: {name}")
        return folder

    def get_children(self, parent_id: Optional[str] = None) -> List[PageInfo]:
        return [p for p in self._pages.values() if p.parent_id == parent_id]

    def get_breadcrumb(self, page_id: Optional[str]) -> List[PageInfo]:
        """Return list from root to page_id (inclusive)."""
        crumbs: List[PageInfo] = []
        current_id = page_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            page = self._pages.get(current_id)
            if not page:
                break
            crumbs.append(page)
            current_id = page.parent_id
        crumbs.reverse()
        return crumbs

    # --- Page CRUD ---

    def get_all(self) -> List[PageInfo]:
        return list(self._pages.values())

    def get_page(self, page_id: str) -> Optional[PageInfo]:
        return self._pages.get(page_id)

    def get_page_dir(self, page_id: str) -> Optional[Path]:
        """Return the filesystem directory for a bundle page, or None."""
        page = self._pages.get(page_id)
        if not page or not self._pages_dir:
            return None
        if page.content_type == "bundle":
            d = self._pages_dir / page_id
            return d if d.is_dir() else None
        return None

    def get_html_path(self, page_id: str) -> Optional[Path]:
        page = self._pages.get(page_id)
        if not page or not self._pages_dir:
            return None
        if page.content_type == "bundle" and page.entry_file:
            p = self._pages_dir / page_id / page.entry_file
            return p if p.exists() else None
        if not page.filename:
            return None
        p = self._pages_dir / page.filename
        return p if p.exists() else None

    def add_page(self, name: str, description: str, html_bytes: bytes, original_filename: str, parent_id: Optional[str] = None) -> PageInfo:
        if not self._pages_dir:
            raise ValueError("PageManager not initialized")

        page_id = uuid.uuid4().hex[:8]
        ext = Path(original_filename).suffix or ".html"
        safe_filename = f"{page_id}{ext}"

        dest = self._pages_dir / safe_filename
        dest.write_bytes(html_bytes)

        page = PageInfo(
            id=page_id,
            name=name,
            description=description,
            content_type="html",
            parent_id=parent_id,
            filename=safe_filename,
            size_bytes=len(html_bytes),
        )
        self._pages[page_id] = page
        self._save_config()
        logger.info(f"Added page: {name} ({safe_filename})")
        return page

    def add_page_from_path(self, name: str, description: str, source_path: str, parent_id: Optional[str] = None) -> PageInfo:
        if not self._pages_dir:
            raise ValueError("PageManager not initialized")

        src = Path(source_path).resolve()
        if not src.is_file():
            raise ValueError(f"File not found: {source_path}")

        html_bytes = src.read_bytes()
        return self.add_page(name, description, html_bytes, src.name, parent_id=parent_id)

    def add_bookmark(self, name: str, url: str, description: str = "", parent_id: Optional[str] = None) -> PageInfo:
        page_id = uuid.uuid4().hex[:8]
        frameable = _check_frameable(url)
        page = PageInfo(
            id=page_id,
            name=name,
            description=description,
            content_type="url",
            parent_id=parent_id,
            url=url,
            frameable=frameable,
        )
        self._pages[page_id] = page
        self._save_config()
        logger.info(f"Added bookmark: {name} ({url}) frameable={frameable}")
        return page

    @staticmethod
    def _compute_size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return 0

    @staticmethod
    def _detect_entry_file(bundle_dir: Path) -> Optional[str]:
        # Priority: index.html > index.htm > first .html at root > first .html nested
        for name in ("index.html", "index.htm"):
            if (bundle_dir / name).exists():
                return name
        root_htmls = sorted(f.name for f in bundle_dir.iterdir() if f.is_file() and f.suffix.lower() in (".html", ".htm"))
        if root_htmls:
            return root_htmls[0]
        nested_htmls = sorted(str(f.relative_to(bundle_dir)) for f in bundle_dir.rglob("*.html"))
        nested_htmls += sorted(str(f.relative_to(bundle_dir)) for f in bundle_dir.rglob("*.htm"))
        if nested_htmls:
            return nested_htmls[0]
        return None

    def add_bundle(
        self,
        name: str,
        description: str,
        files: List[Tuple[str, bytes]],
        entry_file: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> PageInfo:
        if not self._pages_dir:
            raise ValueError("PageManager not initialized")

        page_id = uuid.uuid4().hex[:8]
        bundle_dir = self._pages_dir / page_id
        bundle_dir.mkdir(parents=True, exist_ok=True)

        for rel_path, content in files:
            # Path traversal defense
            safe = (bundle_dir / rel_path).resolve()
            if not safe.is_relative_to(bundle_dir.resolve()):
                continue
            safe.parent.mkdir(parents=True, exist_ok=True)
            safe.write_bytes(content)

        if not entry_file:
            entry_file = self._detect_entry_file(bundle_dir)
        if not entry_file:
            shutil.rmtree(bundle_dir)
            raise ValueError("번들에 HTML 파일이 없습니다.")

        size = self._compute_size(bundle_dir)
        page = PageInfo(
            id=page_id,
            name=name,
            description=description,
            content_type="bundle",
            parent_id=parent_id,
            entry_file=entry_file,
            size_bytes=size,
        )
        self._pages[page_id] = page
        self._save_config()
        logger.info(f"Added bundle: {name} ({page_id}/, entry={entry_file})")
        return page

    def get_bundle_file_path(self, page_id: str, file_path: str) -> Optional[Path]:
        page = self._pages.get(page_id)
        if not page or page.content_type != "bundle" or not self._pages_dir:
            return None
        bundle_dir = (self._pages_dir / page_id).resolve()
        target = (bundle_dir / file_path).resolve()
        if not target.is_relative_to(bundle_dir):
            return None
        return target if target.is_file() else None

    def check_and_update_frameable(self, page_id: str) -> Optional[bool]:
        page = self._pages.get(page_id)
        if not page or page.content_type != "url" or not page.url:
            return None
        frameable = _check_frameable(page.url)
        page.frameable = frameable
        self._pages[page_id] = page
        self._save_config()
        return frameable

    def update_page(self, page_id: str, name: Optional[str] = None, description: Optional[str] = None, parent_id: Optional[str] = "__unset__") -> Optional[PageInfo]:
        page = self._pages.get(page_id)
        if not page:
            return None

        if name is not None:
            page.name = name
        if description is not None:
            page.description = description
        if parent_id != "__unset__":
            page.parent_id = parent_id

        self._pages[page_id] = page
        self._save_config()
        return page

    def delete_page(self, page_id: str) -> bool:
        page = self._pages.get(page_id)
        if not page:
            return False

        # If it's a folder, recursively delete children
        if page.content_type == "folder":
            children = self.get_children(page_id)
            for child in children:
                self.delete_page(child.id)

        # Deactivate if this page is currently active
        if self._active_page_id == page_id:
            self._active_page_id = None

        self._pages.pop(page_id, None)

        if self._pages_dir and page.content_type == "bundle":
            bundle_dir = self._pages_dir / page_id
            if bundle_dir.is_dir():
                shutil.rmtree(bundle_dir)
        elif self._pages_dir and page.filename:
            html_file = self._pages_dir / page.filename
            if html_file.exists():
                html_file.unlink()

        self._save_config()
        logger.info(f"Deleted page: {page.name}")
        return True


    # --- Active page ---

    def activate_page(self, page_id: str) -> Optional[PageInfo]:
        page = self._pages.get(page_id)
        if not page or page.content_type == "folder":
            return None
        self._active_page_id = page_id
        logger.info(f"Activated page: {page.name} ({page_id})")
        return page

    def deactivate_page(self) -> None:
        self._active_page_id = None

    def get_active_page(self) -> Optional[PageInfo]:
        if not self._active_page_id:
            return None
        page = self._pages.get(self._active_page_id)
        if not page:
            # Page was deleted — clear stale reference
            self._active_page_id = None
            return None
        return page

    # --- Publish ---

    @staticmethod
    def _hash_password(password: str, salt: bytes | None = None) -> str:
        if salt is None:
            salt = os.urandom(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=100_000)
        return salt.hex() + ":" + dk.hex()

    def publish_page(self, page_id: str, published: bool, password: Optional[str] = None) -> Optional[PageInfo]:
        page = self._pages.get(page_id)
        if not page or page.content_type in ("folder", "url"):
            return None
        page.published = published
        if published and password:
            page.host_password_hash = self._hash_password(password)
        elif not published:
            page.host_password_hash = None
        self._pages[page_id] = page
        self._save_config()
        logger.info(f"{'Published' if published else 'Unpublished'} page: {page.name}")
        return page

    def verify_host_password(self, page_id: str, password: str) -> bool:
        page = self._pages.get(page_id)
        if not page:
            return False
        if not page.host_password_hash:
            return True  # no password set
        stored = page.host_password_hash
        if ":" in stored:
            salt_hex, _ = stored.split(":", 1)
            salt = bytes.fromhex(salt_hex)
            return self._hash_password(password, salt=salt) == stored
        # 레거시 SHA-256 해시 호환
        return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored

    def get_published_pages(self) -> List[PageInfo]:
        return [p for p in self._pages.values() if p.published and p.content_type not in ("folder", "url")]

    # --- Page file operations (for LLM tools) ---

    def _resolve_page_file(self, page_id: str, file_path: str) -> Optional[Path]:
        """Resolve a file path within a page, with path traversal protection."""
        page = self._pages.get(page_id)
        if not page or not self._pages_dir:
            return None

        if page.content_type == "bundle":
            base = (self._pages_dir / page_id).resolve()
            target = (base / file_path).resolve()
            if not target.is_relative_to(base):
                return None
            return target
        elif page.content_type == "html" and page.filename:
            # Single file: only the file itself is accessible
            if file_path == page.filename or file_path == Path(page.filename).name:
                return (self._pages_dir / page.filename).resolve()
        return None

    def list_page_files(self, page_id: str) -> Optional[List[str]]:
        """List files in a page."""
        page = self._pages.get(page_id)
        if not page or not self._pages_dir:
            return None

        if page.content_type == "bundle":
            bundle_dir = self._pages_dir / page_id
            if not bundle_dir.is_dir():
                return []
            return sorted(
                str(f.relative_to(bundle_dir))
                for f in bundle_dir.rglob("*")
                if f.is_file()
            )
        elif page.content_type == "html" and page.filename:
            return [page.filename]
        return []

    def read_page_file(self, page_id: str, file_path: str) -> Optional[str]:
        """Read a file from a page."""
        target = self._resolve_page_file(page_id, file_path)
        if not target or not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    def write_page_file(self, page_id: str, file_path: str, content: str) -> Optional[str]:
        """Write/create a file in a page. Returns the resolved path or None."""
        page = self._pages.get(page_id)
        if not page or not self._pages_dir:
            return None

        if page.content_type == "bundle":
            base = (self._pages_dir / page_id).resolve()
            target = (base / file_path).resolve()
            if not target.is_relative_to(base):
                return None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            # Update size
            page.size_bytes = self._compute_size(base)
            self._pages[page_id] = page
            self._save_config()
            self.bump_version(page_id)
            return str(target)
        elif page.content_type == "html" and page.filename:
            target = (self._pages_dir / page.filename).resolve()
            target.write_text(content, encoding="utf-8")
            page.size_bytes = len(content.encode("utf-8"))
            self._pages[page_id] = page
            self._save_config()
            self.bump_version(page_id)
            return str(target)
        return None

    def convert_to_bundle(self, page_id: str) -> Optional[PageInfo]:
        """Convert a single-file page to a bundle for multi-file editing."""
        page = self._pages.get(page_id)
        if not page or not self._pages_dir or page.content_type != "html" or not page.filename:
            return None

        src = self._pages_dir / page.filename
        if not src.is_file():
            return None

        bundle_dir = self._pages_dir / page_id
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # Move file into bundle, rename to meaningful name
        original_name = Path(page.filename).stem.split("_")[-1] if "_" in page.filename else page.filename
        ext = Path(page.filename).suffix
        dest_name = f"index{ext}" if ext in (".html", ".htm") else original_name
        dest = bundle_dir / dest_name
        shutil.copy2(str(src), str(dest))
        src.unlink()

        page.content_type = "bundle"
        page.entry_file = dest_name
        page.filename = None
        page.size_bytes = self._compute_size(bundle_dir)
        self._pages[page_id] = page
        self._save_config()
        logger.info(f"Converted page '{page.name}' to bundle")
        return page


    # --- KV Storage ---

    @staticmethod
    def _get_kv_path(page_id: str) -> Path:
        from open_agent.config import get_page_kv_dir
        return get_page_kv_dir() / f"{page_id}.json"

    @staticmethod
    def _load_kv(path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _save_kv(path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")

    def kv_list(self, page_id: str) -> Optional[List[str]]:
        if page_id not in self._pages:
            return None
        data = self._load_kv(self._get_kv_path(page_id))
        return list(data.keys())

    def kv_get(self, page_id: str, key: str) -> Optional[str]:
        if page_id not in self._pages:
            return None
        data = self._load_kv(self._get_kv_path(page_id))
        return data.get(key)

    def kv_set(self, page_id: str, key: str, value: str) -> bool:
        if page_id not in self._pages:
            return False
        path = self._get_kv_path(page_id)
        data = self._load_kv(path)
        data[key] = value
        serialized = json.dumps(data, ensure_ascii=False)
        if len(serialized.encode("utf-8")) > 1_048_576:  # 1MB limit
            raise ValueError("KV storage size limit exceeded (max 1MB per page)")
        self._save_kv(path, data)
        # KV는 페이지 자체 상태 저장용 — bump_version 하지 않음
        # (버전 변경 시 뷰어가 iframe을 리로드하여 사용자 입력이 소멸되므로)
        return True

    def kv_delete(self, page_id: str, key: str) -> bool:
        if page_id not in self._pages:
            return False
        path = self._get_kv_path(page_id)
        data = self._load_kv(path)
        if key not in data:
            return False
        del data[key]
        self._save_kv(path, data)
        return True


page_manager = PageManager()
