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

variable "maintenance_marker_parameter_name" {
  type        = string
  description = "Name of an SSM Parameter Store parameter that, when set to a truthy value (true/1/active/on/yes), suppresses alerts. Useful for ad hoc maintenance."
  default     = ""
}

variable "patch_maintenance_window_ids" {
  type        = map(string)
  description = "Map of exact ECS cluster name to SSM Maintenance Window ID, e.g. from the terraform-aws-ssm-patch-manager module's maintenance_window_id output. Alerts for a cluster are suppressed while its mapped window has an execution in progress, reflecting real patch/reboot activity instead of a fixed clock schedule. Useful when one Lambda covers clusters from more than one environment/patch window."
  default     = {}
}
