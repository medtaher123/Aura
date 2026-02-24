output "cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

# MCP Server outputs
output "mcp_service_name" {
  description = "MCP ECS service name"
  value       = aws_ecs_service.mcp_server.name
}

output "mcp_task_definition_arn" {
  description = "MCP Task definition ARN"
  value       = aws_ecs_task_definition.mcp_server.arn
}

output "mcp_cloudwatch_log_group" {
  description = "MCP CloudWatch log group name"
  value       = aws_cloudwatch_log_group.mcp_server.name
}

# Streamlit outputs
output "streamlit_service_name" {
  description = "Streamlit ECS service name"
  value       = try(aws_ecs_service.streamlit.name, "")
}

output "streamlit_task_definition_arn" {
  description = "Streamlit Task definition ARN"
  value       = try(aws_ecs_task_definition.streamlit.arn, "")
}

output "streamlit_cloudwatch_log_group" {
  description = "Streamlit CloudWatch log group name"
  value       = try(aws_cloudwatch_log_group.streamlit.name, "")
}

# Legacy outputs for backward compatibility
output "service_name" {
  description = "ECS service name (legacy, use mcp_service_name)"
  value       = aws_ecs_service.mcp_server.name
}

output "task_definition_arn" {
  description = "Task definition ARN (legacy, use mcp_task_definition_arn)"
  value       = aws_ecs_task_definition.mcp_server.arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group name (legacy, use mcp_cloudwatch_log_group)"
  value       = aws_cloudwatch_log_group.mcp_server.name
}
