variable "name_prefix" {
  type        = string
  description = "Prefix used for all resource names"
}

variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "ap-southeast-2"
}

variable "slack_webhook_url_prod" {
  type        = string
  description = "Slack webhook URL for production alerts"
  sensitive   = true
}

variable "slack_webhook_url_lower" {
  type        = string
  description = "Slack webhook URL for lower environment alerts"
  sensitive   = true
}
