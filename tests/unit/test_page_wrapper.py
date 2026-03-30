"""Unit tests for core/page_wrapper.py — HTML wrapper generation."""

from pathlib import Path

from core.page_wrapper import (
    ALLOWED_EXTENSIONS,
    _badge_color,
    _build_importmap,
    _detect_default_export,
    _extract_bare_imports,
    generate_wrapper,
    inject_live_reload,
    inject_storage_bridge,
    is_allowed_extension,
    needs_wrapper,
)


# ── is_allowed_extension ──────────────────────────────────────────────


class TestIsAllowedExtension:
    def test_html_allowed(self):
        assert is_allowed_extension("page.html") is True
        assert is_allowed_extension("page.htm") is True

    def test_code_extensions(self):
        assert is_allowed_extension("app.jsx") is True
        assert is_allowed_extension("app.tsx") is True
        assert is_allowed_extension("main.js") is True
        assert is_allowed_extension("style.css") is True
        assert is_allowed_extension("readme.md") is True

    def test_image_extensions(self):
        assert is_allowed_extension("photo.png") is True
        assert is_allowed_extension("photo.jpg") is True
        assert is_allowed_extension("photo.jpeg") is True
        assert is_allowed_extension("anim.gif") is True
        assert is_allowed_extension("image.webp") is True

    def test_data_extensions(self):
        assert is_allowed_extension("data.json") is True
        assert is_allowed_extension("config.xml") is True
        assert is_allowed_extension("notes.txt") is True
        assert is_allowed_extension("table.csv") is True

    def test_disallowed_extension(self):
        assert is_allowed_extension("archive.zip") is False
        assert is_allowed_extension("binary.exe") is False
        assert is_allowed_extension("data.pdf") is False

    def test_case_insensitive(self):
        assert is_allowed_extension("FILE.HTML") is True
        assert is_allowed_extension("Image.PNG") is True


# ── needs_wrapper ─────────────────────────────────────────────────────


class TestNeedsWrapper:
    def test_html_no_wrapper(self):
        assert needs_wrapper("page.html") is False
        assert needs_wrapper("page.htm") is False

    def test_other_needs_wrapper(self):
        assert needs_wrapper("app.jsx") is True
        assert needs_wrapper("style.css") is True
        assert needs_wrapper("readme.md") is True
        assert needs_wrapper("data.json") is True
        assert needs_wrapper("image.png") is True


# ── _extract_bare_imports ─────────────────────────────────────────────


class TestExtractBareImports:
    def test_basic_import(self):
        source = 'import React from "react";\nimport { useState } from "react";'
        packages = _extract_bare_imports(source)
        assert "react" in packages

    def test_scoped_package(self):
        source = 'import { Chart } from "@tremor/react";'
        packages = _extract_bare_imports(source)
        assert "@tremor/react" in packages

    def test_skip_relative_imports(self):
        source = 'import { helper } from "./utils";'
        packages = _extract_bare_imports(source)
        assert len(packages) == 0

    def test_skip_absolute_path(self):
        source = 'import { config } from "/absolute/path";'
        packages = _extract_bare_imports(source)
        assert len(packages) == 0

    def test_subpath_import(self):
        source = 'import { something } from "lodash/fp";'
        packages = _extract_bare_imports(source)
        assert "lodash" in packages

    def test_empty_source(self):
        packages = _extract_bare_imports("")
        assert len(packages) == 0


# ── _build_importmap ──────────────────────────────────────────────────


class TestBuildImportmap:
    def test_basic_importmap(self):
        result = _build_importmap({"react"})
        assert "react" in result
        assert "esm.sh" in result

    def test_empty_packages(self):
        result = _build_importmap(set())
        assert "imports" in result

    def test_multiple_packages(self):
        result = _build_importmap({"react", "lodash"})
        assert "react" in result
        assert "lodash" in result


# ── _detect_default_export ────────────────────────────────────────────


class TestDetectDefaultExport:
    def test_function_export(self):
        source = "export default function App() { return null; }"
        assert _detect_default_export(source) == "App"

    def test_class_export(self):
        source = "export default class MyComponent {}"
        assert _detect_default_export(source) == "MyComponent"

    def test_identifier_export(self):
        source = "function Foo() {}\nexport default Foo;"
        assert _detect_default_export(source) == "Foo"

    def test_no_default_export(self):
        source = "export function helper() {}"
        assert _detect_default_export(source) is None

    def test_empty_source(self):
        assert _detect_default_export("") is None


