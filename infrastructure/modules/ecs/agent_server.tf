# Agent Server Service Configuration

locals {
  agent_server_container_definitions = [
    {
      name      = "agent-server"
      image     = var.agent_server_container_image
      essential = true

      portMappings = [
        {
          containerPort = var.agent_server_container_port
          protocol      = "tcp"
          name          = "agent-http"
        }
      ]

      environment = [
        {
          name  = "LOG_LEVEL"
          value = var.agent_server_log_level
        },
        {
          name  = "WORKERS"
          value = var.agent_server_workers
        },
        {
          name  = "PYTHONUNBUFFERED"
          value = "1"
        },
        {
          name  = "MCP_SERVER_URL"
          value = var.agent_server_mcp_server_url
        },
        {
          name  = "BEDROCK_MODEL_ID"
          value = var.agent_server_bedrock_model_id
        },
        {
          name  = "BEDROCK_REGION"
          value = var.aws_region
        },
        {
          name  = "BEDROCK_MAX_TOKENS"
          value = var.agent_server_bedrock_max_tokens
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.agent_server[0].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "agent"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:${var.agent_server_container_port}/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60 # Agent server needs more startup time for MCP connection
      }
    }
  ]
}

resource "aws_cloudwatch_log_group" "agent_server" {
  count = var.agent_server_enabled ? 1 : 0

  name              = "/ecs/${var.project_name}-agent"
  retention_in_days = 7

  tags = {
    Name        = "${var.project_name}-agent-logs"
    Environment = var.environment
  }
}

resource "aws_ecs_task_definition" "agent_server" {
  count = var.agent_server_enabled ? 1 : 0

  family                   = "${var.project_name}-agent-server"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.agent_server_task_cpu
  memory                   = var.agent_server_task_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.agent_task_role_arn

  container_definitions = jsonencode(local.agent_server_container_definitions)

  tags = {
    Name        = "${var.project_name}-agent-task"
    Environment = var.environment
  }
}

resource "aws_ecs_service" "agent_server" {
  count = var.agent_server_enabled ? 1 : 0

  name             = "${var.project_name}-agent-service"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.agent_server[0].arn
  desired_count    = var.agent_server_desired_count
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = true
  }

  service_registries {
    registry_arn = var.agent_service_discovery_registry_arn
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name        = "${var.project_name}-agent-service"
    Environment = var.environment
    Component   = "Agent-Server"
  }
}
