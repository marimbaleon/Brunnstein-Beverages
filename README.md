# Brunnstein Beverages

A fictional mid-sized German beverage manufacturer used as a demo company to showcase Data & AI use cases. The company is a located in southern germany and makes mineral water, soft drinks, and craft beverages, sold B2B (retail chains, gastronomy) and B2C (webshop). 

## Use case 1: multi-agent invoice intake

A PDF invoice arrives. A set of agents extract the line items, validate them against the database (customer exists, order references match, amounts add up, IBAN is plausible), and give recommendations for a human reviewer. On confirmation the invoice is persisted.

## Stack

- Python 3.12, uv, ruff, pytest
- Docker for local services (FastAPI, Streamlit, MLflow)
- LangGraph
- Terraform on AWS
- Aurora DSQL (serverless SQL DB)
- S3
- Amazon Bedrock with Claude Haiku 4.5

See [docs/architecture.md](docs/architecture.md) for more details.

## Repository layout

```
.
├── data/              data model, generators, fixtures
├── platform/
│   ├── api/           FastAPI service
│   ├── agents/        LangGraph graphs and nodes
│   └── ui/            Streamlit app
├── infra/             Terraform
├── notebooks/         exploration and prototyping
└── docs/              architecture and design notes
```

## Running locally

All data is synthetic and regenerates deterministically from a single seed.

1. `uv run python -m data.data_generator` loads synthetic ERP rows into DSQL (suppliers, POs, goods receipts, supplier invoices).
2. `uv run python -m data.pdf.supplier_invoice.generate` renders PDFs for invoices already in the DB to `local_pdfs/`.
3. `uv run python -m data.pdf.supplier_invoice.test_cases` renders fresh invoice PDFs for the agent to process, into `test_invoices/`.

Historical PDFs from step 2 mirror rows already in the DB. Test PDFs from step 3 reference real suppliers and POs but are not yet in the DB. They are the "incoming mail" the agent validates. The tests cases include valid and corrupted pdfs.

## License

MIT. See [LICENSE](LICENSE).
