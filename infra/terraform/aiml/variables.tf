# Variables — set via .tfvars (not committed) or env (TF_VAR_*)

variable "environment" {
  type        = string
  default     = "dev"
  description = "Environment name (dev, staging, prod)."
}

variable "project" {
  type        = string
  default     = "terraform01"
  description = "Project identifier."
}
