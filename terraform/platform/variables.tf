variable "aws_region" {
  type    = string
  default = "us-east-2"
}

variable "bucket_prefix" {
  type    = string
  default = "pulse-events"
}

variable "events_prefix" {
  type    = string
  default = "events/"

  validation {
    condition     = endswith(var.events_prefix, "/") && !startswith(var.events_prefix, "/")
    error_message = "events_prefix must end with a slash and not start with one."
  }
}

variable "snowflake_organization" {
  type    = string
  default = null
}

variable "snowflake_account" {
  type    = string
  default = null
}

variable "snowflake_user" {
  type    = string
  default = null
}

variable "snowflake_private_key_path" {
  type    = string
  default = null
}

variable "terraform_role" {
  type    = string
  default = "PULSE_TERRAFORM"
}

variable "database" {
  type    = string
  default = "PULSE"

  validation {
    condition     = can(regex("^[A-Z][A-Z0-9_]*$", var.database))
    error_message = "database must be an upper case identifier."
  }
}

variable "deployer_public_key" {
  type = string
}

variable "ops_public_key" {
  type = string
}

variable "ops_allowed_ips" {
  type    = list(string)
  default = []

  validation {
    condition     = alltrue([for ip in var.ops_allowed_ips : can(cidrhost(ip, 0))])
    error_message = "ops_allowed_ips must be cidr blocks like 203.0.113.7/32."
  }
}

variable "warehouse_size" {
  type    = string
  default = "XSMALL"

  validation {
    condition     = contains(["XSMALL", "SMALL", "MEDIUM", "LARGE"], var.warehouse_size)
    error_message = "warehouse_size must be XSMALL, SMALL, MEDIUM or LARGE."
  }
}

variable "auto_suspend_seconds" {
  type    = number
  default = 60

  validation {
    condition     = var.auto_suspend_seconds >= 60 && var.auto_suspend_seconds <= 600
    error_message = "auto_suspend_seconds must be between 60 and 600."
  }
}

variable "daily_credit_quota" {
  type = map(number)
  default = {
    LOAD  = 2
    BUILD = 5
    QUERY = 5
  }

  validation {
    condition     = alltrue([for key, quota in var.daily_credit_quota : quota > 0])
    error_message = "every daily credit quota must be positive."
  }
}

variable "raw_retention_days" {
  type    = number
  default = 1

  validation {
    condition     = var.raw_retention_days >= 0 && var.raw_retention_days <= 90
    error_message = "raw_retention_days must be between 0 and 90."
  }
}

variable "event_file_expiry_days" {
  type    = number
  default = 30

  validation {
    condition     = var.event_file_expiry_days >= 1
    error_message = "event_file_expiry_days must be at least 1."
  }
}
