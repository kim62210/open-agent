#!/usr/bin/env python3
import json, sys, pathlib, html

# -------------------------------------------------------------------
# 1. Input/output paths (absolute paths)
# -------------------------------------------------------------------
if len(sys.argv) != 3:
    print('Usage: json2html.py <json_path> <output_html_path>')
    sys.exit(1)

json_path = pathlib.Path(sys.argv[1])
output_html = pathlib.Path(sys.argv[2])

# -------------------------------------------------------------------
# 2. Load JSON
# -------------------------------------------------------------------
with json_path.open(encoding='utf-8') as f:
    data = json.load(f)

# -------------------------------------------------------------------
# 3. HTML fragment generation functions
# -------------------------------------------------------------------
def esc(txt):
    return html.escape(str(txt))

def _safe_get(obj, *keys, default='-'):
    """Safely extract value from nested dict. Returns default if key is missing."""
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current

def render_item(item):
    if not isinstance(item, dict):
        return ""
    h_min = _safe_get(item, 'hardness', 'min')
    h_max = _safe_get(item, 'hardness', 'max')
    bs_val = _safe_get(item, 'breakingStrength', 'value')
    h_scale = _safe_get(item, 'hardness', 'scale')
    bs_fixture = _safe_get(item, 'breakingStrength', 'test', 'fixture')
    bs_span = _safe_get(item, 'breakingStrength', 'test', 'spanMm')
    bs_unit = _safe_get(item, 'breakingStrength', 'unit')
    tracks = ', '.join(item.get('compatibleTracks', [])) or '-'
    is_active = item.get('isActive', False)
    return f"""
    <tr>
        <td>{esc(item.get('id', '-'))}</td>
        <td>{esc(item.get('name', '-'))}</td>
        <td>{'✓' if is_active else '✗'}</td>
        <td>{esc(item.get('materialNumber', '-'))}</td>
        <td>{esc(tracks)}</td>
        <td>{esc(h_scale)} {esc(h_min)}~{esc(h_max)}</td>
        <td>{esc(bs_fixture)} {esc(bs_span)}mm</td>
        <td>{esc(bs_val)} {esc(bs_unit)}</td>
    </tr>
    """

def render_category(name, items):
    if not isinstance(items, list):
        return ""
    rows = '\n'.join(render_item(it) for it in items)
    return f"""
    <section>
        <h2>{esc(name)}</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th><th>Name</th><th>Active</th><th>Material No.</th>
                    <th>Compatible Tracks</th><th>Hardness</th><th>Test (Fixture, Span)</th><th>Breaking Strength</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </section>
    """

# -------------------------------------------------------------------
# 4. Assemble full HTML
# -------------------------------------------------------------------
sections = []
categories = data.get('categories', {})
if isinstance(categories, dict):
    for cat_name, items in categories.items():
        sections.append(render_category(cat_name, items))
elif isinstance(categories, list):
    for i, items in enumerate(categories):
        sections.append(render_category(f"Category {i+1}", items if isinstance(items, list) else []))
body_html = '\n'.join(sections)

# -------------------------------------------------------------------
# 5. Insert into existing index.html
# -------------------------------------------------------------------
with output_html.open('r', encoding='utf-8') as f:
    template = f.read()

PLACEHOLDER = '<div id="content">(generating...)</div>'
if PLACEHOLDER in template:
    final_html = template.replace(PLACEHOLDER, f'<div id="content">{body_html}</div>')
else:
    print('Warning: placeholder not found. Overwriting full body.', file=sys.stderr)
    final_html = f'<html><body><div id="content">{body_html}</div></body></html>'

with output_html.open('w', encoding='utf-8') as f:
    f.write(final_html)

print('HTML generation completed:', output_html)
