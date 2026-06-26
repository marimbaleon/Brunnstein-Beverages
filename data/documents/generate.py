"""Write Brunnstein's unstructured documents (no database involved).

Regenerates the master spine and transactional flow deterministically (same
seed as the loaders), then serialises the unstructured artefacts the GenAI use
cases read:

    data/documents/contracts/<type>/<id>_<party>.pdf  (+ index.jsonl)
    data/documents/complaints/<id>.json               (+ complaints.ndjson)
    data/documents/dunning/<invoice>_<level>.eml / .html
    data/documents/spec_sheets/<sku>.pdf
    data/documents/images/labels|signage/*.png        (+ prompts.jsonl)

Run as a script:
    uv run python -m data.documents.generate
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data.documents.complaints import write_complaints
from data.documents.contracts import write_contracts
from data.documents.dunning import write_dunning
from data.documents.images import write_images
from data.documents.spec_sheets import write_spec_sheets
from data.erp.generators.customers import generate_customers
from data.erp.generators.plants import generate_plants
from data.erp.generators.production import generate_production
from data.erp.generators.products import generate_products
from data.erp.generators.raw_materials import generate_raw_materials
from data.erp.generators.sales import generate_sales
from data.erp.generators.suppliers import generate_suppliers
from data.webshop.orders import generate_online_orders, generate_webshop_customers

_DOCS_ROOT = Path(__file__).resolve().parent


def main(
    seed: int = 42,
    year_range: tuple[int, int] = (2023, 2025),
) -> dict[str, Any]:
    materials = generate_raw_materials(seed=seed)
    suppliers = generate_suppliers(seed=seed)
    plants, lines = generate_plants()
    products, components = generate_products(materials)
    customers = generate_customers(seed=seed)

    sales_orders, _, customer_invoices, _ = generate_sales(
        customers, products, plants, year_range=year_range, seed=seed
    )
    webshop_customers = generate_webshop_customers(year_range=year_range, seed=seed)
    online_orders = generate_online_orders(
        webshop_customers, products, year_range=year_range, seed=seed
    )
    production_runs, _ = generate_production(
        products, lines, sales_orders, online_orders, year_range=year_range, seed=seed
    )

    contracts = write_contracts(suppliers, customers, seed=seed)
    complaints = write_complaints(
        production_runs, products, webshop_customers, customers, seed=seed
    )
    dunning = write_dunning(customer_invoices, seed=seed)
    spec_sheets = write_spec_sheets(products, components, materials, seed=seed)
    images = write_images(
        products,
        plants,
        complaints_ndjson=_DOCS_ROOT / "complaints" / "complaints.ndjson",
        seed=seed,
    )

    return {
        "contract_pdfs": len(contracts),
        "complaint_json": len(complaints),
        "dunning_files": len(dunning),
        "spec_sheet_pdfs": len(spec_sheets),
        "image_png": images["rendered_png"],
        "image_prompt_entries": images["prompt_manifest_entries"],
    }


if __name__ == "__main__":
    counts = main()
    for k, v in counts.items():
        print(f"  {k}: {v}")
