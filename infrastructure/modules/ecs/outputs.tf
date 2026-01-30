output "cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

output "mcp_server_service_name" {
  description = "MCP server ECS service name"
  value       = aws_ecs_service.mcp_server.name
}

output "mcp_server_task_definition_arn" {
  description = "MCP server task definition ARN"
  value       = aws_ecs_task_definition.mcp_server.arn
}

output "mcp_server_cloudwatch_log_group_name" {
  description = "MCP server CloudWatch log group name"
  value       = aws_cloudwatch_log_group.mcp_server.name
}

# Agent Server outputs
output "agent_server_service_name" {
  description = "Agent server ECS service name"
  value       = var.agent_server_enabled ? aws_ecs_service.agent_server[0].name : null
}

output "agent_server_task_definition_arn" {
  description = "Agent server task definition ARN"
  value       = var.agent_server_enabled ? aws_ecs_task_definition.agent_server[0].arn : null
}

output "agent_server_cloudwatch_log_group_name" {
  description = "Agent server CloudWatch log group name"
  value       = var.agent_server_enabled ? aws_cloudwatch_log_group.agent_server[0].name : null
}
