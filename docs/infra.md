# Infrastructure

Everything provisioned in AWS for this project. Code lives in [infra/](../infra/).

## Prerequisites

- AWS account in `eu-central-1` (Frankfurt).
- Bootstrap IAM user `BrunnsteinBeverages` with `AdministratorAccess` attached.
- Access key + secret stored in `~/.aws/credentials` under profile `[brunnstein]`.
- Terraform >= 1.5 and AWS CLI installed locally.

The bootstrap user owns the access key Terraform itself uses, so it carries `lifecycle.prevent_destroy = true`. Don't `terraform destroy` it without thinking.

## What Terraform manages

| Resource | Purpose |
|---|---|
| `aws_dsql_cluster.main` | Aurora DSQL cluster, single-region, scale-to-zero. Operational system of record. |
| `aws_s3_bucket.invoices` | Holds incoming supplier invoice PDFs. Versioning on, SSE-S3 default, public access blocked. |
| `aws_budgets_budget.monthly` | $10/month cap with email alerts at 80% actual and 100% forecast. |
| `aws_iam_user.bootstrap` | The `BrunnsteinBeverages` admin user. Imported, not freshly created. |
| `aws_iam_user_policy_attachment.bootstrap_admin` | Attaches `AdministratorAccess`. |
| `aws_iam_service_linked_role.dsql` | `AWSServiceRoleForAuroraDsql`, needed by DSQL for tagging. |

Default tags `Project=brunnstein` and `ManagedBy=Terraform` are applied to everything.

## Operating

From `infra/`:

```
terraform init     # once per machine
terraform plan
terraform apply
```

Outputs include the DSQL endpoint, S3 bucket name, and account id. The load script reads `DSQL_CLUSTER_ID` and `AWS_REGION` from `.env`.

## Cost

Idle cost is essentially zero:

- DSQL: scales to zero compute when no queries.
- S3: free tier (5 GB, 20k GETs).
- Budgets: free.
- IAM: free.

The $10/month cap catches runaway loops (e.g. an agent in an extraction loop calling Bedrock thousands of times). The email alert fires before the cap is reached.

## Operational notes

- **First `apply` failure on a fresh account**: DSQL needs `AWSServiceRoleForAuroraDsql` before the cluster can be tagged. The role is now in Terraform state (imported), so this is a one-time issue. On a fresh account, the role auto-creates the first time any DSQL API is called, or via `aws iam create-service-linked-role --aws-service-name dsql.amazonaws.com`.
- **DSQL transaction limits**: ~3000 row modifications per transaction. The load script chunks inserts to stay under this.
- **DSQL doesn't enforce foreign keys**: DDL with FK constraints is rejected outright. The load script strips FK constraints from the SQLAlchemy metadata before `create_all`.
- **Bootstrap user can lock you out**: deleting the user or rotating its key without updating `~/.aws/credentials` breaks the next `terraform apply`. The `prevent_destroy` lifecycle blocks accidental deletion.

## State

Local state file at `infra/terraform.tfstate` (gitignored). Move to an S3 backend if more than one machine starts running `terraform apply`. Not needed for single-developer setup.
