# Brunnstein Beverages

A fictional mid-sized German beverage manufacturer used as a demo company for Data & AI use cases. The company is based in southern Germany, makes mineral water, soft drinks and craft beverages, and sells B2B (retail chains, gastronomy) and B2C (webshop).

**Repo is under active development.**

## Use case 1: supplier invoice intake (AP automation)

A supplier sends a PDF invoice. A LangGraph agent extracts the fields with a vision LLM, validates them against the ERP, runs a three-way match (purchase order + goods receipt + invoice), and produces a verdict.

Pipeline:

```
PDF -> extract (Claude Haiku 4.5)
    -> validate (DSQL lookups, IBAN check, 3-way match)
    -> decide  -> approve  -> persist to DSQL
                -> flag    -> Streamlit review (human-in-the-loop)
                -> hold    -> wait for goods receipt
```

The agent emits explicit signal codes (`iban_mismatch_full`, `iban_mismatch_typo`, `po_not_found`, `supplier_unknown`, `quantity_mismatch_vs_goods_receipt`, `unit_price_drift`, `no_matching_goods_receipt`, ...). The decision step routes on those signals.

### Eval

Eight adversarial test invoices live in `use_cases/automated_invoice_processing/test_invoices/`, each with `meta.json` declaring the expected outcome. The eval suite runs the agent over all of them:

```
uv run python -m use_cases.automated_invoice_processing.agent.evaluate
```

Current pass rate: **7/8**. The remaining failure is the same supplier layout consistently dropping the last IBAN digit during extraction. The agent catches it as `iban_missing` rather than producing a false positive — honest failure mode, documented in the demo notebook.

## Stack

- Python 3.12, uv, ruff, pytest
- LangGraph + langchain-aws (Bedrock Converse, Claude Haiku 4.5)
- SQLAlchemy 2.0, Pydantic 2
- Aurora DSQL (serverless Postgres-compatible)
- S3 for invoice PDFs
- Terraform on AWS
- Streamlit for the human review UI
- MLflow (local file backend) for per-run tracing

See [docs/architecture.md](docs/architecture.md) for the decisions, [docs/data_model.md](docs/data_model.md) for the schema, and [docs/infra.md](docs/infra.md) for the AWS setup.

## Repository layout

```
.
├── data/                                data model, ERP generators, PDF generators
│   ├── erp/                             schema, load to DSQL, ERD generator, per-entity generators
│   ├── pdf/supplier_invoice/            4 invoice layouts + adversarial test case generator
│   └── notebooks/                       data generator + DSQL exploration
├── use_cases/
│   └── automated_invoice_processing/
│       ├── agent/                       extract, validate, decide, persist nodes + LangGraph
│       ├── notebooks/demo.ipynb         end-to-end walkthrough + full eval
│       ├── test_invoices/               8 committed test fixtures with meta.json
│       └── ui.py                        Streamlit human review surface
├── infra/                               Terraform: DSQL, S3, IAM, budgets
├── tests/                               unit tests on pure validation + decision logic
└── docs/                                architecture, data model, infra
```

## Running locally

All data is synthetic and regenerates deterministically from a single seed.

```bash
# 1. Provision AWS resources (one-time)
cd infra && terraform apply

# 2. Load synthetic ERP rows into DSQL
uv run python -m data.data_generator

# 3. Render the 8 adversarial test invoice PDFs
uv run python -m use_cases.automated_invoice_processing.eval.test_case_generation

# 4. Run the agent on one PDF
uv run python -m use_cases.automated_invoice_processing.agent.run \
    use_cases/automated_invoice_processing/test_invoices/02_iban_fraud/tc-002-fraud.pdf

# 5. Full eval over all 8 scenarios
uv run python -m use_cases.automated_invoice_processing.agent.evaluate

# 6. Human-in-the-loop review UI
uv run streamlit run use_cases/automated_invoice_processing/ui.py

# 7. Demo notebook
open use_cases/automated_invoice_processing/notebooks/demo.ipynb
```

Optional: `uv run mlflow ui` (after some runs) to inspect per-run params, latencies and decisions.

## Roadmap

- Multi-national suppliers (Italian, Czech, Polish, ...) with multi-language extraction and reverse-charge VAT
- Sales-side data: customers, sales orders, customer invoices (groundwork for an AR use case)
- ECS / Fargate deployment + GitHub Actions CI
- Use case 2: RAG over signed supplier contracts
- Use case 3: IoT anomaly detection on production data

## License

MIT. See [LICENSE](LICENSE).
