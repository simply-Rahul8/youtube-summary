# /// script
# requires-python = ">=3.10"
# dependencies = ["reportlab>=4"]
# ///
"""Render the summary Markdown to a clean A4 PDF.

Supports: # / ## / ### / #### headings, paragraphs, - * and 1. lists (nested by
indent), | tables |, > note boxes, **bold**, *italic*, `code`, [text](url),
and a `<!-- pagebreak -->` marker. The first `# ` heading becomes the cover title.

Usage: uv run md_to_pdf.py summary.md out.pdf
"""
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)

SRC, OUT = Path(sys.argv[1]), sys.argv[2]
MD = SRC.read_text(encoding="utf-8")

# Base-14 fonts only cover Latin-1; switch to a Unicode TTF when the text needs it.
# ponytail: one regular face for everything in that case (bold renders as regular)
FONT, BOLD = "Helvetica", "Helvetica-Bold"
if any(ord(c) > 0xFF and c not in "\u2013\u2014\u2018\u2019\u201c\u201d\u2022\u2026\u20ac"
       for c in MD):
    for p in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "C:/Windows/Fonts/arialuni.ttf"):
        if Path(p).exists():
            pdfmetrics.registerFont(TTFont("Uni", p))
            FONT = BOLD = "Uni"
            break

BLUE, GREY, LINE = colors.HexColor("#1a5fb4"), colors.HexColor("#f2f4f7"), colors.HexColor("#c9ced6")
ss = getSampleStyleSheet()
body = ParagraphStyle("b", parent=ss["Normal"], fontName=FONT, fontSize=9.8, leading=13.6, spaceAfter=5)
cell = ParagraphStyle("c", parent=body, fontSize=8.6, leading=11.2, spaceAfter=0)
cellh = ParagraphStyle("ch", parent=cell, fontName=BOLD)
H = {
    1: ParagraphStyle("h1", parent=body, fontName=BOLD, fontSize=16, leading=20, textColor=BLUE,
                      spaceBefore=10, spaceAfter=8),
    2: ParagraphStyle("h2", parent=body, fontName=BOLD, fontSize=12.4, leading=15.5,
                      textColor=colors.HexColor("#1f2933"), spaceBefore=10, spaceAfter=4),
    3: ParagraphStyle("h3", parent=body, fontName=BOLD, fontSize=10.6, leading=13.5, textColor=BLUE,
                      spaceBefore=6, spaceAfter=2),
    4: ParagraphStyle("h4", parent=body, fontName=BOLD, fontSize=9.8, leading=13, spaceBefore=4,
                      spaceAfter=1),
}
title_st = ParagraphStyle("t", parent=H[1], fontSize=22, leading=27, alignment=TA_CENTER,
                          spaceBefore=0, spaceAfter=10)
note = ParagraphStyle("n", parent=body, backColor=colors.HexColor("#fff7e0"),
                      borderColor=colors.HexColor("#e8c25a"), borderWidth=0.6, borderPadding=5,
                      spaceBefore=10, spaceAfter=11)


def inline(t):
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', t)
    t = re.sub(r"\*\*(.+?)\*\*", rf'<font name="{BOLD}">\1</font>', t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", t)
    t = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<i>\1</i>", t)
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="#1a5fb4">\1</link>', t)


def make_list(items):
    """items: [(indent, ordered, text)] -> nested ListFlowable."""
    base = items[0][0]
    flow, i = [], 0
    while i < len(items):
        ind, _, text = items[i]
        j = i + 1
        while j < len(items) and items[j][0] > base:
            j += 1
        parts = [Paragraph(inline(text), body)]
        if j > i + 1:
            parts.append(make_list(items[i + 1:j]))
        flow.append(ListItem(parts if len(parts) > 1 else parts[0], leftIndent=12))
        i = j
    ordered = items[0][1]
    return ListFlowable(flow, bulletType="1" if ordered else "bullet",
                        start=None if ordered else ("\u2022" if base == 0 else "-"),
                        leftIndent=14, bulletFontSize=8 if not ordered else 9, bulletFontName=FONT)


def make_table(rows):
    rows = [r for r in rows if not re.fullmatch(r"\|?[\s:\-|]+\|?", r)]
    data = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    n = max(len(r) for r in data)
    data = [r + [""] * (n - len(r)) for r in data]
    width = A4[0] - 36 * mm
    lens = [max(min(len(r[c]), 60) for r in data) + 4 for c in range(n)]
    widths = [width * x / sum(lens) for x in lens]
    t = Table([[Paragraph(inline(c), cellh if i == 0 else cell) for c in r]
               for i, r in enumerate(data)], colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, LINE), ("BACKGROUND", (0, 0), (-1, 0), GREY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    return t


story, para, lst, tbl, quote = [], [], [], [], []
doc_title = None
LIST_RE = re.compile(r"^(\s*)([-*]|\d+[.)])\s+(.*)$")


def flush():
    global para, lst, tbl, quote
    if para:
        story.append(Paragraph(inline(" ".join(para)), body))
    if lst:
        story.append(make_list(lst))
        story.append(Spacer(1, 3))
    if tbl:
        story.append(make_table(tbl))
        story.append(Spacer(1, 8))
    if quote:  # one line per bullet; plain lines inside a quote stay one paragraph
        lines, prev_plain = [], False
        for q in quote:
            b = re.match(r"^([-*]|\d+[.)])\s+(.*)$", q)
            if b:
                mark = "•" if b.group(1) in "-*" else b.group(1)
                lines.append(f"{mark} {inline(b.group(2))}")
            elif prev_plain:
                lines[-1] += " " + inline(q)
            else:
                lines.append(inline(q))
            prev_plain = not b
        story.append(Paragraph("<br/>".join(lines), note))
    para, lst, tbl, quote = [], [], [], []


for raw in MD.splitlines():
    line = raw.rstrip()
    s = line.strip()
    m = LIST_RE.match(line)
    if s == "<!-- pagebreak -->":
        flush()
        story.append(PageBreak())
    elif not s:
        if not lst:  # blank lines inside a list keep the list going
            flush()
    elif s.startswith("#"):
        flush()
        level = min(len(s) - len(s.lstrip("#")), 4)
        text = s.lstrip("#").strip()
        if level == 1 and doc_title is None:
            doc_title = text
            story += [Spacer(1, 6 * mm), Paragraph(inline(text), title_st)]
        else:
            story.append(Paragraph(inline(text), H[level]))
    elif s.startswith("|"):
        if not tbl:
            flush()
        tbl.append(s)
    elif s.startswith(">"):
        if not quote:
            flush()
        q = s[1:].strip()
        if q:  # a bare ">" spacer line adds nothing
            quote.append(q)
    elif m:
        if not lst:
            flush()
        lst.append((len(m.group(1).expandtabs(4)) // 2, m.group(2)[0].isdigit(), m.group(3)))
    elif lst and line.startswith(" "):
        lst[-1] = (lst[-1][0], lst[-1][1], lst[-1][2] + " " + s)  # wrapped list line
    elif s in ("---", "***"):
        flush()
        story.append(Spacer(1, 6))
    else:
        if lst or tbl or quote:
            flush()
        para.append(s)
flush()

footer_text = (doc_title or SRC.stem)[:90]


def footer(c, d):
    c.saveState()
    c.setFont(FONT, 7.5)
    c.setFillColor(colors.HexColor("#7b8794"))
    c.drawString(18 * mm, 10 * mm, footer_text)
    c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {d.page}")
    c.restoreState()


SimpleDocTemplate(OUT, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                  bottomMargin=18 * mm, title=doc_title or SRC.stem
                  ).build(story, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
