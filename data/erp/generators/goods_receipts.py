"""Generate goods receipts for purchase orders.

Closed POs get full receipts. Partial POs get partial coverage.
Open and cancelled POs get nothing.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from data.erp.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    GoodsReceiptStatus,
    PurchaseOrder,
    PurchaseOrderStatus,
)


def _receipt_dates(po: PurchaseOrder, rng: random.Random) -> list[date]:
    """Closed POs may arrive in 1-2 shipments, partial POs in 1 (incomplete) shipment."""
    if po.status == PurchaseOrderStatus.closed:
        n = rng.choices([1, 2], weights=[80, 20], k=1)[0]
    else:
        n = 1
    dates = []
    base = po.order_date
    for i in range(n):
        # First receipt 3-21 days after order, second 7-30 days after first
        if i == 0:
            offset = rng.randint(3, 21)
        else:
            offset = (dates[-1] - base).days + rng.randint(7, 30)
        dates.append(base + timedelta(days=offset))
    return dates


def generate_goods_receipts(
    purchase_orders: list[PurchaseOrder],
    seed: int = 42,
) -> list[GoodsReceipt]:
    rng = random.Random(seed)

    receipts: list[GoodsReceipt] = []
    gr_counter = 0

    for po in purchase_orders:
        if po.status in (PurchaseOrderStatus.open, PurchaseOrderStatus.cancelled):
            continue

        dates = _receipt_dates(po, rng)
        n_receipts = len(dates)
        # Split each PO line's total quantity across receipts.
        for r_idx, received_date in enumerate(dates):
            gr_counter += 1
            year = received_date.year
            gr = GoodsReceipt(
                id=uuid4(),
                gr_number=f"GR-{year}-{gr_counter:06d}",
                purchase_order_id=po.id,
                received_date=received_date,
                status=GoodsReceiptStatus.matched if po.status == PurchaseOrderStatus.closed
                else GoodsReceiptStatus.pending_invoice,
                notes=None,
            )
            gr.purchase_order = po

            for line_idx, po_line in enumerate(po.lines, start=1):
                # For closed POs split full quantity across receipts. For partial, deliver
                # only part of one line.
                if po.status == PurchaseOrderStatus.closed:
                    if n_receipts == 1:
                        received_qty = po_line.quantity
                    else:
                        # First receipt gets 40-70%, second the rest
                        if r_idx == 0:
                            frac = Decimal(rng.randint(40, 70)) / Decimal(100)
                            received_qty = (po_line.quantity * frac).quantize(Decimal("0.001"))
                        else:
                            already = sum(
                                (rl.quantity_received for r in receipts if r.purchase_order_id == po.id
                                 for rl in r.lines if rl.purchase_order_line_id == po_line.id),
                                Decimal("0"),
                            )
                            received_qty = po_line.quantity - already
                else:
                    # Partial PO: skip some lines, partial quantity on others
                    if rng.random() < 0.4:
                        continue
                    frac = Decimal(rng.randint(50, 90)) / Decimal(100)
                    received_qty = (po_line.quantity * frac).quantize(Decimal("0.001"))

                if received_qty <= 0:
                    continue
                gr_line = GoodsReceiptLine(
                    id=uuid4(),
                    goods_receipt_id=gr.id,
                    line_number=line_idx,
                    purchase_order_line_id=po_line.id,
                    quantity_received=received_qty,
                )
                gr_line.purchase_order_line = po_line
                gr.lines.append(gr_line)

            if gr.lines:
                receipts.append(gr)

    return receipts
