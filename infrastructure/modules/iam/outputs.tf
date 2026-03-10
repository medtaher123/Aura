output "ecs_task_execution_role_arn" {
  description = "ECS Task Execution Role ARN (shared)"
  value       = aws_iam_role.ecs_task_execution_role.arn
}

output "mcp_task_role_arn" {
  description = "MCP Server Task Role ARN"
  value       = aws_iam_role.mcp_task_role.arn
}

output "agent_task_role_arn" {
  description = "Agent Server Task Role ARN"
  value       = aws_iam_role.agent_task_role.arn
}

output "streamlit_task_role_arn" {
  description = "Streamlit Task Role ARN"
  value       = aws_iam_role.streamlit_task_role.arn
}

output "bdtopo_pipeline_task_role_arn" {
  description = "BDTOPO Pipeline Task Role ARN"
  value       = try(aws_iam_role.bdtopo_pipeline_task_role[0].arn, null)
}

output "eventbridge_scheduler_role_arn" {
  description = "EventBridge Scheduler Role ARN for BDTOPO pipeline"
  value       = try(aws_iam_role.eventbridge_scheduler[0].arn, null)
}
