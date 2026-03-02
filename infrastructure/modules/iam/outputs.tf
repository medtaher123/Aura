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
