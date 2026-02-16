# MCP Server repository outputs
output "mcp_repository_url" {
  description = "ECR repository URL for MCP server"
  value       = aws_ecr_repository.mcp_server.repository_url
}

output "mcp_repository_arn" {
  description = "ECR repository ARN for MCP server"
  value       = aws_ecr_repository.mcp_server.arn
}

# Streamlit repository outputs
output "streamlit_repository_url" {
  description = "ECR repository URL for Streamlit"
  value       = aws_ecr_repository.streamlit.repository_url
}

output "streamlit_repository_arn" {
  description = "ECR repository ARN for Streamlit"
  value       = aws_ecr_repository.streamlit.arn
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions"
  value       = aws_iam_role.github_actions_ecr.arn
}

# Legacy outputs for backward compatibility
output "repository_url" {
  description = "ECR repository URL for MCP server (legacy, use mcp_repository_url)"
  value       = aws_ecr_repository.mcp_server.repository_url
}

output "repository_arn" {
  description = "ECR repository ARN (legacy, use mcp_repository_arn)"
  value       = aws_ecr_repository.mcp_server.arn
}
