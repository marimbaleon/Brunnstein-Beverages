# Architecture

## Architecture Principles
- keep costs as low as possible since this is a private project
- use of scale-to-zero cloud resources for data storage (AWS)
- local development with focus on being fast. No environments.   

## Components

**AWS Aurora DSQL**: Central database for the project. Mimics data sources as base for Agentic AI Use Cases. Serverless, Postgres-compatible, scale-to-zero. Chosen over RDS (always-on cost), Aurora Serverless v2 (15s cold start).

**AWS S3** for all incoming data from fictional source systems, eg. documents, IoT data, CRM, ERP, and more.

**Amazon Bedrock with Claude Haiku 4.5**. Single IAM and billing surface with the rest of AWS. Cheap compared to Anthropic's Sonnet or Opus models (roughly $0.01 per invoice extraction). The provider is wrapped in a thin `LlmClient` so swapping to direct Anthropic API or another model is a one-line change.

**LangGraph** for agents. Explicit nodes and edges so each step is reviewable and testable.

**FastAPI** exposes the agents. Pydantic models shared between API, agent state, and DB layer.

**Streamlit** for the demo UI: one page per use case, drag-and-drop upload, human-in-the-loop confirmation.

**MLflow** for LLM and agent observability. Self-hosted in a single container with SQLite as the backend. `mlflow.langchain.autolog()` traces every LangGraph node automatically: inputs, outputs, latency, token counts. The `mlflow.evaluate()` API covers the eval suite.

**Terraform** provisions AWS resources: DSQL, S3, IAM, budget alerts.

## Local-first development

Code runs on a laptop and talks to real AWS services using personal credentials. Aurora DSQL, S3, and Bedrock are all called directly: no MinIO, no LocalStack, no AWS emulation. There is no dev/prod behavior gap because there is only one set of resources.

Application services (FastAPI, Streamlit, MLflow) run in Docker via `docker compose up`.

A live deployment is provisioned with Terraform only when needed (typically before a scheduled demo) and torn down afterwards. Idle cost is essentially zero. The same AWS resources are used for local dev and for the live demo: this is a single-user project and a separate "dev environment" would be ceremony with no payoff.

Trade-off: AWS credentials are required even for local development, and a runaway loop could generate real cost. An AWS budget alert provisioned in Terraform catches this.

## Deliberately out of scope for v1

- Analytical platform (eg. Databricks, Snowflake). Not needed at start, since DSQL mimics data sources and Agents run locally in Docker container.
- Email ingress (SES, SQS). "Invoice arrived" is simulated with a file picker.
- Vector database. Not needed for use case 1.
- Authentication. Single-user demo.

## Use case 1 flow

```
PDF in S3
   │
   ▼
LangGraph agent
   ├── extract   (Bedrock vision)
   ├── validate  (DSQL: customer, order, line items)
   └── pause for human review
   │
   ▼
Streamlit UI: user confirms or edits
   │
   ▼
Invoice persisted to DSQL
```

Every step is traced in MLflow.
