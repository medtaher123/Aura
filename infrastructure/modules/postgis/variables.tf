variable "enabled" {
  description = "Whether to provision managed PostGIS-compatible RDS resources"
  type        = bool
  default     = false
}

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

variable "subnet_ids" {
  description = "Subnet IDs for DB subnet group"
  type        = list(string)
}

variable "allowed_security_group_ids" {
  description = "Security groups allowed to connect to PostGIS"
  type        = list(string)
  default     = []
}

variable "instance_class" {
  description = "RDS instance class baseline for full-France workload"
  type        = string
  default     = "db.r6g.xlarge"
}

variable "allocated_storage" {
  description = "Initial allocated storage (GB)"
  type        = number
  default     = 512
}

variable "max_allocated_storage" {
  description = "Maximum autoscaled storage (GB)"
  type        = number
  default     = 2048
}

variable "multi_az" {
  description = "Whether to enable Multi-AZ for HA"
  type        = bool
  default     = false
}

variable "backup_retention_period" {
  description = "Backup retention period in days"
  type        = number
  default     = 15
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "bdtopo"
}

variable "master_username" {
  description = "Master username"
  type        = string
  default     = "bdtopo_admin"
}

variable "deletion_protection" {
  description = "Protect DB from deletion"
  type        = bool
  default     = true
}

