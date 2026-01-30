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

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for ECS tasks"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security group IDs for ECS tasks"
  type        = list(string)
}

# =============================================================================
# MCP Server Variables
# =============================================================================

variable "mcp_server_cpu" {
  description = "CPU units for MCP server task"
  type        = string
}

variable "mcp_server_memory" {
  description = "Memory for MCP server task"
  type        = string
}

variable "mcp_server_desired_count" {
  description = "Desired number of MCP server tasks"
  type        = number
}

variable "mcp_server_container_image" {
  description = "Docker image for MCP server"
  type        = string
}

variable "mcp_server_container_port" {
  description = "Port exposed by the MCP server container"
  type        = number
  default     = 8000
}

variable "mcp_server_log_level" {
  description = "Log level for MCP server"
  type        = string
}

variable "mcp_server_workers" {
  description = "Number of workers for MCP server"
  type        = string
}

variable "mcp_server_execution_role_arn" {
  description = "ARN of the task execution role for MCP Server"
  type        = string
}

variable "mcp_server_task_role_arn" {
  description = "ARN of the task role for MCP Server"
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
  default     = "/tmp/fire_archive"
}

# =============================================================================
# Agent Server Variables
# =============================================================================

variable "agent_server_enabled" {
  description = "Whether to deploy the Agent Server"
  type        = bool
  default     = true
}

variable "agent_server_container_image" {
  description = "Docker image for Agent Server"
  type        = string
  default     = ""
}

variable "agent_server_container_port" {
  description = "Port exposed by the Agent Server container"
  type        = number
  default     = 8080
}

variable "agent_server_task_cpu" {
  description = "CPU units for Agent Server task"
  type        = string
  default     = "512"
}

variable "agent_server_task_memory" {
  description = "Memory for Agent Server task"
  type        = string
  default     = "1024"
}

variable "agent_server_desired_count" {
  description = "Desired number of Agent Server tasks"
  type        = number
  default     = 1
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
