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
  value       = module.ecs_mcp_server.cluster_name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = module.ecs_mcp_server.cluster_arn
}

output "mcp_server_service_name" {
  description = "MCP server service name"
  value       = module.ecs_mcp_server.mcp_server_service_name
}

output "mcp_server_task_definition_arn" {
  description = "MCP server task definition ARN"
  value       = module.ecs_mcp_server.mcp_server_task_definition_arn
}

output "mcp_server_cloudwatch_log_group_name" {
  description = "CloudWatch log group for MCP server"
  value       = module.ecs_mcp_server.mcp_server_cloudwatch_log_group_name
}

# ECR Outputs
output "mcp_server_ecr_repository_url" {
  description = "ECR repository URL for MCP server"
  value       = module.ecr.mcp_server_repository_url
}

output "mcp_server_ecr_repository_arn" {
  description = "ECR repository ARN for MCP server"
  value       = module.ecr.mcp_server_repository_arn
}

output "agent_server_ecr_repository_url" {
  description = "ECR repository URL for Agent server"
  value       = module.ecr.agent_server_repository_url
}

output "agent_server_ecr_repository_arn" {
  description = "ECR repository ARN for Agent server"
  value       = module.ecr.agent_server_repository_arn
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions"
  value       = module.ecr.github_actions_role_arn
}

# Agent Server ECS Outputs
output "agent_server_service_name" {
  description = "Agent server service name"
  value       = module.ecs_mcp_server.agent_server_service_name
}

output "agent_server_task_definition_arn" {
  description = "Agent server task definition ARN"
  value       = module.ecs_mcp_server.agent_server_task_definition_arn
}

output "agent_server_cloudwatch_log_group_name" {
  description = "CloudWatch log group for Agent server"
  value       = module.ecs_mcp_server.agent_server_cloudwatch_log_group_name
}

# IAM Outputs
output "ecs_task_execution_role_arn" {
  description = "ECS Task Execution Role ARN"
  value       = module.iam.ecs_task_execution_role_arn
}

output "ecs_task_role_arn" {
  description = "ECS Task Role ARN"
  value       = module.iam.ecs_task_role_arn
}
