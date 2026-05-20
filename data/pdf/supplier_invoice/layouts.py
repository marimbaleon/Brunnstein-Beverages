"""Four visually distinct German invoice layouts.

Each layout function takes the rendering context and returns PDF bytes.
A supplier is deterministically assigned to one layout based on its
supplier_number hash, so the same supplier always issues invoices with
the same template.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from data.erp.models import PurchaseOrder, Supplier, SupplierInvoice, SupplierInvoiceLine
from data.pdf.supplier_invoice._formatters import (
    format_date,
    format_eur,
    format_iban,
    format_qty,
)

# Brunnstein Beverages is the recipient on every supplier invoice.
RECIPIENT = {
    "name": "Brunnstein Beverages GmbH",
    "street": "Brunnsteinstraße 12",
    "postal_code": "83646",
    "city": "Bad Tölz",
    "country": "Deutschland",
    "vat_id": "DE325871094",
}


@dataclass(frozen=True)
class Context:
    invoice: SupplierInvoice
    supplier: Supplier
    purchase_order: PurchaseOrder
    lines: list[SupplierInvoiceLine]


def assign_layout(supplier: Supplier) -> int:
    """Deterministic layout index 0-3 from the supplier_number."""
    return sum(ord(c) for c in supplier.supplier_number) % 4


def render(ctx: Context) -> bytes:
    """Render the invoice with the layout assigned to its supplier."""
    layouts = [layout_classic, layout_minimal, layout_traditional, layout_corporate]
    return layouts[assign_layout(ctx.supplier)](ctx)


# Shared helpers


def _line_rows(lines: list[SupplierInvoiceLine]) -> list[list[str]]:
    rows = [["Pos.", "Bezeichnung", "Menge", "Einzelpreis", "Gesamt netto"]]
    for line in lines:
        rows.append([
            str(line.line_number),
            line.description,
            format_qty(line.quantity),
            format_eur(line.unit_price_net_eur),
            format_eur(line.line_net_eur),
        ])
    return rows


def _totals_rows(invoice: SupplierInvoice) -> list[list[str]]:
    return [
        ["Zwischensumme netto", format_eur(invoice.total_net_eur)],
        ["USt. 19%", format_eur(invoice.total_vat_eur)],
        ["Gesamtsumme brutto", format_eur(invoice.total_gross_eur)],
    ]


# Layout A: Classic Mittelstand

def layout_classic(ctx: Context) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f"Rechnung {ctx.invoice.supplier_invoice_number}",
    )

    styles = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=11)
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    h1 = ParagraphStyle("h1", parent=bold, fontSize=16, spaceAfter=6)
    small = ParagraphStyle("small", parent=base, fontSize=7, leading=9)

    story = []

    sender = (
        f"<b>{ctx.supplier.name}</b><br/>"
        f"{ctx.supplier.street}<br/>"
        f"{ctx.supplier.postal_code} {ctx.supplier.city}<br/>"
        f"USt-IdNr: {ctx.supplier.vat_id}"
    )
    metadata = (
        f"<b>Rechnungs-Nr.:</b> {ctx.invoice.supplier_invoice_number}<br/>"
        f"<b>Rechnungsdatum:</b> {format_date(ctx.invoice.invoice_date)}<br/>"
        f"<b>Bestellung Nr.:</b> {ctx.purchase_order.po_number}<br/>"
        f"<b>Fälligkeit:</b> {format_date(ctx.invoice.due_date)}"
    )

    header = Table(
        [[Paragraph(sender, base), Paragraph(metadata, base)]],
        colWidths=[10 * cm, 7 * cm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(header)
    story.append(Spacer(1, 0.8 * cm))

    recipient = (
        f"{RECIPIENT['name']}<br/>"
        f"{RECIPIENT['street']}<br/>"
        f"{RECIPIENT['postal_code']} {RECIPIENT['city']}"
    )
    story.append(Paragraph(recipient, base))
    story.append(Spacer(1, 1 * cm))

    story.append(Paragraph("Rechnung", h1))
    story.append(Spacer(1, 0.4 * cm))

    items = Table(_line_rows(ctx.lines), colWidths=[1.2 * cm, 8.5 * cm, 2.3 * cm, 2.5 * cm, 2.5 * cm])
    items.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(items)
    story.append(Spacer(1, 0.5 * cm))

    totals = Table(_totals_rows(ctx.invoice), colWidths=[5 * cm, 3.5 * cm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.5, colors.black),
    ]))
    story.append(totals)
    story.append(Spacer(1, 1 * cm))

    payment = (
        f"<b>Bankverbindung:</b> {format_iban(ctx.invoice.payment_iban)} &nbsp; "
        f"BIC: {ctx.supplier.bic or '-'}<br/>"
        f"<b>Zahlungsziel:</b> {ctx.supplier.payment_terms_days} Tage netto"
    )
    story.append(Paragraph(payment, small))

    doc.build(story)
    return buf.getvalue()


# Layout B: Modern minimal

def layout_minimal(ctx: Context) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2.5 * cm, rightMargin=2.5 * cm,
        topMargin=2.5 * cm, bottomMargin=2.5 * cm,
        title=f"Rechnung {ctx.invoice.supplier_invoice_number}",
    )

    base = ParagraphStyle("base", fontName="Helvetica", fontSize=10, leading=13)
    light = ParagraphStyle("light", parent=base, textColor=colors.grey)
    huge = ParagraphStyle("huge", parent=base, fontName="Helvetica-Bold", fontSize=28, alignment=TA_LEFT, spaceAfter=12)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10, textColor=colors.grey)

    story = [Paragraph("RECHNUNG", huge)]

    meta = (
        f"Nr. {ctx.invoice.supplier_invoice_number} &nbsp;&nbsp; "
        f"{format_date(ctx.invoice.invoice_date)} &nbsp;&nbsp; "
        f"PO {ctx.purchase_order.po_number}"
    )
    story.append(Paragraph(meta, light))
    story.append(Spacer(1, 1.5 * cm))

    parties = Table(
        [[
            Paragraph(f"<b>Von</b><br/>{ctx.supplier.name}<br/>{ctx.supplier.street}<br/>"
                      f"{ctx.supplier.postal_code} {ctx.supplier.city}", base),
            Paragraph(f"<b>An</b><br/>{RECIPIENT['name']}<br/>{RECIPIENT['street']}<br/>"
                      f"{RECIPIENT['postal_code']} {RECIPIENT['city']}", base),
        ]],
        colWidths=[8 * cm, 8 * cm],
    )
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(parties)
    story.append(Spacer(1, 1.2 * cm))

    items = Table(_line_rows(ctx.lines), colWidths=[1.2 * cm, 8.5 * cm, 2.3 * cm, 2.5 * cm, 2.5 * cm])
    items.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(items)
    story.append(Spacer(1, 0.6 * cm))

    totals = Table(_totals_rows(ctx.invoice), colWidths=[5 * cm, 3.5 * cm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 2), (-1, 2), 12),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(totals)
    story.append(Spacer(1, 2 * cm))

    footer = (
        f"Zahlbar binnen {ctx.supplier.payment_terms_days} Tagen auf "
        f"{format_iban(ctx.invoice.payment_iban)}"
    )
    story.append(Paragraph(footer, small))

    doc.build(story)
    return buf.getvalue()


# Layout C: Bavarian traditional

def layout_traditional(ctx: Context) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=1.5 * cm, bottomMargin=2 * cm,
        title=f"Rechnung {ctx.invoice.supplier_invoice_number}",
    )

    base = ParagraphStyle("base", fontName="Times-Roman", fontSize=10, leading=13)
    italic = ParagraphStyle("italic", parent=base, fontName="Times-Italic", textColor=colors.HexColor("#5a4a2c"))
    h1 = ParagraphStyle("h1", parent=base, fontName="Times-Bold", fontSize=18, alignment=TA_CENTER, spaceAfter=4)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10)

    story = []

    banner = Table(
        [[
            Paragraph(f"<b>{ctx.supplier.name}</b>", h1),
        ], [
            Paragraph(f"Wirtschaftsbetrieb &middot; gegründet 1923", italic),
        ]],
        colWidths=[17 * cm],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f0dc")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(banner)
    story.append(Spacer(1, 0.6 * cm))

    parties = Table(
        [[
            Paragraph(f"{ctx.supplier.name}<br/>{ctx.supplier.street}<br/>"
                      f"{ctx.supplier.postal_code} {ctx.supplier.city}<br/>"
                      f"USt-IdNr: {ctx.supplier.vat_id}", base),
            Paragraph(f"<b>Rechnung Nr.:</b> {ctx.invoice.supplier_invoice_number}<br/>"
                      f"<b>Datum:</b> {format_date(ctx.invoice.invoice_date)}<br/>"
                      f"<b>Bestell-Nr.:</b> {ctx.purchase_order.po_number}<br/>"
                      f"<b>Zahlbar bis:</b> {format_date(ctx.invoice.due_date)}", base),
        ]],
        colWidths=[9 * cm, 8 * cm],
    )
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(parties)
    story.append(Spacer(1, 0.8 * cm))

    story.append(Paragraph(f"Rechnungsempfänger: {RECIPIENT['name']}, "
                           f"{RECIPIENT['street']}, "
                           f"{RECIPIENT['postal_code']} {RECIPIENT['city']}", base))
    story.append(Spacer(1, 0.5 * cm))

    items = Table(_line_rows(ctx.lines), colWidths=[1.2 * cm, 8.5 * cm, 2.3 * cm, 2.5 * cm, 2.5 * cm])
    items.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#5a4a2c")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#5a4a2c")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(items)
    story.append(Spacer(1, 0.5 * cm))

    totals = Table(_totals_rows(ctx.invoice), colWidths=[5 * cm, 3.5 * cm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
        ("FONTNAME", (0, 2), (-1, 2), "Times-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.75, colors.HexColor("#5a4a2c")),
    ]))
    story.append(totals)
    story.append(Spacer(1, 1 * cm))

    footer = (
        f"<b>Bankverbindung:</b> {format_iban(ctx.invoice.payment_iban)} "
        f"&nbsp; BIC: {ctx.supplier.bic or '-'}<br/>"
        f"<b>Zahlungsziel:</b> {ctx.supplier.payment_terms_days} Tage netto<br/>"
        f"<i>Wir bedanken uns für Ihren Auftrag und verbleiben mit den besten Grüßen.</i>"
    )
    story.append(Paragraph(footer, small))

    doc.build(story)
    return buf.getvalue()


# Layout D: Corporate AG

def layout_corporate(ctx: Context) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=1.5 * cm, bottomMargin=2.5 * cm,
        title=f"Rechnung {ctx.invoice.supplier_invoice_number}",
    )

    accent = colors.HexColor("#1f4a73")

    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9, leading=11)
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    h1 = ParagraphStyle("h1", parent=bold, fontSize=14, textColor=colors.white, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=base, fontSize=7, leading=9, textColor=colors.grey)
    right_meta = ParagraphStyle("right_meta", parent=base, alignment=TA_RIGHT)

    story = []

    bar = Table(
        [[Paragraph(f"&nbsp;&nbsp;{ctx.supplier.name}", h1),
          Paragraph("RECHNUNG", h1)]],
        colWidths=[12 * cm, 5 * cm],
    )
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), accent),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("RIGHTPADDING", (1, 0), (1, 0), 10),
    ]))
    story.append(bar)
    story.append(Spacer(1, 0.6 * cm))

    parties = Table(
        [[
            Paragraph(f"<b>Rechnungsempfänger</b><br/>{RECIPIENT['name']}<br/>"
                      f"{RECIPIENT['street']}<br/>"
                      f"{RECIPIENT['postal_code']} {RECIPIENT['city']}", base),
            Paragraph(f"<b>Rechnungs-Nr.:</b> {ctx.invoice.supplier_invoice_number}<br/>"
                      f"<b>Rechnungsdatum:</b> {format_date(ctx.invoice.invoice_date)}<br/>"
                      f"<b>Bestellnummer:</b> {ctx.purchase_order.po_number}<br/>"
                      f"<b>Zahlungsziel:</b> {format_date(ctx.invoice.due_date)}", right_meta),
        ]],
        colWidths=[9 * cm, 8 * cm],
    )
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(parties)
    story.append(Spacer(1, 0.8 * cm))

    items = Table(_line_rows(ctx.lines), colWidths=[1.2 * cm, 8.5 * cm, 2.3 * cm, 2.5 * cm, 2.5 * cm])
    items.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(items)
    story.append(Spacer(1, 0.5 * cm))

    totals = Table(_totals_rows(ctx.invoice), colWidths=[5 * cm, 3.5 * cm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 2), (-1, 2), 11),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#e6edf3")),
    ]))
    story.append(totals)
    story.append(Spacer(1, 1.2 * cm))

    footer = (
        f"<b>{ctx.supplier.name}</b> &nbsp;|&nbsp; "
        f"{ctx.supplier.street}, {ctx.supplier.postal_code} {ctx.supplier.city} &nbsp;|&nbsp; "
        f"USt-IdNr: {ctx.supplier.vat_id} &nbsp;|&nbsp; "
        f"IBAN: {format_iban(ctx.invoice.payment_iban)} &nbsp;|&nbsp; "
        f"BIC: {ctx.supplier.bic or '-'}<br/>"
        f"HRB 12345 Amtsgericht München &nbsp;|&nbsp; "
        f"Vorstand: Dr. M. Schneider, Dr. K. Berger &nbsp;|&nbsp; "
        f"Sitz: {ctx.supplier.city}"
    )
    story.append(Paragraph(footer, small))

    doc.build(story)
    return buf.getvalue()
