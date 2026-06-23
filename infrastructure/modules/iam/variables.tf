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

variable "execution_role_name" {
  description = "Name of the ECS task execution role. Override per-stack to avoid account-global IAM name collisions when running multiple stacks in the same account."
  type        = string
  default     = "ecsTaskExecutionRole"
}

variable "opentopo_api_key_arn" {
  description = "ARN for OpenTopo API key secret"
  type        = string
}

variable "map_key_arn" {
  description = "ARN for Map key secret"
  type        = string
}

variable "maptiler_api_key_arn" {
  description = "ARN for Maptiler API key secret"
  type        = string
}

variable "bdtopo_database_url_secret_arn" {
  description = "Optional ARN containing BDTOPO_DATABASE_URL"
  type        = string
  default     = ""
}


variable "cognito_client_secret_arn" {
  description = "Optional ARN containing the Streamlit Cognito app client secret"
  type        = string
  default     = ""
}

variable "bdtopo_pipeline_enabled" {
  description = "Whether to create BDTOPO pipeline IAM resources"
  type        = bool
  default     = false
}
