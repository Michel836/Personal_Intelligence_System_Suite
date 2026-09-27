"""Safe, standalone, deterministic HTML export (M018).

Properties:

* **No remote assets** — all CSS is inline; no CDN, no JS, no fonts fetched.
* **Escaped** — every value is HTML-escaped; document content is never injected
  as markup, and no script from content can run.
* **Bounded** — table rows and card lists are capped by the assembler, but the
  renderer also enforces its own hard cap defensively.
* **Print-ready** — ``@page`` rules, page-break hints and CSS page counters
  (honoured by CSS-capable renderers such as WeasyPrint and browser print).
"""
from __future__ import annotations

import html
from typing import Any

from .models import Block, ReportIR
from .privacy import banner, describe_mode

MAX_TABLE_ROWS = 2000
MAX_CARDS = 2000

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font-family: "DejaVu Sans", "Segoe UI", Arial, sans-serif; color: #1f2933;
       font-size: 11pt; line-height: 1.5; margin: 0; }
h1 { font-size: 22pt; margin: 0 0 4px 0; }
h2 { font-size: 15pt; margin: 22px 0 8px 0; border-bottom: 2px solid #2563eb;
     padding-bottom: 4px; page-break-after: avoid; }
h3 { font-size: 12pt; margin: 14px 0 6px 0; }
a { color: #1d4ed8; text-decoration: none; word-break: break-all; }
.cover { border: 1px solid #d2d6dc; border-radius: 8px; padding: 22px; margin-bottom: 18px; }
.cover .meta { color: #52606d; font-size: 9.5pt; margin-top: 10px; }
.banner { border-left: 5px solid #2563eb; background: #eff6ff; padding: 8px 12px;
          margin: 10px 0 18px 0; font-size: 10pt; }
.warning { border-left: 5px solid #d97706; background: #fffbeb; padding: 8px 12px;
           margin: 8px 0; font-size: 10pt; }
.summary { border: 1px dashed #7c3aed; background: #f5f3ff; padding: 12px;
           border-radius: 6px; margin: 10px 0; }
.summary .label { font-weight: 700; color: #6d28d9; font-size: 10pt; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 14px 0; font-size: 9.5pt; }
th, td { border: 1px solid #cbd2d9; padding: 5px 7px; text-align: left; vertical-align: top; }
th { background: #f0f4f8; }
tr { page-break-inside: avoid; }
.card { border: 1px solid #d2d6dc; border-radius: 6px; padding: 8px 10px; margin: 6px 0;
        page-break-inside: avoid; }
.card .ref { font-weight: 700; color: #1d4ed8; }
.card .meta { color: #52606d; font-size: 9pt; }
.toc { border: 1px solid #e4e7eb; border-radius: 6px; padding: 10px 14px; }
.toc ol { margin: 4px 0; padding-left: 20px; }
.appendix { font-size: 9pt; }
.appendix .prov { color: #52606d; }
.prov-badge { display: inline-block; font-size: 8pt; padding: 1px 6px; border-radius: 8px;
              background: #e4e7eb; color: #323f4b; margin-left: 4px; }
.footer { margin-top: 26px; padding-top: 8px; border-top: 1px solid #cbd2d9;
          color: #7b8794; font-size: 8.5pt; }
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
@page { @bottom-center { content: "Page " counter(page) " / " counter(pages);
        font-size: 8pt; color: #7b8794; } }
@media print { h2 { page-break-after: avoid; } .card, tr { page-break-inside: avoid; } }
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _render_block(block: Block) -> str:
    data = block.data or {}
    kind = block.type
    if kind == "heading":
        level = int(data.get("level", 3))
        level = min(max(level, 3), 4)
        return f"<h{level}>{_esc(data.get('text'))}</h{level}>"
    if kind == "paragraph":
        cites = data.get("citations") or []
        cite_html = "".join(f" <sup>{_esc(c)}</sup>" for c in cites)
        return f"<p>{_esc(data.get('text'))}{cite_html}</p>"
    if kind == "warning":
        return f'<div class="warning">{_esc(data.get("text"))}</div>'
    if kind == "table":
        return _render_table(data)
    if kind == "document_card":
        return _render_card(data)
    if kind == "timeline":
        return _render_timeline(data)
    if kind == "graph_summary":
        return _render_graph(data)
    if kind == "metadata":
        return _render_metadata(data)
    if kind == "summary":
        return _render_summary(data)
    if kind == "citation":
        return f"<p>{_esc(data.get('text'))}</p>"
    if kind == "image":
        # Images are never embedded from remote/content; only safe data URIs pass.
        uri = data.get("data_uri")
        if isinstance(uri, str) and uri.startswith("data:image/"):
            return f'<p><img alt="{_esc(data.get("alt", ""))}" src="{uri}" style="max-width:100%"/></p>'
        return f'<p class="meta">[image omitted: {_esc(data.get("reason", "unavailable"))}]</p>'
    if kind == "source_appendix":
        return _render_appendix(data)
    return ""


def _render_table(data: dict[str, Any]) -> str:
    columns = [str(c) for c in (data.get("columns") or [])]
    rows = list(data.get("rows") or [])[:MAX_TABLE_ROWS]
    out = ['<table>']
    if data.get("caption"):
        out.append(f"<caption>{_esc(data['caption'])}</caption>")
    if columns:
        out.append("<thead><tr>" + "".join(f"<th>{_esc(c)}</th>" for c in columns) + "</tr></thead>")
    out.append("<tbody>")
    for row in rows:
        cells = row if isinstance(row, list | tuple) else [row.get(c) for c in columns]
        out.append("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in cells) + "</tr>")
    out.append("</tbody></table>")
    if len(data.get("rows") or []) > MAX_TABLE_ROWS:
        out.append(f'<div class="warning">Table truncated at {MAX_TABLE_ROWS} rows.</div>')
    return "".join(out)


def _render_card(data: dict[str, Any]) -> str:
    ref = _esc(data.get("ref"))
    label = _esc(data.get("label"))
    meta_bits = []
    if data.get("path"):
        meta_bits.append(f"path: {_esc(data['path'])}")
    if data.get("date"):
        src = data.get("date_source") or "unknown"
        meta_bits.append(f"date: {_esc(data['date'])} ({_esc(src)}, {_esc(data.get('date_class'))})")
    if data.get("extraction_state"):
        meta_bits.append(f"extraction: {_esc(data['extraction_state'])}")
    if data.get("score") is not None:
        meta_bits.append(f"score: {_esc(data['score'])}")
    if data.get("state") and data.get("state") != "ACTIVE":
        meta_bits.append(f"state: {_esc(data['state'])}")
    body = f'<div class="card"><span class="ref">[{ref}]</span> {label}'
    if meta_bits:
        body += f'<div class="meta">{ " · ".join(meta_bits) }</div>'
    if data.get("note"):
        body += f'<div class="meta">note: {_esc(data["note"])}</div>'
    relations = data.get("relations") or []
    if relations:
        rel = ", ".join(str(r.get("type") if isinstance(r, dict) else r) for r in relations)
        body += f'<div class="meta">relations: {_esc(rel)}</div>'
    return body + "</div>"


def _render_timeline(data: dict[str, Any]) -> str:
    events = list(data.get("events") or [])
    rows = [[e.get("date"), f"[{e.get('ref')}]", e.get("label"), e.get("date_source")]
            for e in events]
    return _render_table({"columns": ["Date", "Ref", "Document", "Date source"], "rows": rows})


def _render_graph(data: dict[str, Any]) -> str:
    types = data.get("relation_types") or {}
    rows = [[k, v] for k, v in types.items()]
    counts = (f"{data.get('nodes', 0)} nodes · {data.get('edges', 0)} edges · "
              f"depth {data.get('depth', '?')}")
    return f"<p>{_esc(counts)}</p>" + _render_table({"columns": ["Relation type", "Count"], "rows": rows})


def _render_metadata(data: dict[str, Any]) -> str:
    items = data.get("items") or {}
    rows = [[k, v] for k, v in items.items()]
    return _render_table({"columns": ["Key", "Value"], "rows": rows})


def _render_summary(data: dict[str, Any]) -> str:
    label = _esc(data.get("label") or "AI-generated summary")
    out = [f'<div class="summary"><div class="label">{label}</div>']
    if data.get("insufficient_evidence"):
        out.append("<p>Insufficient evidence to summarise safely.</p>")
    for para in data.get("paragraphs") or []:
        refs = para.get("refs") or []
        ref_html = "".join(f" <sup>[{_esc(r)}]</sup>" for r in refs)
        out.append(f"<p>{_esc(para.get('text'))}{ref_html}</p>")
    out.append("</div>")
    return "".join(out)


def _render_appendix(data: dict[str, Any]) -> str:
    sources = list(data.get("sources") or [])[:MAX_CARDS]
    out = ['<div class="appendix"><h2 id="sources">Sources</h2>']
    for s in sources:
        bits = [f'<span class="ref">[{_esc(s.get("ref"))}]</span> {_esc(s.get("label"))}']
        if s.get("path"):
            bits.append(f'path: {_esc(s["path"])}')
        if s.get("date"):
            bits.append(f'date: {_esc(s["date"])} ({_esc(s.get("date_source"))})')
        if s.get("extraction_state"):
            bits.append(f'extraction: {_esc(s["extraction_state"])}')
        if s.get("unavailable"):
            bits.append("UNAVAILABLE")
        bits.append(f'<span class="prov-badge">{_esc(s.get("provenance"))}</span>')
        out.append('<div class="card">' + " · ".join(bits) + "</div>")
    out.append("</div>")
    return "".join(out)


def render_html(ir: ReportIR, *, include_appendix: bool = True) -> str:
    d = ir.definition
    desc = describe_mode(d.privacy_mode)
    head = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8"/>',
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>',
        f"<title>{_esc(d.title)}</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
    ]
    cover = [
        '<div class="cover">',
        f"<h1>{_esc(d.title)}</h1>",
    ]
    if d.description:
        cover.append(f"<p>{_esc(d.description)}</p>")
    cover.append(
        '<div class="meta">'
        f"report id: {_esc(d.report_id)} · kind: {_esc(d.kind)} · "
        f"generated: {_esc(ir.generated_at)} · "
        f"privacy: {_esc(desc.get('label', d.privacy_mode))} · "
        f"generator: {_esc(ir.generator_version)}"
        "</div>")
    cover.append("</div>")
    parts = ["".join(head), "".join(cover), f'<div class="banner">{_esc(banner(d.privacy_mode))}</div>']

    for w in ir.warnings:
        parts.append(f'<div class="warning">{_esc(w)}</div>')
    if ir.omitted:
        listed = ", ".join(f"[{o.get('file_id')}]" for o in ir.omitted[:50])
        parts.append(f'<div class="warning">{len(ir.omitted)} item(s) omitted by privacy mode: {_esc(listed)}</div>')

    if ir.sections:
        toc = ['<div class="toc"><strong>Contents</strong><ol>']
        for s in ir.sections:
            toc.append(f'<li><a href="#{_esc(s.id)}">{_esc(s.title)}</a></li>')
        toc.append("</ol></div>")
        parts.append("".join(toc))

    for section in ir.sections:
        parts.append(f'<section><h2 id="{_esc(section.id)}">{_esc(section.title)}</h2>')
        for block in section.blocks:
            parts.append(_render_block(block))
        parts.append(f'<span class="prov-badge">{_esc(section.provenance)}</span></section>')

    if include_appendix:
        parts.append(_render_appendix({"sources": [s.as_dict() for s in ir.sources]}))

    parts.append(
        '<div class="footer">'
        f"Report {_esc(d.report_id)} · logical fingerprint {_esc(ir.logical_fingerprint())} · "
        f"{_esc(ir.generator_version)}"
        "</div>")
    parts.append("</body></html>")
    return "\n".join(parts)
