output "cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

output "service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.mcp_server.name
}

output "task_definition_arn" {
  description = "Task definition ARN"
  value       = aws_ecs_task_definition.mcp_server.arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.mcp_server.name
}
