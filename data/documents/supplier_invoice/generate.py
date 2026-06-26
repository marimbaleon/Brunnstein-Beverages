"""Generate supplier invoice PDFs from rows in DSQL.

    uv run python -m data.documents.supplier_invoice.generate              # 50 PDFs to local_pdfs/
    uv run python -m data.documents.supplier_invoice.generate --count 100  # more
    uv run python -m data.documents.supplier_invoice.generate --s3         # upload to S3 instead

The default writes locally to local_pdfs/ (gitignored) so you can eyeball the
output. Use --s3 to push to the invoice bucket once the layouts look right.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import boto3
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from data.documents.supplier_invoice.layouts import Context, assign_layout, render
from data.erp.load_to_dsql import get_engine
from data.erp.models import PurchaseOrder, SupplierInvoice, SupplierInvoiceLine

load_dotenv()

_DEFAULT_LOCAL_DIR = "local_pdfs"


def _fetch_invoices(session: Session, count: int) -> list[SupplierInvoice]:
    stmt = (
        select(SupplierInvoice)
        .options(
            selectinload(SupplierInvoice.supplier),
            selectinload(SupplierInvoice.purchase_order).selectinload(PurchaseOrder.lines),
            selectinload(SupplierInvoice.lines).selectinload(
                SupplierInvoiceLine.purchase_order_line
            ),
        )
        .order_by(SupplierInvoice.invoice_date.desc())
        .limit(count)
    )
    return list(session.execute(stmt).unique().scalars().all())


def _s3_client():
    profile = os.environ.get("AWS_PROFILE")
    region = os.environ.get("AWS_REGION", "eu-central-1")
    return boto3.Session(profile_name=profile, region_name=region).client("s3")


def main(count: int = 50, local_dir: str | None = _DEFAULT_LOCAL_DIR, to_s3: bool = False) -> dict:
    engine = get_engine()
    with Session(engine) as session:
        invoices = _fetch_invoices(session, count)

        layout_counts: dict[int, int] = {}
        s3 = None
        bucket = None
        if to_s3:
            bucket = os.environ.get("S3_INVOICES_BUCKET")
            if not bucket:
                raise RuntimeError(
                    "S3_INVOICES_BUCKET is not set in the environment; "
                    "either export it or drop --s3 to write locally."
                )
            s3 = _s3_client()
        else:
            Path(local_dir).mkdir(parents=True, exist_ok=True)

        for inv in invoices:
            ctx = Context(
                invoice=inv,
                supplier=inv.supplier,
                purchase_order=inv.purchase_order,
                lines=sorted(inv.lines, key=lambda line: line.line_number),
            )
            pdf_bytes = render(ctx)
            layout_idx = assign_layout(inv.supplier)
            layout_counts[layout_idx] = layout_counts.get(layout_idx, 0) + 1

            if s3 is not None:
                s3.put_object(
                    Bucket=bucket,
                    Key=inv.source_s3_key,
                    Body=pdf_bytes,
                    ContentType="application/pdf",
                )
            else:
                target = Path(local_dir) / inv.source_s3_key
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(pdf_bytes)

        return {
            "rendered": len(invoices),
            "by_layout": layout_counts,
            "destination": f"s3://{bucket}/" if s3 else local_dir,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--s3", action="store_true",
                        help="upload to S3 instead of writing locally")
    parser.add_argument("--local-dir", type=str, default=_DEFAULT_LOCAL_DIR,
                        help=f"local output directory (default: {_DEFAULT_LOCAL_DIR})")
    args = parser.parse_args()

    result = main(count=args.count, local_dir=args.local_dir, to_s3=args.s3)
    print(f"rendered {result['rendered']} invoices to {result['destination']}")
    print("layout distribution:")
    layout_names = {0: "classic", 1: "minimal", 2: "traditional", 3: "corporate"}
    for idx, name in layout_names.items():
        print(f"  {name}: {result['by_layout'].get(idx, 0)}")
