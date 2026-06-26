"""Write Brunnstein's Bronze landing files (no database involved).

Regenerates the master spine and sales flow deterministically from the same
seed the DSQL loader uses, then serialises the raw, source-shaped files the
file-based systems would drop into the lake:

    data/export/bronze/retail_sellthrough/<partner>/sellthrough_<year>.csv
    data/export/bronze/bank_statements/mt940/<month>_<iban>.sta
    data/export/bronze/bank_statements/camt053/<month>_<iban>.xml
    data/export/bronze/iot_telemetry/line=<line_code>/<year>-<month>.parquet
    data/export/bronze/machine_logs/<line_code>/<date>.log
    data/export/bronze/hr_time_tracking/<year>-<month>.csv

Run as a script:
    uv run python -m data.export.lake
"""

from __future__ import annotations

from typing import Any

from data.banking.statements import write_bank_statements
from data.erp.generators.customers import generate_customers
from data.erp.generators.plants import generate_plants
from data.erp.generators.production import generate_production
from data.erp.generators.products import generate_products
from data.erp.generators.raw_materials import generate_raw_materials
from data.erp.generators.sales import generate_sales
from data.hr.load import generate_hr
from data.hr.time_tracking import write_hr_time_tracking
from data.retail.sellthrough import write_retail_sellthrough
from data.shopfloor.machine_logs import write_machine_logs
from data.shopfloor.telemetry import write_iot_telemetry
from data.webshop.events import write_webshop_events
from data.webshop.orders import generate_online_orders, generate_webshop_customers
from data.webshop.reviews import write_reviews


def main(
    seed: int = 42,
    year_range: tuple[int, int] = (2023, 2025),
) -> dict[str, Any]:
    materials = generate_raw_materials(seed=seed)
    plants, lines = generate_plants()
    products, _ = generate_products(materials)
    customers = generate_customers(seed=seed)
    sales_orders, _, _, payments = generate_sales(
        customers, products, plants, year_range=year_range, seed=seed
    )

    webshop_customers = generate_webshop_customers(year_range=year_range, seed=seed)
    online_orders = generate_online_orders(
        webshop_customers, products, year_range=year_range, seed=seed
    )
    production_runs, maintenance_orders = generate_production(
        products, lines, sales_orders, online_orders, year_range=year_range, seed=seed
    )
    hr = generate_hr(plants, lines, year_range=year_range, seed=seed)

    sellthrough = write_retail_sellthrough(products, customers, year_range=year_range, seed=seed)
    statements = write_bank_statements(payments, customers)
    events = write_webshop_events(webshop_customers, products, year_range=year_range, seed=seed)
    reviews = write_reviews(webshop_customers, products, year_range=year_range, seed=seed)
    telemetry = write_iot_telemetry(production_runs, lines, maintenance_orders, seed=seed)
    logs = write_machine_logs(production_runs, lines, maintenance_orders, seed=seed)
    punches = write_hr_time_tracking(
        hr["employees"], hr["absences"], plants, year_range=year_range, seed=seed
    )

    return {
        "retail_sellthrough_files": len(sellthrough),
        "bank_statement_files": len(statements),
        "webshop_event_files": len(events),
        "review_files": len(reviews),
        "iot_telemetry_files": len(telemetry),
        "machine_log_files": len(logs),
        "hr_time_tracking_files": len(punches),
    }


if __name__ == "__main__":
    counts = main()
    for k, v in counts.items():
        print(f"  {k}: {v}")
