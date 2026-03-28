"""Generate HTML wrapper pages for non-HTML file types.

Wraps raw files (JSX, Markdown, SVG, CSS, JS, images, etc.) in an HTML page
that can be rendered inside an iframe, using CDN-loaded libraries for
transpilation, syntax highlighting, and rendering.
"""

from pathlib import Path

ALLOWED_EXTENSIONS = {
    ".html", ".htm",
    ".jsx", ".tsx", ".js", ".mjs", ".ts",
    ".css",
    ".md",
    ".json", ".xml", ".txt", ".csv",
    ".svg",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
}

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}

_PRISM_LANG_MAP = {
    ".js": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".json": "json",
    ".xml": "xml",
    ".css": "css",
    ".csv": "plain",
    ".txt": "plain",
}


def is_allowed_extension(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


def needs_wrapper(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext not in (".html", ".htm")


def generate_wrapper(page_id: str, filename: str, file_path: Path) -> str:
    ext = Path(filename).suffix.lower()
    raw_url = f"/api/pages/{page_id}/raw"

    if ext in (".jsx", ".tsx"):
        return _wrap_jsx(raw_url, filename, file_path)
    if ext == ".md":
        return _wrap_markdown(raw_url, filename)
    if ext == ".svg":
        return _wrap_svg(file_path, filename)
    if ext == ".css":
        return _wrap_css(raw_url, filename, file_path)
    if ext in _IMAGE_EXTENSIONS:
        return _wrap_image(raw_url, filename)
    if ext in _PRISM_LANG_MAP:
        return _wrap_code(raw_url, filename, ext)

    # Fallback: plain text
    return _wrap_code(raw_url, filename, ".txt")


# ---------------------------------------------------------------------------
# Wrapper generators
# ---------------------------------------------------------------------------

_BASE_STYLE = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0a; color: #e5e5e5; }
"""

_TOOLBAR_HTML = """\
<div id="toolbar" style="
  position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;
  padding:8px 16px;background:rgba(20,20,20,0.95);backdrop-filter:blur(12px);
  border-bottom:1px solid rgba(255,255,255,0.06);font-size:11px;font-weight:600;
  letter-spacing:0.05em;color:rgba(255,255,255,0.5);
">
  <span>{badge} <span style="color:rgba(255,255,255,0.7);margin-left:6px">{filename}</span></span>
  <button onclick="navigator.clipboard.writeText(document.getElementById('code-src').textContent)" style="
    background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);
    color:rgba(255,255,255,0.6);padding:4px 10px;border-radius:4px;cursor:pointer;
    font-size:10px;font-weight:700;letter-spacing:0.08em;
  ">COPY</button>
</div>
"""


def _extract_bare_imports(source: str) -> set[str]:
    """Extract bare (non-relative) package names from import statements."""
    import re

    packages: set[str] = set()
    # Match `from "pkg"` or `from 'pkg'` — works regardless of multiline import braces
    for m in re.finditer(r"""\bfrom\s+['"]([^'"]+)['"]""", source):
        spec = m.group(1)
        # Skip relative imports
        if spec.startswith(".") or spec.startswith("/"):
            continue
        # For scoped packages (@foo/bar), keep the full scope
        if spec.startswith("@"):
            parts = spec.split("/")
            packages.add("/".join(parts[:2]))
        else:
            packages.add(spec.split("/")[0])
    return packages


def _build_importmap(packages: set[str]) -> str:
    """Generate an importmap JSON mapping packages to esm.sh URLs."""
    import json as _json

    imports: dict[str, str] = {}
    for pkg in sorted(packages):
        imports[pkg] = f"https://esm.sh/{pkg}"
        imports[f"{pkg}/"] = f"https://esm.sh/{pkg}/"
    return _json.dumps({"imports": imports}, indent=2)


def _detect_default_export(source: str) -> str | None:
    """Detect the name of the default-exported component."""
    import re

    # export default function Foo
    m = re.search(r"export\s+default\s+(?:function|class)\s+(\w+)", source)
    if m:
        return m.group(1)
    # export default Foo;
    m = re.search(r"export\s+default\s+(\w+)\s*;", source)
    if m:
        return m.group(1)
    return None


def _wrap_jsx(raw_url: str, filename: str, file_path: Path) -> str:
    source = file_path.read_text(encoding="utf-8")
    is_tsx = filename.lower().endswith(".tsx")
    babel_presets = '[["react", { "runtime": "automatic" }]]' if not is_tsx else '[["react", { "runtime": "automatic" }], "typescript"]'

    packages = _extract_bare_imports(source)
    # Always include react + react-dom (used by auto-render code)
    packages.update({"react", "react-dom"})
    importmap = _build_importmap(packages)

    # Detect default export and build auto-render suffix
    comp_name = _detect_default_export(source)
    # Remove "export default" so it becomes a plain declaration in module scope
    if comp_name:
        import re
        source = re.sub(r"export\s+default\s+", "", source, count=1)

    # Fallback: try common component names
    render_target = comp_name or "App"
    # Append auto-render code (uses react/react-dom via importmap)
    auto_render = f"""
import {{ createRoot as __createRoot }} from "react-dom/client";
import {{ createElement as __ce }} from "react";
if (typeof {render_target} !== "undefined") {{
  __createRoot(document.getElementById("root")).render(__ce({render_target}));
}}"""
    source_with_render = source + "\n" + auto_render
    # Escape backticks and backslashes for JS template literal
    escaped = source_with_render.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{filename}</title>
<script type="importmap">{importmap}</script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<style>
{_BASE_STYLE}
#root {{ min-height: 100vh; padding: 24px; }}
#error {{ display:none;padding:24px;color:#f87171;font-family:monospace;white-space:pre-wrap; }}
</style>
</head><body>
<div id="root"></div>
<div id="error"></div>
<script>
try {{
  const src = `{escaped}`;
  const out = Babel.transform(src, {{ presets: {babel_presets} }}).code;
  const el = document.createElement("script");
  el.type = "module";
  el.textContent = out;
  document.body.appendChild(el);
}} catch(e) {{
  const err = document.getElementById("error");
  err.style.display = "block";
  err.textContent = e.message;
}}
</script>
</body></html>"""


def _wrap_markdown(raw_url: str, filename: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{filename}</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-dark.min.css">
<style>
{_BASE_STYLE}
.markdown-body {{ max-width: 860px; margin: 0 auto; padding: 32px 24px; }}
.markdown-body img {{ max-width: 100%; }}
</style>
</head><body>
<article class="markdown-body" id="content"></article>
<script>
fetch("{raw_url}")
  .then(r => r.text())
  .then(md => {{
    document.getElementById("content").innerHTML = marked.parse(md);
  }});
</script>
</body></html>"""


def _wrap_svg(file_path: Path, filename: str) -> str:
    svg_content = file_path.read_text(encoding="utf-8")
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{filename}</title>
<style>
{_BASE_STYLE}
body {{ display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 24px; }}
.svg-container {{ max-width: 90vw; max-height: 90vh; }}
.svg-container svg {{ max-width: 100%; max-height: 85vh; height: auto; }}
</style>
</head><body>
<div class="svg-container">
{svg_content}
</div>
</body></html>"""


def _wrap_css(raw_url: str, filename: str, file_path: Path) -> str:
    source = file_path.read_text(encoding="utf-8")
    # Escape for embedding in HTML
    escaped = source.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{filename}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/prismjs@1/themes/prism-tomorrow.min.css">
<style>
{_BASE_STYLE}
.layout {{ display: grid; grid-template-columns: 1fr 1fr; height: 100vh; }}
.preview-pane {{ border-right: 1px solid rgba(255,255,255,0.06); overflow: auto; }}
.preview-pane iframe {{ width: 100%; height: 100%; border: none; background: white; }}
.code-pane {{ overflow: auto; }}
pre {{ margin: 0; padding: 16px; font-size: 13px; line-height: 1.6; }}
@media (max-width: 768px) {{
  .layout {{ grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; }}
}}
</style>
</head><body>
{_TOOLBAR_HTML.format(badge=f'<span style="color:{_badge_color(".css")}">CSS</span>', filename=filename)}
<div class="layout">
  <div class="preview-pane">
    <iframe srcdoc='<!DOCTYPE html><html><head><link rel="stylesheet" href="{raw_url}"></head><body>
      <div style="padding:24px;font-family:sans-serif">
        <h1>Heading 1</h1><h2>Heading 2</h2><h3>Heading 3</h3>
        <p>Paragraph text with <a href="#">a link</a> and <strong>bold</strong> and <em>italic</em>.</p>
        <button>Button</button> <input placeholder="Input field">
        <ul><li>List item 1</li><li>List item 2</li></ul>
        <table border="1" cellpadding="8"><tr><th>Header</th><th>Header</th></tr><tr><td>Cell</td><td>Cell</td></tr></table>
      </div>
    </body></html>'></iframe>
  </div>
  <div class="code-pane">
    <pre><code id="code-src" class="language-css">{escaped}</code></pre>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/prismjs@1/prism.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-css.min.js"></script>
<script>Prism.highlightAll();</script>
</body></html>"""


def _wrap_image(raw_url: str, filename: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{filename}</title>
<style>
{_BASE_STYLE}
body {{ display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 24px; }}
img {{ max-width: 90vw; max-height: 90vh; object-fit: contain; border-radius: 4px; }}
</style>
</head><body>
<img src="{raw_url}" alt="{filename}">
</body></html>"""


def _wrap_code(raw_url: str, filename: str, ext: str) -> str:
    lang = _PRISM_LANG_MAP.get(ext, "plain")
    prism_component = f'<script src="https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-{lang}.min.js"></script>' if lang != "plain" else ""
    badge_label = ext.lstrip(".").upper()

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{filename}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/prismjs@1/themes/prism-tomorrow.min.css">
<style>
{_BASE_STYLE}
pre {{ padding: 16px; font-size: 13px; line-height: 1.6; overflow: auto; }}
code {{ font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace; }}
</style>
</head><body>
{_TOOLBAR_HTML.format(badge=f'<span style="color:{_badge_color(ext)}">{badge_label}</span>', filename=filename)}
<pre><code id="code-src" class="language-{lang}"></code></pre>
<script src="https://cdn.jsdelivr.net/npm/prismjs@1/prism.min.js"></script>
{prism_component}
<script>
fetch("{raw_url}")
  .then(r => r.text())
  .then(src => {{
    document.getElementById("code-src").textContent = src;
    Prism.highlightAll();
  }});
</script>
</body></html>"""


def inject_storage_bridge(html: str, page_id: str) -> str:
    """Inject window.storage bridge script into HTML before </head>."""
    script = f"""<script>
(function() {{
  const BASE = "/api/pages/{page_id}/kv";
  window.storage = {{
    async get(key) {{
      const r = await fetch(BASE + "/" + encodeURIComponent(key), {{ cache: "no-store" }});
      if (!r.ok) return null;
      return await r.json();
    }},
    async set(key, value) {{
      const r = await fetch(BASE + "/" + encodeURIComponent(key), {{
        method: "PUT",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ value: String(value) }})
      }});
      return r.ok;
    }},
    async delete(key) {{
      const r = await fetch(BASE + "/" + encodeURIComponent(key), {{ method: "DELETE" }});
      return r.ok;
    }},
    async list() {{
      const r = await fetch(BASE, {{ cache: "no-store" }});
      if (!r.ok) return [];
      return await r.json();
    }}
  }};
}})();
</script>
"""
    # Insert before </head> if present, otherwise prepend
    lower = html.lower()
    idx = lower.find("</head>")
    if idx != -1:
        return html[:idx] + script + html[idx:]
    return script + html


def inject_live_reload(html: str, page_id: str, version_url: str | None = None) -> str:
    """Inject live-reload polling script before </body>.

    Polls the version endpoint every 3 seconds and reloads when content changes.
    """
    url = version_url or f"/api/pages/{page_id}/__version__"
    # Debounced soft-reload: 버전 변경 감지 후 2초 안정화 대기 → fetch+document.write로
    # 페이지를 교체하여 화면 깜빡임(white flash) 없이 반영.
    script = f"""<script>
