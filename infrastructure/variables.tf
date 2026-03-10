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
  default     = "963275461308"
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

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets"
  type        = list(string)
  default     = ["10.1.4.0/24", "10.1.5.0/24", "10.1.6.0/24"]
}

# ECS Configuration
variable "mcp_server_cpu" {
  description = "CPU units for MCP server task"
  type        = string
  default     = "4096"
}

variable "mcp_server_memory" {
  description = "Memory for MCP server task"
  type        = string
  default     = "8192"
}

variable "mcp_server_desired_count" {
  description = "Desired number of MCP server tasks"
  type        = number
  default     = 1
}

variable "mcp_server_image" {
  description = "Docker image for MCP server"
  type        = string
  default     = "963275461308.dkr.ecr.eu-west-3.amazonaws.com/eo-agent-mcp-server:latest"
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
  default     = "arn:aws:secretsmanager:eu-west-3:963275461308:secret:mpllm/api-keys/OPENTOPO_API_KEY-z1pBzv"
}

variable "map_key_arn" {
  description = "ARN for Map key secret"
  type        = string
  default     = "arn:aws:secretsmanager:eu-west-3:963275461308:secret:mpllm/api-keys/MAP_KEY-GUFKLE"
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
  default     = "4096"
}

variable "streamlit_memory" {
  description = "Memory for Streamlit task"
  type        = string
  default     = "8192"
}

variable "streamlit_desired_count" {
  description = "Desired number of Streamlit tasks"
  type        = number
  default     = 2
}

variable "maptiler_api_key_arn" {
  description = "ARN for Maptiler API key secret"
  type        = string
  default     = ""
}

variable "bdtopo_database_url_secret_arn" {
  description = "Secrets Manager ARN containing BDTOPO_DATABASE_URL connection string"
  type        = string
  default     = ""
}

# Agent Server Configuration
variable "agent_server_enabled" {
  description = "Whether to create agent server resources"
  type        = bool
  default     = true
}

variable "agent_server_cpu" {
  description = "CPU units for Agent server task"
  type        = string
  default     = "4096"
}

variable "agent_server_memory" {
  description = "Memory for Agent server task"
  type        = string
  default     = "8192"
}

variable "agent_server_desired_count" {
  description = "Desired number of Agent server tasks"
  type        = number
  default     = 1
}

variable "agent_server_log_level" {
  description = "Log level for Agent server"
  type        = string
  default     = "info"
}

variable "agent_server_workers" {
  description = "Number of workers for Agent server"
  type        = string
  default     = "1"
}

variable "agent_server_bedrock_model_id" {
  description = "Bedrock model ID for Agent server"
  type        = string
  default     = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "agent_server_bedrock_max_tokens" {
  description = "Bedrock max tokens for Agent server"
  type        = string
  default     = "4096"
}

# Service Discovery
variable "service_discovery_namespace" {
  description = "Service discovery namespace"
  type        = string
  default     = "eo-agent.local"
}

# Managed PostGIS baseline (for BDTOPO full-France)
variable "postgis_enabled" {
  description = "Whether to provision a managed PostGIS-compatible RDS instance"
  type        = bool
  default     = true
}

variable "postgis_instance_class" {
  description = "PostGIS RDS instance class baseline"
  type        = string
  default     = "db.r7g.xlarge"
}

variable "postgis_allocated_storage" {
  description = "PostGIS allocated storage in GB"
  type        = number
  default     = 500
}

variable "postgis_max_allocated_storage" {
  description = "PostGIS max autoscaled storage in GB"
  type        = number
  default     = 2000
}

variable "postgis_multi_az" {
  description = "Enable Multi-AZ for PostGIS"
  type        = bool
  default     = false
}

variable "postgis_backup_retention_period" {
  description = "Backup retention period for PostGIS"
  type        = number
  default     = 7
}

variable "postgis_db_name" {
  description = "PostGIS database name"
  type        = string
  default     = "bdtopo"
}

variable "postgis_master_username" {
  description = "PostGIS admin username"
  type        = string
  default     = "bdtopo_admin"
}

variable "postgis_deletion_protection" {
  description = "PostGIS deletion protection"
  type        = bool
  default     = true
}

# BDTOPO Pipeline (ECS Fargate batch task + EventBridge schedule)
variable "bdtopo_pipeline_enabled" {
  description = "Whether to create BDTOPO pipeline task definition and EventBridge schedule"
  type        = bool
  default     = false
}

variable "bdtopo_pipeline_cpu" {
  description = "CPU units for BDTOPO pipeline task"
  type        = string
  default     = "4096"
}

variable "bdtopo_pipeline_memory" {
  description = "Memory (MiB) for BDTOPO pipeline task"
  type        = string
  default     = "16384"
}

variable "bdtopo_pipeline_ephemeral_storage_gib" {
  description = "Ephemeral storage (GiB) for BDTOPO pipeline task"
  type        = number
  default     = 100
}

variable "bdtopo_pipeline_work_dir" {
  description = "Working directory for BDTOPO pipeline inside the container"
  type        = string
  default     = "/tmp/bdtopo"
}

variable "bdtopo_pipeline_max_parts" {
  description = "Number of archive parts for full-France download"
  type        = number
  default     = 9
}

variable "bdtopo_pipeline_download_timeout_seconds" {
  description = "HTTP timeout (seconds) for each archive download chunk"
  type        = number
  default     = 90
}

variable "bdtopo_pipeline_download_max_retries" {
  description = "Max retry attempts per archive download"
  type        = number
  default     = 5
}

variable "bdtopo_pipeline_extraction_timeout_seconds" {
  description = "Timeout (seconds) for 7z extraction subprocess"
  type        = number
  default     = 7200
}

variable "bdtopo_pipeline_quality_threshold" {
  description = "Max ratio of invalid geometries before quality check fails"
  type        = number
  default     = 0.01
}

variable "bdtopo_pipeline_keep_downloads" {
  description = "Whether to keep downloaded archives after ingestion"
  type        = bool
  default     = false
}

variable "bdtopo_pipeline_keep_extracted" {
  description = "Whether to keep extracted GPKG files after ingestion"
  type        = bool
  default     = false
}

variable "bdtopo_pipeline_full_api_resource_url" {
  description = "Atom feed URL for full-mode BDTOPO edition discovery"
  type        = string
  default     = "https://data.geopf.fr/telechargement/resource/BDTOPO"
}

variable "bdtopo_pipeline_diff_api_resource_url" {
  description = "Atom feed URL for differential BDTOPO edition discovery"
  type        = string
  default     = "https://data.geopf.fr/telechargement/resource/BDTOPO-DIFF"
}

variable "bdtopo_pipeline_schedule_enabled" {
  description = "Whether the quarterly EventBridge schedule is active"
  type        = bool
  default     = true
}
