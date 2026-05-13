output "dsql_cluster_id" {
  value = aws_dsql_cluster.main.identifier
}

output "dsql_cluster_endpoint" {
  value = "${aws_dsql_cluster.main.identifier}.dsql.${var.aws_region}.on.aws"
}

output "invoice_bucket_name" {
  value = aws_s3_bucket.invoices.id
}

output "aws_account_id" {
  value = data.aws_caller_identity.current.account_id
}
