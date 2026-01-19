variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "eu-west-3"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "project_name" {
  description = "Project name prefix"
  type        = string
  default     = "mpllm"
}

variable "aws_account_id" {
  description = "AWS Account ID"
  type        = string
  default     = "637423200916"
}

# VPC Configuration
variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones for subnets"
  type        = list(string)
  default     = ["eu-west-3a", "eu-west-3b", "eu-west-3c"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

# ECS Configuration
variable "mcp_server_cpu" {
  description = "CPU units for MCP server task"
  type        = string
  default     = "256"
}

variable "mcp_server_memory" {
  description = "Memory for MCP server task"
  type        = string
  default     = "512"
}

variable "mcp_server_desired_count" {
  description = "Desired number of MCP server tasks"
  type        = number
  default     = 1
}

variable "mcp_server_image" {
  description = "Docker image for MCP server"
  type        = string
  default     = "637423200916.dkr.ecr.eu-west-3.amazonaws.com/mpllm-mcp:latest"
}

variable "mcp_log_level" {
  description = "Log level for MCP server"
  type        = string
  default     = "info"
}

variable "mcp_workers" {
  description = "Number of workers for MCP server"
  type        = string
  default     = "1"
}

# Secrets ARNs
variable "opentopo_api_key_arn" {
  description = "ARN for OpenTopo API key secret"
  type        = string
  default     = "arn:aws:secretsmanager:eu-west-3:637423200916:secret:mpllm/OPENTOPO_API_KEY-tQBR3M"
}

variable "map_key_arn" {
  description = "ARN for Map key secret"
  type        = string
  default     = "arn:aws:secretsmanager:eu-west-3:637423200916:secret:mpllm/MAP_KEY-r2EH0R"
}
