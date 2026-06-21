#!/usr/bin/env python3
"""
MPPE Diário Oficial — build reportlab PDF report from matches.json.

Usage:
    python3 build_report.py matches.json [output.pdf]

Reads a JSON file produced by mppe_diario_search.py and renders a styled
PDF report (capa + sumário + detalhamento por edição).

Verified 2026-06-20: 38 matches → 22-page A4 PDF, ~60 KB.
"""
import json
import sys
import html as html_lib
from datetime import datetime
from pathlib import Path

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
    from reportlab.lib.enums import TA_JUSTIFY
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "reportlab"], check=False)
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
    from reportlab.lib.enums import TA_JUSTIFY


def main(matches_path: str, output_path=None):
    with open(matches_path) as f:
        data = json.load(f)

    # Accept both shapes:
    #   1) list of matches: [{item, match_count, hits}, ...]
    #   2) envelope: {name, start, end, results: [...]}
    if isinstance(data, dict) and "results" in data:
        matches = data["results"]
        envelope = data
    elif isinstance(data, list):
        matches = data
        envelope = None
    else:
        raise ValueError(f"JSON não é lista nem envelope com 'results': {type(data).__name__}")

    matches.sort(key=lambda m: m["item"]["date_created"] or "")

    if not output_path:
        slug = matches[0]["item"]["title"][:30].replace(" ", "_").replace(".", "").replace("/", "_") if matches else "relatorio"
        output_path = f"/Users/chlima/mppe-investigation/relatorio_{slug}.pdf"

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
        title="Publicações MPPE — relatório de menções",
        author="Hermes Agent",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=18, spaceAfter=12, textColor=HexColor("#003366"))
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4, textColor=HexColor("#003366"))
    h3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11, spaceBefore=6, spaceAfter=3, textColor=HexColor("#222"))
    meta = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=9, textColor=HexColor("#666666"), leading=11)
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=13, alignment=TA_JUSTIFY)
    quote = ParagraphStyle("Quote", parent=body, leftIndent=14, rightIndent=8, fontSize=9.5,
                            textColor=HexColor("#333333"), backColor=HexColor("#F4F4F4"),
                            borderPadding=4, spaceBefore=2, spaceAfter=4)

    story = []
    total_occurrences = sum(r["match_count"] for r in matches)

    # Window from envelope (preferred) or from first/last item date
    if envelope:
        search_name = envelope.get("name", "termo pesquisado")
        start_date = envelope.get("start", "?")
        end_date = envelope.get("end", "?")
        editions_total = envelope.get("editions_total", len(matches))
    else:
        first_item = matches[0]["item"] if matches else {}
        last_item = matches[-1]["item"] if matches else {}
        search_name = "termo pesquisado"
        start_date = (first_item.get("date_created") or "?")[:10]
        end_date = (last_item.get("date_created") or "?")[:10]
        editions_total = len(matches)

    story.append(Paragraph(
        f'Publicações do Diário Oficial do MPPE<br/>que mencionam <i>{search_name}</i>',
        title_style
    ))
    story.append(Paragraph(
        f"Janela consultada: <b>{start_date} → {end_date}</b> &nbsp;|&nbsp; "
        f"Total de edições analisadas: <b>{editions_total}</b> &nbsp;|&nbsp; "
        f"Edições com matches: <b>{len(matches)}</b> &nbsp;|&nbsp; "
        f"Total de ocorrências: <b>{total_occurrences}</b>",
        meta
    ))
    story.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')} por Hermes Agent &nbsp;|&nbsp; "
        f"Fonte: https://portal.mppe.mp.br/diario-oficial",
        meta
    ))
    story.append(Spacer(1, 8))

    # Sumário
    story.append(Paragraph("Sumário", h2))
    sum_rows = [["#", "Data", "Edição", "Ocorrências"]]
    for i, m in enumerate(matches, 1):
        dc = (m["item"]["date_created"] or "")[:10]
        sum_rows.append([str(i), dc, m["item"]["title"], str(m["match_count"])])
    sum_tbl = Table(sum_rows, colWidths=[1.2*cm, 2.6*cm, 11.5*cm, 2.0*cm])
    sum_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#003366")),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (-1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#FFFFFF"), HexColor("#F7F9FC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(sum_tbl)
    story.append(PageBreak())

    # Detalhamento por edição
    for i, m in enumerate(matches, 1):
        it = m["item"]
        dc = (it["date_created"] or "")[:10]
        story.append(Paragraph(f"{i}. {it['title']}", h2))
        ed_num = ""
        for sep in ["Edição", "Edicao"]:
            if sep in it["title"]:
                ed_num = it["title"].split(sep)[-1].strip()
                break
        # pdf_url OR content_url (the search script uses content_url in the envelope)
        raw_url = it.get("pdf_url") or it.get("content_url") or ""
        if raw_url and not raw_url.startswith("http"):
            raw_url = "https://portal.mppe.mp.br" + raw_url
        story.append(Paragraph(
            f"<b>Data:</b> {dc} &nbsp;|&nbsp; <b>Edição:</b> {ed_num} &nbsp;|&nbsp; "
            f"<b>Ocorrências:</b> {m['match_count']} &nbsp;|&nbsp; "
            f"<b>Mês/Ano:</b> {it.get('month', '')} / {it.get('year', '')}",
            meta
        ))
        if raw_url:
            link_html = f'<b>Link:</b> <link href="{raw_url}" color="#003366">{raw_url[:90]}...</link>'
            story.append(Paragraph(link_html, meta))
        story.append(Spacer(1, 3))

        seen = set()
        snip_idx = 0
        for h in m["hits"]:
            key = (h["offset"], h["matched"])
            if key in seen:
                continue
            seen.add(key)
            snip_idx += 1
            ctx = h["context"].replace("\n", " ").strip()
            matched_clean = h["matched"]
            ctx_html = ctx.replace(matched_clean, f"<b><font color='#003366'>{matched_clean}</font></b>")
            ctx_html = html_lib.escape(ctx_html)
            unesc_highlight = html_lib.escape(f"<b><font color='#003366'>{matched_clean}</font></b>")
            ctx_html = ctx_html.replace(unesc_highlight, f"<b><font color='#003366'>{matched_clean}</font></b>")
            ctx_html = ctx_html.replace("\n", "<br/>")
            story.append(Paragraph(f"<b>Ocorrência {snip_idx}:</b>", h3))
            story.append(Paragraph(ctx_html, quote))
        story.append(Spacer(1, 6))

    doc.build(story)
    print(f"PDF gerado: {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    mp = sys.argv[1]
    op = sys.argv[2] if len(sys.argv) > 2 else None
    main(mp, op)