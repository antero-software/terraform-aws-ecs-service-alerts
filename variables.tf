variable "app_name" {
  type        = string
  description = "Application name"
}

variable "environment" {
  type        = string
  description = "Environment name"
}

variable "aws_region" {
  type        = string
  description = "AWS region"
}

variable "account_name" {
  type        = string
  description = "Name of the AWS account to display in Slack alerts"
}

variable "slack_webhook_url" {
  type        = string
  description = "Slack webhook URL for alerting"
  sensitive   = true
}
