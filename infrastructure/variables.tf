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
  default     = "eo-agent"
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
  default     = "10.1.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones for subnets"
  type        = list(string)
  default     = ["eu-west-3a", "eu-west-3b", "eu-west-3c"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.1.1.0/24", "10.1.2.0/24", "10.1.3.0/24"]
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
  default     = "637423200916.dkr.ecr.eu-west-3.amazonaws.com/eo-agent-mcp:latest"
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

# Streamlit Configuration
variable "streamlit_cpu" {
  description = "CPU units for Streamlit task"
  type        = string
  default     = "512"
}

variable "streamlit_memory" {
  description = "Memory for Streamlit task"
  type        = string
  default     = "1024"
}

variable "streamlit_desired_count" {
  description = "Desired number of Streamlit tasks"
  type        = number
  default     = 1
}

variable "maptiler_api_key_arn" {
  description = "ARN for Maptiler API key secret"
  type        = string
  default     = ""
}

# Service Discovery
variable "service_discovery_namespace" {
  description = "Service discovery namespace"
  type        = string
  default     = "eo-agent.local"
}
