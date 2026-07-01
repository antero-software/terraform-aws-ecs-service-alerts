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

variable "maintenance_window_enabled" {
  type        = bool
  description = "Enable a recurring maintenance window during which alerts are suppressed (events are still logged to CloudWatch)"
  default     = false
}

variable "maintenance_window_start" {
  type        = string
  description = "Start time of the maintenance window in HH:MM format (UTC). Example: '01:00'"
  default     = "01:00"

  validation {
    condition     = can(regex("^([01]\\d|2[0-3]):[0-5]\\d$", var.maintenance_window_start))
    error_message = "maintenance_window_start must be in HH:MM format (24-hour UTC), e.g. '02:00'."
  }
}

variable "maintenance_window_end" {
  type        = string
  description = "End time of the maintenance window in HH:MM format (UTC). Supports overnight windows (e.g. start=23:00, end=01:00)"
  default     = "05:00"

  validation {
    condition     = can(regex("^([01]\\d|2[0-3]):[0-5]\\d$", var.maintenance_window_end))
    error_message = "maintenance_window_end must be in HH:MM format (24-hour UTC), e.g. '04:00'."
  }
}
