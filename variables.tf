variable "name_prefix" {
  type        = string
  description = "Prefix used for all resource names"
}

variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "ap-southeast-2"
}

variable "slack_webhook_url" {
  type        = string
  description = "Slack webhook URL for alerting"
  sensitive   = true
}
