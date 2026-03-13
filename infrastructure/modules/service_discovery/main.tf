# Service Discovery Namespace for internal communication
resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = var.namespace
  vpc         = var.vpc_id
  description = "Private DNS namespace for ${var.project_name} services"

  tags = {
    Name        = "${var.project_name}-namespace"
    Environment = var.environment
  }
}

# Service Discovery Service for MCP Server
resource "aws_service_discovery_service" "mcp_server" {
  name = "mcp-server"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    Name        = "${var.project_name}-mcp-discovery"
    Environment = var.environment
  }
}

# Service Discovery Service for Agent Server
resource "aws_service_discovery_service" "agent_server" {
  name = "agent-server"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = {
    Name        = "${var.project_name}-agent-discovery"
    Environment = var.environment
  }
}
