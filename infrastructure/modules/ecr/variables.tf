variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "aws_account_id" {
  description = "AWS Account ID"
  type        = string
}

variable "github_repository" {
  description = "GitHub repository in format owner/repo for OIDC authentication"
  type        = string
}

variable "create_github_oidc" {
  description = "Whether to create the account-global GitHub OIDC provider and CI role/policy. Set to false for secondary stacks in the same AWS account, since the OIDC provider is account-global (only one allowed) and the CI role/policy names are not project-scoped."
  type        = bool
  default     = true
}
