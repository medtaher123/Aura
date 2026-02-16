variable "project_name" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "namespace" {
  description = "Service discovery namespace"
  type        = string
  default     = "eo-agent.local"
}
