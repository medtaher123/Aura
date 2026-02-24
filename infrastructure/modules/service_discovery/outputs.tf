output "namespace_id" {
  description = "ID of the service discovery namespace"
  value       = aws_service_discovery_private_dns_namespace.main.id
}

output "namespace_arn" {
  description = "ARN of the service discovery namespace"
  value       = aws_service_discovery_private_dns_namespace.main.arn
}

output "namespace_hosted_zone_id" {
  description = "Hosted zone ID of the service discovery namespace"
  value       = aws_service_discovery_private_dns_namespace.main.hosted_zone
}

output "mcp_server_service_id" {
  description = "ID of the MCP server service discovery service"
  value       = aws_service_discovery_service.mcp_server.id
}

output "mcp_server_service_arn" {
  description = "ARN of the MCP server service discovery service"
  value       = aws_service_discovery_service.mcp_server.arn
}

output "mcp_server_dns_name" {
  description = "DNS name for the MCP server"
  value       = "mcp-server.${var.namespace}"
}
