resource "aws_iam_user" "bootstrap" {
  name = "BrunnsteinBeverages"

  lifecycle {
    # The user owns the access key Terraform itself authenticates with.
    # Destroying it would lock the account out of Terraform-managed changes.
    prevent_destroy = true
  }
}

resource "aws_iam_user_policy_attachment" "bootstrap_admin" {
  user       = aws_iam_user.bootstrap.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_service_linked_role" "dsql" {
  aws_service_name = "dsql.amazonaws.com"

  lifecycle {
    prevent_destroy = true
  }
}
