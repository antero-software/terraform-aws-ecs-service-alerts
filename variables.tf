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

variable "patch_maintenance_window_id" {
  type        = string
  description = "ID of an SSM Maintenance Window to treat as a live suppression signal, e.g. the maintenance_window_id output of the terraform-aws-ssm-patch-manager module. Alerts are suppressed while that window has an execution in progress, reflecting real patch/reboot activity instead of a fixed clock schedule."
  default     = ""
}
