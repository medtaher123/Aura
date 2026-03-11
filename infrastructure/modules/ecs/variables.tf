# Shared variables
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

variable "execution_role_arn" {
  description = "ARN of the task execution role (shared)"
  type        = string
}

variable "mcp_task_role_arn" {
  description = "ARN of the MCP server task role"
  type        = string
}

variable "agent_task_role_arn" {
  description = "ARN of the Agent server task role"
  type        = string
}

variable "streamlit_task_role_arn" {
  description = "ARN of the Streamlit task role"
  type        = string
}

# MCP Server variables
variable "mcp_server_container_image" {
  description = "Docker image for MCP server container"
  type        = string
}

variable "mcp_server_container_port" {
  description = "Port exposed by the MCP server container"
  type        = number
  default     = 8000
}

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

variable "bdtopo_database_url_secret_arn" {
  description = "Secrets Manager ARN containing BDTOPO_DATABASE_URL connection string"
  type        = string
  default     = ""
}

variable "service_discovery_registry_arn" {
  description = "ARN of the service discovery registry for MCP server"
  type        = string
  default     = ""
}

variable "agent_service_discovery_registry_arn" {
  description = "ARN of the service discovery registry for Agent server"
  type        = string
  default     = ""
}

# Streamlit variables
variable "streamlit_container_image" {
  description = "Docker image for Streamlit container"
  type        = string
  default     = ""
}

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

variable "target_group_arn" {
  description = "ARN of the ALB target group for Streamlit"
  type        = string
  default     = ""
}

variable "agent_server_url" {
  description = "WebSocket URL for Agent server (used by Streamlit)"
  type        = string
  default     = ""
}

variable "maptiler_api_key_arn" {
  description = "ARN for Maptiler API key secret"
  type        = string
  default     = "arn:aws:secretsmanager:eu-west-3:963275461308:secret:mpllm/api-keys/MAPTILER_API_KEY-cfpZua"
}

# Agent Server variables
variable "agent_server_enabled" {
  description = "Whether to create agent server resources"
  type        = bool
  default     = true
}

variable "agent_server_container_image" {
  description = "Docker image for Agent server container"
  type        = string
  default     = ""
}

variable "agent_server_container_port" {
  description = "Port exposed by the Agent server container"
  type        = number
  default     = 8080
}

variable "agent_server_task_cpu" {
  description = "CPU units for Agent server task"
  type        = string
  default     = "4096"
}

variable "agent_server_task_memory" {
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

variable "agent_server_mcp_server_url" {
  description = "MCP server URL for Agent server"
  type        = string
  default     = ""
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

# BDTOPO Pipeline variables
variable "bdtopo_pipeline_enabled" {
  description = "Whether to create BDTOPO pipeline task definition and schedule"
  type        = bool
  default     = true
}

variable "bdtopo_pipeline_container_image" {
  description = "Docker image for BDTOPO pipeline container"
  type        = string
  default     = ""
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
  default     = 50
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

variable "bdtopo_pipeline_task_role_arn" {
  description = "ARN of the BDTOPO pipeline task role"
  type        = string
  default     = ""
}

variable "eventbridge_scheduler_role_arn" {
  description = "ARN of the EventBridge Scheduler role for BDTOPO pipeline"
  type        = string
  default     = ""
}

variable "bdtopo_pipeline_schedule_enabled" {
  description = "Whether the quarterly EventBridge schedule is active"
  type        = bool
  default     = true
}
