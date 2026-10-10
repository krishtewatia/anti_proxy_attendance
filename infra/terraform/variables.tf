# ------------------------------------------------------------------------------
# The one setting that decides how the instance runs
# ------------------------------------------------------------------------------

variable "run_mode" {
  description = <<-EOT
    "on_demand": the instance is started and stopped by hand (make start / make
    stop) and is also stopped automatically every night, so a forgotten
    instance does not use up credits.
    "always_on": no automatic stop; the instance runs until it is stopped by hand.
  EOT
  type        = string
  default     = "on_demand"

  validation {
    condition     = contains(["on_demand", "always_on"], var.run_mode)
    error_message = "run_mode must be \"on_demand\" or \"always_on\"."
  }
}

variable "instance_state" {
  description = "Set by make start / make stop (written to state.auto.tfvars). Not meant to be edited by hand."
  type        = string
  default     = "running"

  validation {
    condition     = contains(["running", "stopped"], var.instance_state)
    error_message = "instance_state must be \"running\" or \"stopped\"."
  }
}

variable "auto_stop_schedule" {
  description = "When the nightly automatic stop happens in on_demand mode (EventBridge Scheduler cron, in auto_stop_timezone)."
  type        = string
  default     = "cron(30 23 * * ? *)"
}

variable "auto_stop_timezone" {
  type    = string
  default = "Asia/Kolkata"
}

# ------------------------------------------------------------------------------
# Naming and placement
# ------------------------------------------------------------------------------

variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "project" {
  type    = string
  default = "antiproxy"
}

variable "environment" {
  type    = string
  default = "prod"
}

# ------------------------------------------------------------------------------
# The instance
# ------------------------------------------------------------------------------

variable "instance_type" {
  description = "Free plan accounts may use t3.micro, t3.small, t4g.micro, t4g.small, c7i-flex.large and m7i-flex.large. The images are x86-64."
  type        = string
  default     = "t3.small"

  validation {
    condition     = contains(["t3.small", "c7i-flex.large", "m7i-flex.large"], var.instance_type)
    error_message = "Use t3.small, c7i-flex.large or m7i-flex.large (x86-64 types available on the Free plan with enough memory)."
  }
}

variable "root_volume_gb" {
  description = "Encrypted gp3 volume holding the system, the images and the uploaded photos."
  type        = number
  default     = 20
}

variable "swap_mb" {
  type    = number
  default = 2048
}

# ------------------------------------------------------------------------------
# The application
# ------------------------------------------------------------------------------

variable "site_host" {
  description = "Public host name of the site (a DuckDNS name: <subdomain>.duckdns.org)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]+\\.duckdns\\.org$", var.site_host))
    error_message = "site_host must look like <subdomain>.duckdns.org."
  }
}

variable "release_sha" {
  description = "Commit whose images are started on first boot (the image tag). make up passes the current origin/main."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.release_sha))
    error_message = "release_sha must be a full 40-character commit id."
  }
}

variable "github_repository" {
  description = "owner/name of the repository the Compose file is fetched from and deployments come from."
  type        = string
  default     = "krishtewatia/anti_proxy_attendance"
}

variable "image_prefix" {
  description = "Registry path the three images share: <image_prefix>-backend, -frontend, -vision."
  type        = string
  default     = "ghcr.io/krishtewatia/anti-proxy"
}

variable "liveness_mode" {
  type    = string
  default = "observe"
}

variable "acme_ca" {
  description = "Certificate authority Caddy uses. Use the staging directory for trial runs: https://acme-staging-v02.api.letsencrypt.org/directory"
  type        = string
  default     = "https://acme-v02.api.letsencrypt.org/directory"
}

# ------------------------------------------------------------------------------
# MongoDB Atlas
# ------------------------------------------------------------------------------

variable "atlas_org_id" {
  description = "Atlas organization the project is created in (Organization Settings in the Atlas console)."
  type        = string
}

variable "atlas_project_name" {
  type    = string
  default = "anti-proxy-attendance"
}

variable "atlas_cluster_name" {
  type    = string
  default = "antiproxy"
}

variable "atlas_allowed_ip" {
  description = "Public address of the instance, allowed to reach the cluster. Passed by infra/scripts/tf.py after the instance has an address; empty means no address is allowed."
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Alerts and backups
# ------------------------------------------------------------------------------

variable "alert_email" {
  description = "Where the budget alerts are sent."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be an email address."
  }
}

variable "credit_budget_usd" {
  description = "Credits available to the account, in dollars."
  type        = number
  default     = 95
}

variable "credit_alert_thresholds_usd" {
  description = "Email when this much of the credits has been used (usage before credits are applied)."
  type        = list(number)
  default     = [25, 50, 75]
}

variable "backup_retention_days" {
  description = "Backups older than this are deleted from the bucket."
  type        = number
  default     = 14
}