# ── generate_wrapper ──────────────────────────────────────────────────


class TestGenerateWrapper:
    def test_jsx_wrapper(self, tmp_path: Path):
        f = tmp_path / "App.jsx"
        f.write_text('export default function App() { return <div>Hello</div>; }')
        html = generate_wrapper("page1", "App.jsx", f)
        assert "<!DOCTYPE html>" in html
        assert "babel" in html.lower() or "Babel" in html

    def test_tsx_wrapper(self, tmp_path: Path):
        f = tmp_path / "App.tsx"
        f.write_text('export default function App() { return <div>Hello</div>; }')
        html = generate_wrapper("page1", "App.tsx", f)
        assert "typescript" in html.lower()

    def test_markdown_wrapper(self, tmp_path: Path):
        f = tmp_path / "readme.md"
        f.write_text("# Hello")
        html = generate_wrapper("page1", "readme.md", f)
        assert "marked" in html.lower()
        assert "markdown" in html.lower()

    def test_svg_wrapper(self, tmp_path: Path):
        f = tmp_path / "icon.svg"
        f.write_text('<svg><circle r="10"/></svg>')
        html = generate_wrapper("page1", "icon.svg", f)
        assert "<svg>" in html
        assert "circle" in html

    def test_css_wrapper(self, tmp_path: Path):
        f = tmp_path / "style.css"
        f.write_text("body { color: red; }")
        html = generate_wrapper("page1", "style.css", f)
        assert "prism" in html.lower()
        assert "body" in html

    def test_image_wrapper(self, tmp_path: Path):
        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG")
        html = generate_wrapper("page1", "photo.png", f)
        assert "<img" in html
        assert "photo.png" in html

    def test_json_wrapper(self, tmp_path: Path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        html = generate_wrapper("page1", "data.json", f)
        assert "prism" in html.lower()

    def test_txt_fallback(self, tmp_path: Path):
        f = tmp_path / "notes.txt"
        f.write_text("plain text content")
        html = generate_wrapper("page1", "notes.txt", f)
        assert "<!DOCTYPE html>" in html

    def test_unknown_falls_back_to_txt(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c\n1,2,3")
        html = generate_wrapper("page1", "data.csv", f)
        assert "<!DOCTYPE html>" in html


# ── inject_storage_bridge ─────────────────────────────────────────────


class TestInjectStorageBridge:
    def test_inserts_before_head_close(self):
        html = "<html><head><title>T</title></head><body></body></html>"
        result = inject_storage_bridge(html, "page1")
        assert "window.storage" in result
        assert result.index("window.storage") < result.index("</head>")

    def test_prepends_if_no_head(self):
        html = "<div>No head tag</div>"
        result = inject_storage_bridge(html, "page1")
        assert result.startswith("<script>")
        assert "window.storage" in result

    def test_contains_page_id(self):
        html = "<html><head></head><body></body></html>"
        result = inject_storage_bridge(html, "my-page-id")
        assert "my-page-id" in result


# ── inject_live_reload ────────────────────────────────────────────────


class TestInjectLiveReload:
    def test_inserts_before_body_close(self):
        html = "<html><head></head><body><p>Content</p></body></html>"
        result = inject_live_reload(html, "page1")
        assert "setInterval" in result
        idx_script = result.index("setInterval")
        idx_body = result.index("</body>")
        assert idx_script < idx_body

    def test_appends_if_no_body(self):
        html = "<div>No body tag</div>"
        result = inject_live_reload(html, "page1")
        assert "setInterval" in result
        assert result.endswith("</script>")

    def test_custom_version_url(self):
        html = "<html><head></head><body></body></html>"
        result = inject_live_reload(html, "page1", version_url="/custom/version")
        assert "/custom/version" in result

    def test_default_version_url(self):
        html = "<html><head></head><body></body></html>"
        result = inject_live_reload(html, "page1")
        assert "/api/pages/page1/__version__" in result


# ── _badge_color ──────────────────────────────────────────────────────


class TestBadgeColor:
    def test_known_extensions(self):
        assert _badge_color(".jsx") == "#f97316"
        assert _badge_color(".tsx") == "#3b82f6"
        assert _badge_color(".css") == "#06b6d4"
        assert _badge_color(".md") == "#a855f7"

    def test_unknown_extension(self):
        assert _badge_color(".xyz") == "#737373"
