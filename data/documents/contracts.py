"""Framework agreements as PDF, plus a JSONL index for retrieval.

Supplier framework agreements (Rahmenliefervertrag) for every supplier and
supply agreements for a sample of B2B customers. Each PDF carries the clause
structure a real agreement has — term, prices and rebates, payment, delivery,
quality/SLA, liability, termination — with values that vary per party, so a RAG
or clause-extraction use case has something real to read. ``index.jsonl`` holds
one metadata record per contract pointing at its PDF.

Files land under ``data/documents/contracts/`` with ``index.jsonl`` alongside.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from reportlab.platypus import Paragraph, Spacer

from data.documents._pdf import build, styles
from data.erp.models import Customer, Supplier

_ROOT = Path(__file__).resolve().parent / "contracts"

_SUPPLIER_SUBJECT = (
    "Gegenstand dieses Rahmenliefervertrags ist die wiederkehrende Lieferung von "
    "Roh-, Hilfs- und Verpackungsstoffen durch den Lieferanten an die Brunnstein "
    "Beverages GmbH nach Maßgabe einzelner Abrufbestellungen."
)
_CUSTOMER_SUBJECT = (
    "Gegenstand dieser Liefervereinbarung ist die Belieferung des Kunden mit "
    "Getränkeprodukten der Brunnstein Beverages GmbH zu den nachstehend "
    "vereinbarten Konditionen."
)


def _clauses(
    rng: random.Random,
    *,
    is_supplier: bool,
    terms: int,
    notice_months: int,
    rebate_pct: int,
    price_lock_months: int,
) -> list[tuple[str, str]]:
    party = "Lieferant" if is_supplier else "Kunde"
    grantor = "der Lieferant" if is_supplier else "Brunnstein"
    return [
        ("§ 1 Vertragsgegenstand", _SUPPLIER_SUBJECT if is_supplier else _CUSTOMER_SUBJECT),
        (
            "§ 2 Laufzeit und Verlängerung",
            f"Der Vertrag tritt mit Unterzeichnung in Kraft und läuft auf unbestimmte "
            f"Zeit. Er kann mit einer Frist von {notice_months} Monaten zum Quartalsende "
            f"schriftlich gekündigt werden. Das Recht zur außerordentlichen Kündigung aus "
            f"wichtigem Grund bleibt unberührt.",
        ),
        (
            "§ 3 Preise und Konditionen",
            f"Die Preise ergeben sich aus der jeweils gültigen Anlage 1. Sie sind für "
            f"{price_lock_months} Monate ab Vertragsbeginn fest vereinbart. Ab einem "
            f"Jahresvolumen gemäß Anlage 1 gewährt {grantor} "
            f"einen Jahresbonus von {rebate_pct}% auf den Nettoumsatz.",
        ),
        (
            "§ 4 Zahlungsbedingungen",
            f"Rechnungen sind innerhalb von {terms} Tagen ab Rechnungsdatum ohne Abzug "
            f"zur Zahlung fällig. Bei Zahlung innerhalb von 14 Tagen wird ein Skonto von "
            f"2% gewährt.",
        ),
        (
            "§ 5 Lieferung und Gefahrübergang",
            "Die Lieferung erfolgt DAP (Incoterms 2020) an den jeweils benannten "
            "Bestimmungsort. Teillieferungen sind zulässig, sowet zumutbar.",
        ),
        (
            "§ 6 Qualität und Gewährleistung",
            f"Der {party} sichert die Einhaltung der einschlägigen lebensmittelrechtlichen "
            f"Vorschriften sowie der vereinbarten Spezifikationen zu. Beanstandungen sind "
            f"innerhalb von 7 Werktagen nach Wareneingang anzuzeigen. Die Liefertreue soll "
            f"{rng.randint(95, 99)}% nicht unterschreiten.",
        ),
        (
            "§ 7 Haftung",
            "Die Haftung für leichte Fahrlässigkeit ist auf den vertragstypischen, "
            "vorhersehbaren Schaden begrenzt, soweit nicht Leben, Körper oder Gesundheit "
            "betroffen sind.",
        ),
        (
            "§ 8 Schlussbestimmungen",
            "Änderungen bedürfen der Schriftform. Es gilt das Recht der Bundesrepublik "
            "Deutschland. Gerichtsstand ist, soweit zulässig, der Sitz von Brunnstein "
            "Beverages.",
        ),
    ]


def _make_pdf(
    path: Path,
    header: str,
    party_name: str,
    party_addr: str,
    signed: date,
    clauses: list[tuple[str, str]],
) -> None:
    s = styles()
    story = [
        Paragraph(header, s["title"]),
        Paragraph(
            f"zwischen Brunnstein Beverages GmbH, Quellenstraße 1, 83646 Bad Tölz "
            f"(nachfolgend „Brunnstein“) und {party_name}, {party_addr}.",
            s["subtitle"],
        ),
    ]
    for heading, text in clauses:
        story.append(Paragraph(heading, s["heading"]))
        story.append(Paragraph(text, s["body"]))
    story.append(Spacer(1, 24))
    story.append(Paragraph(f"Bad Tölz, den {signed:%d.%m.%Y}", s["body"]))
    story.append(
        Paragraph(
            "_________________________&nbsp;&nbsp;&nbsp;&nbsp;_________________________", s["body"]
        )
    )
    story.append(Paragraph(f"Brunnstein Beverages GmbH&nbsp;&nbsp;&nbsp;{party_name}", s["small"]))
    build(path, story, header)


def write_contracts(
    suppliers: list[Supplier],
    customers: list[Customer],
    n_customers: int = 30,
    today: date = date(2026, 1, 15),
    seed: int = 42,
    out_dir: Path = _ROOT,
) -> list[Path]:
    """Write supplier and customer framework agreements plus the index."""
    rng = random.Random(seed + 21)
    out_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    written: list[Path] = []

    cust_sample = sorted(customers, key=lambda c: c.customer_number)[:n_customers]

    def emit(doc_type: str, party_type: str, number: str, name: str, addr: str, terms: int) -> None:
        notice = rng.choice([3, 6, 12])
        rebate = rng.choice([1, 2, 2, 3, 5])
        price_lock = rng.choice([6, 12, 12, 24])
        signed = today - timedelta(days=rng.randint(120, 365 * 4))
        cid = f"CT-{len(index) + 1:05d}"
        path = out_dir / doc_type / f"{cid}_{number}.pdf"
        header = "Rahmenliefervertrag" if party_type == "supplier" else "Liefervereinbarung"
        clauses = _clauses(
            rng,
            is_supplier=party_type == "supplier",
            terms=terms,
            notice_months=notice,
            rebate_pct=rebate,
            price_lock_months=price_lock,
        )
        _make_pdf(path, header, name, addr, signed, clauses)
        index.append(
            {
                "contract_id": cid,
                "doc_type": doc_type,
                "party_type": party_type,
                "party_number": number,
                "party_name": name,
                "signed_date": signed.isoformat(),
                "valid_from": signed.isoformat(),
                "payment_terms_days": terms,
                "notice_period_months": notice,
                "annual_rebate_pct": rebate,
                "price_lock_months": price_lock,
                "auto_renew": True,
                "pdf_path": str(path.relative_to(out_dir.parent)),
            }
        )
        written.append(path)

    for sup in sorted(suppliers, key=lambda s: s.supplier_number):
        addr = f"{sup.street}, {sup.postal_code} {sup.city}"
        emit(
            "supplier_framework",
            "supplier",
            sup.supplier_number,
            sup.name,
            addr,
            sup.payment_terms_days,
        )

    for cust in cust_sample:
        addr = f"{cust.street}, {cust.postal_code} {cust.city}"
        emit(
            "customer_supply",
            "customer",
            cust.customer_number,
            cust.name,
            addr,
            cust.payment_terms_days,
        )

    (out_dir / "index.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in index) + "\n",
        encoding="utf-8",
    )
    return written
