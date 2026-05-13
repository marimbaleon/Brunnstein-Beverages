variable "project_name" {
  type    = string
  default = "brunnstein"
}

variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "aws_profile" {
  type    = string
  default = "brunnstein"
}

variable "budget_amount_usd" {
  type        = number
  default     = 30
  description = "Monthly cost cap in USD. Forecast over this triggers an alert."
}

variable "alert_email" {
  type        = string
  description = "Email to receive budget alerts."
}
