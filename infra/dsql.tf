resource "aws_dsql_cluster" "main" {
  deletion_protection_enabled = false

  tags = {
    Name = "${var.project_name}-main"
  }
}
