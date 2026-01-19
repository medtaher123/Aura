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

variable "task_cpu" {
  description = "CPU units for the task"
  type        = string
}

variable "task_memory" {
  description = "Memory for the task"
  type        = string
}

variable "desired_count" {
  description = "Desired number of tasks"
  type        = number
}

variable "container_image" {
  description = "Docker image for the container"
  type        = string
}

variable "container_port" {
  description = "Port exposed by the container"
  type        = number
  default     = 8000
}

variable "log_level" {
  description = "Log level for the application"
  type        = string
}

variable "workers" {
  description = "Number of workers"
  type        = string
}

variable "execution_role_arn" {
  description = "ARN of the task execution role"
  type        = string
}

variable "task_role_arn" {
  description = "ARN of the task role"
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