(function(){{var v=null,t=null;
function softReload(){{
var el=document.documentElement;el.style.transition="opacity .2s";el.style.opacity="0";
setTimeout(function(){{fetch(location.href,{{cache:"no-store"}})
.then(function(r){{return r.text()}}).then(function(h){{document.open();document.write(h);document.close()}})
.catch(function(){{location.reload()}})}},200)}}
setInterval(function(){{
fetch("{url}").then(function(r){{return r.json()}}).then(function(d){{
if(v!==null&&d.v!==v){{clearTimeout(t);t=setTimeout(softReload,2000)}}
v=d.v}}).catch(function(){{}})
}},3000)}})();
</script>
<script>document.documentElement.style.cssText="transition:opacity .3s;opacity:0";
window.addEventListener("load",function(){{document.documentElement.style.opacity="1"}});
if(document.readyState==="complete")document.documentElement.style.opacity="1";</script>"""
    lower = html.lower()
    idx = lower.find("</body>")
    if idx != -1:
        return html[:idx] + script + html[idx:]
    return html + script


def _badge_color(ext: str) -> str:
    colors = {
        ".jsx": "#f97316",
        ".tsx": "#3b82f6",
        ".js": "#eab308",
        ".mjs": "#eab308",
        ".ts": "#3b82f6",
        ".css": "#06b6d4",
        ".md": "#a855f7",
        ".json": "#22c55e",
        ".xml": "#ef4444",
        ".txt": "#737373",
        ".csv": "#22c55e",
        ".svg": "#ec4899",
    }
    return colors.get(ext, "#737373")
