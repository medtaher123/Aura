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

# GitHub Configuration
variable "github_repository" {
  description = "GitHub repository in format owner/repo for OIDC authentication"
  type        = string
  default     = "ines-besrour/MetaplanetLLM" # Update this with your actual repository
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

# =============================================================================
# MCP Server Configuration
# =============================================================================

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

variable "mcp_server_container_port" {
  description = "Port exposed by the MCP server container"
  type        = number
  default     = 8000
}

variable "mcp_server_log_level" {
  description = "Log level for MCP server"
  type        = string
  default     = "info"
}

variable "mcp_server_workers" {
  description = "Number of workers for MCP server"
  type        = string
  default     = "1"
}

# Secrets ARNs
variable "opentopo_api_key_arn" {
  description = "ARN for OpenTopo API key secret"
  type        = string
  default     = "arn:aws:secretsmanager:eu-west-3:637423200916:secret:mpllm/api-keys/OPENTOPO_API_KEY-z1pBzv"
}

variable "map_key_arn" {
  description = "ARN for Map key secret"
  type        = string
  default     = "arn:aws:secretsmanager:eu-west-3:637423200916:secret:mpllm/api-keys/MAP_KEY-GUFKLE"
}

# GeoServer Configuration
variable "geoserver_base_url" {
  description = "GeoServer base URL"
  type        = string
  default     = "http://geoserver-alb-556624184.eu-west-3.elb.amazonaws.com/geoserver"
}

variable "geoserver_risk_layer" {
  description = "GeoServer risk layer name"
  type        = string
  default     = "georisk:predictions"
}

variable "fire_archive_dir" {
  description = "Directory for fire detection archives"
  type        = string
  default     = "s3://metaplanet-fire-archive-firms/"
}

# =============================================================================
# Agent Server Configuration
# =============================================================================

variable "agent_server_enabled" {
  description = "Whether to deploy the Agent Server"
  type        = bool
  default     = true
}

variable "agent_server_cpu" {
  description = "CPU units for Agent Server task"
  type        = string
  default     = "512"
}

variable "agent_server_memory" {
  description = "Memory for Agent Server task"
  type        = string
  default     = "1024"
}

variable "agent_server_desired_count" {
  description = "Desired number of Agent Server tasks"
  type        = number
  default     = 1
}

variable "agent_server_container_port" {
  description = "Port exposed by the Agent Server container"
  type        = number
  default     = 8080
}

variable "agent_server_log_level" {
  description = "Log level for Agent Server"
  type        = string
  default     = "info"
}

variable "agent_server_workers" {
  description = "Number of workers for Agent Server"
  type        = string
  default     = "1"
}

variable "agent_server_mcp_server_url" {
  description = "MCP Server URL for Agent Server to connect to"
  type        = string
  default     = "http://localhost:8000"
}

variable "agent_server_bedrock_model_id" {
  description = "AWS Bedrock model ID for LLM"
  type        = string
  default     = "anthropic.claude-3-5-sonnet-20241022-v2:0"
}

variable "agent_server_bedrock_max_tokens" {
  description = "Max tokens for Bedrock LLM responses"
  type        = string
  default     = "4096"
}
