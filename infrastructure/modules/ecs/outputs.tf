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

# Agent Server outputs
output "agent_service_name" {
  description = "Agent server ECS service name"
  value       = try(aws_ecs_service.agent_server[0].name, "")
}

output "agent_task_definition_arn" {
  description = "Agent server Task definition ARN"
  value       = try(aws_ecs_task_definition.agent_server[0].arn, "")
}

output "agent_cloudwatch_log_group" {
  description = "Agent server CloudWatch log group name"
  value       = try(aws_cloudwatch_log_group.agent_server[0].name, "")
}

# BDTOPO Pipeline outputs
output "bdtopo_pipeline_task_definition_arn" {
  description = "BDTOPO pipeline task definition ARN"
  value       = try(aws_ecs_task_definition.bdtopo_pipeline[0].arn, "")
}

output "bdtopo_pipeline_cloudwatch_log_group" {
  description = "BDTOPO pipeline CloudWatch log group name"
  value       = try(aws_cloudwatch_log_group.bdtopo_pipeline[0].name, "")
}
