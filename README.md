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


## License

MIT. See [LICENSE](LICENSE).
