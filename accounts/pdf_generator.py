"""
PDF Report Generator for LeadActivity.
Uses ReportLab to generate professional PDF reports.
"""

import io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT


# ── Color Palette (Material-ish) ────────────────────────────────────────────
C_PRIMARY   = colors.HexColor("#1a73e8")
C_DARK      = colors.HexColor("#202124")
C_MUTED     = colors.HexColor("#5f6368")
C_BORDER    = colors.HexColor("#dadce0")
C_SURFACE   = colors.HexColor("#f8f9fa")
C_WHITE     = colors.white
C_SUCCESS   = colors.HexColor("#137333")
C_WARNING   = colors.HexColor("#b06000")
C_ERROR     = colors.HexColor("#d93025")
C_SUCCESS_BG = colors.HexColor("#e6f4ea")
C_WARNING_BG = colors.HexColor("#fef7e0")
C_ERROR_BG   = colors.HexColor("#fce8e6")

SCORE_COLOR = {
    "Active":            (C_SUCCESS, C_SUCCESS_BG),
    "Moderately Active": (C_WARNING, C_WARNING_BG),
    "Inactive":          (C_ERROR,   C_ERROR_BG),
}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=C_WHITE,
            leading=28,
            alignment=TA_LEFT,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName="Helvetica",
            fontSize=11,
            textColor=colors.HexColor("#bdc1c6"),
            leading=16,
        ),
        "section": ParagraphStyle(
            "section",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=C_PRIMARY,
            spaceAfter=6,
            spaceBefore=14,
            borderPadding=(0, 0, 4, 0),
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Helvetica",
            fontSize=10,
            textColor=C_DARK,
            leading=15,
        ),
        "muted": ParagraphStyle(
            "muted",
            fontName="Helvetica",
            fontSize=9,
            textColor=C_MUTED,
            leading=14,
        ),
        "label": ParagraphStyle(
            "label",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=C_MUTED,
            leading=12,
        ),
        "value": ParagraphStyle(
            "value",
            fontName="Helvetica",
            fontSize=10,
            textColor=C_DARK,
            leading=14,
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName="Helvetica",
            fontSize=8,
            textColor=C_MUTED,
            alignment=TA_CENTER,
        ),
    }


def generate_lead_pdf(lead) -> bytes:
    """
    Generate a PDF report for a LeadActivity instance.
    Returns bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20*mm,
        rightMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm,
        title=f"Lead Report — {lead.name or 'Unknown'}",
    )

    W = A4[0] - 40*mm  # usable width
    s = _styles()
    story = []

    # ── Header Banner ──────────────────────────────────────
    score_fg, score_bg = SCORE_COLOR.get(lead.activity_score, (C_MUTED, C_SURFACE))

    header_data = [[
        Paragraph(f"{lead.name or 'Unknown Lead'}", s["title"]),
        Paragraph(
            f'<font color="#ffffff" size="10"><b>{lead.activity_score}</b></font>',
            ParagraphStyle("sc", fontName="Helvetica-Bold", fontSize=10,
                           textColor=C_WHITE, alignment=TA_RIGHT),
        ),
    ]]
    header_table = Table(header_data, colWidths=[W * 0.75, W * 0.25])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_PRIMARY),
        ("ROWBACKGROUNDS", (1, 0), (1, 0), [score_bg]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING",   (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 14),
        ("ROUNDEDCORNERS", [8]),
    ]))
    story.append(header_table)

    # Headline + Location under banner
    if lead.headline or lead.location:
        sub_text = " · ".join(filter(None, [lead.headline, lead.location]))
        story.append(Spacer(1, 6))
        story.append(Paragraph(sub_text, s["muted"]))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width=W, thickness=1, color=C_BORDER))
    story.append(Spacer(1, 10))

    # ── Profile URL ────────────────────────────────────────
    story.append(Paragraph("Profile URL", s["label"]))
    story.append(Paragraph(
        f'<link href="{lead.profile_url}" color="#1a73e8">{lead.profile_url}</link>',
        s["value"]
    ))
    story.append(Spacer(1, 12))

    # ── Activity Stats ─────────────────────────────────────
    story.append(Paragraph("Activity Overview (Last 30 Days)", s["section"]))

    stat_data = [
        ["Metric", "Count"],
        ["Posts",    str(lead.posts_count)],
        ["Comments", str(lead.comments_count)],
        ["Reposts",  str(lead.reposts_count)],
        ["Total",    str(lead.posts_count + lead.comments_count + lead.reposts_count)],
    ]
    stat_table = Table(stat_data, colWidths=[W * 0.6, W * 0.4])
    stat_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), C_PRIMARY),
        ("TEXTCOLOR",    (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 10),
        ("BACKGROUND",   (0, 1), (-1, -2), C_SURFACE),
        ("BACKGROUND",   (0, -1), (-1, -1), C_BORDER),
        ("FONTNAME",     (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR",    (0, 1), (-1, -1), C_DARK),
        ("GRID",         (0, 0), (-1, -1), 0.5, C_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [C_WHITE, C_SURFACE]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
        ("ALIGN",        (1, 0), (1, -1), "CENTER"),
        ("ROUNDEDCORNERS", [4]),
    ]))
    story.append(stat_table)
    story.append(Spacer(1, 8))

    # Last Activity + Score row
    score_fg, score_bg = SCORE_COLOR.get(lead.activity_score, (C_MUTED, C_SURFACE))
    badge_data = [[
        Paragraph(f"Last Activity: {lead.last_activity_date or '—'}", s["body"]),
        Paragraph(
            f'<b>{lead.activity_score}</b>',
            ParagraphStyle("bs", fontName="Helvetica-Bold", fontSize=10,
                           textColor=score_fg, alignment=TA_CENTER),
        ),
    ]]
    badge_table = Table(badge_data, colWidths=[W * 0.65, W * 0.35])
    badge_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (0, 0), C_SURFACE),
        ("BACKGROUND",   (1, 0), (1, 0), score_bg),
        ("BOX",          (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",    (0, 0), (-1, -1), 0.5, C_BORDER),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(badge_table)
    story.append(Spacer(1, 14))

    # ── Gemini Lead Qualification Summary ─────────────────
    if lead.summary:
        story.append(HRFlowable(width=W, thickness=1, color=C_BORDER))
        story.append(Paragraph("AI Lead Qualification Summary", s["section"]))
        summary_box = Table(
            [[Paragraph(lead.summary, s["body"])]],
            colWidths=[W],
        )
        summary_box.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#e8f0fe")),
            ("BOX",          (0, 0), (-1, -1), 0.5, C_PRIMARY),
            ("LEFTPADDING",  (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING",   (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
            ("ROUNDEDCORNERS", [6]),
        ]))
        story.append(summary_box)
        story.append(Spacer(1, 14))

    # ── Search Context ─────────────────────────────────────
    if lead.search_url:
        story.append(HRFlowable(width=W, thickness=1, color=C_BORDER))
        story.append(Paragraph("Search Context", s["section"]))
        story.append(Paragraph(
            f'Search URL: <link href="{lead.search_url}" color="#1a73e8">{lead.search_url[:80]}...</link>',
            s["muted"]
        ))
        story.append(Spacer(1, 8))

    # ── Footer ─────────────────────────────────────────────
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 6))
    generated_at = lead.created_at.strftime("%B %d, %Y at %H:%M") if lead.created_at else datetime.now().strftime("%B %d, %Y at %H:%M")
    story.append(Paragraph(
        f"Generated by LinkedIn Lead Activity Analyzer · {generated_at}",
        s["footer"],
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()
