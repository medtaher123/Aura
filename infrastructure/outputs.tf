# VPC Outputs
output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = module.vpc.public_subnet_ids
}

output "security_group_id" {
  description = "Security group ID for services"
  value       = module.vpc.security_group_id
}

# ECS Outputs
output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = module.ecs.cluster_arn
}

# MCP Server Outputs
output "mcp_service_name" {
  description = "MCP server service name"
  value       = module.ecs.mcp_service_name
}

output "mcp_task_definition_arn" {
  description = "MCP server task definition ARN"
  value       = module.ecs.mcp_task_definition_arn
}

output "mcp_cloudwatch_log_group" {
  description = "CloudWatch log group for MCP server"
  value       = module.ecs.mcp_cloudwatch_log_group
}

# Streamlit Outputs
output "streamlit_service_name" {
  description = "Streamlit service name"
  value       = module.ecs.streamlit_service_name
}

output "streamlit_task_definition_arn" {
  description = "Streamlit task definition ARN"
  value       = module.ecs.streamlit_task_definition_arn
}

output "streamlit_cloudwatch_log_group" {
  description = "CloudWatch log group for Streamlit"
  value       = module.ecs.streamlit_cloudwatch_log_group
}

# Agent Server Outputs
output "agent_service_name" {
  description = "Agent server service name"
  value       = module.ecs.agent_service_name
}

output "agent_task_definition_arn" {
  description = "Agent server task definition ARN"
  value       = module.ecs.agent_task_definition_arn
}

output "agent_cloudwatch_log_group" {
  description = "CloudWatch log group for Agent server"
  value       = module.ecs.agent_cloudwatch_log_group
}

# ALB Outputs
output "streamlit_url" {
  description = "Public URL for Streamlit service"
  value       = var.cloudfront_enabled ? one(module.cloudfront[*].url) : module.alb.app_url
}

output "cloudfront_domain" {
  description = "CloudFront distribution domain (*.cloudfront.net), null when CloudFront is disabled"
  value       = one(module.cloudfront[*].domain_name)
}

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = module.alb.alb_dns_name
}

output "alb_arn" {
  description = "ARN of the Application Load Balancer"
  value       = module.alb.alb_arn
}

# Service Discovery Outputs
output "service_discovery_namespace" {
  description = "Service discovery namespace"
  value       = var.service_discovery_namespace
}

output "mcp_server_internal_url" {
  description = "Internal URL for MCP server"
  value       = "http://${module.service_discovery.mcp_server_dns_name}:8000"
}

# ECR Outputs
output "mcp_ecr_repository_url" {
  description = "ECR repository URL for MCP server"
  value       = module.ecr.mcp_repository_url
}

output "streamlit_ecr_repository_url" {
  description = "ECR repository URL for Streamlit"
  value       = module.ecr.streamlit_repository_url
}

output "agent_ecr_repository_url" {
  description = "ECR repository URL for Agent server"
  value       = module.ecr.agent_repository_url
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions"
  value       = module.ecr.github_actions_role_arn
}

# IAM Outputs
output "ecs_task_execution_role_arn" {
  description = "ECS Task Execution Role ARN (shared)"
  value       = module.iam.ecs_task_execution_role_arn
}

output "mcp_task_role_arn" {
  description = "MCP Server Task Role ARN"
  value       = module.iam.mcp_task_role_arn
}

output "agent_task_role_arn" {
  description = "Agent Server Task Role ARN"
  value       = module.iam.agent_task_role_arn
}

output "streamlit_task_role_arn" {
  description = "Streamlit Task Role ARN"
  value       = module.iam.streamlit_task_role_arn
}

output "postgis_enabled" {
  description = "Whether managed PostGIS is enabled"
  value       = module.postgis.enabled
}

output "postgis_endpoint" {
  description = "Managed PostGIS endpoint"
  value       = module.postgis.endpoint
}

output "postgis_port" {
  description = "Managed PostGIS port"
  value       = module.postgis.port
}

output "postgis_master_user_secret_arn" {
  description = "Secrets Manager ARN for managed PostGIS master credentials"
  value       = module.postgis.master_user_secret_arn
}

# BDTOPO Pipeline outputs
output "bdtopo_pipeline_ecr_repository_url" {
  description = "ECR repository URL for BDTOPO pipeline"
  value       = module.ecr.bdtopo_pipeline_repository_url
}

output "bdtopo_pipeline_task_definition_arn" {
  description = "BDTOPO pipeline task definition ARN"
  value       = module.ecs.bdtopo_pipeline_task_definition_arn
}

output "bdtopo_pipeline_cloudwatch_log_group" {
  description = "BDTOPO pipeline CloudWatch log group name"
  value       = module.ecs.bdtopo_pipeline_cloudwatch_log_group
}
