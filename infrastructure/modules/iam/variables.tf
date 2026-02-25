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
