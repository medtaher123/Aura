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

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs_mcp_server.cluster_name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = module.ecs_mcp_server.cluster_arn
}

output "mcp_service_name" {
  description = "MCP server service name"
  value       = module.ecs_mcp_server.service_name
}

output "mcp_task_definition_arn" {
  description = "MCP server task definition ARN"
  value       = module.ecs_mcp_server.task_definition_arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for MCP server"
  value       = module.ecs_mcp_server.cloudwatch_log_group
}
