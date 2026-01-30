output "mcp_server_repository_url" {
  description = "ECR repository URL for MCP server"
  value       = aws_ecr_repository.mcp_server.repository_url
}

output "mcp_server_repository_arn" {
  description = "ECR repository ARN for MCP server"
  value       = aws_ecr_repository.mcp_server.arn
}

output "agent_server_repository_url" {
  description = "ECR repository URL for Agent server"
  value       = aws_ecr_repository.agent_server.repository_url
}

output "agent_server_repository_arn" {
  description = "ECR repository ARN for Agent server"
  value       = aws_ecr_repository.agent_server.arn
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions"
  value       = aws_iam_role.github_actions_ecr.arn
}
