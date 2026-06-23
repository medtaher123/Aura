# MCP Server Service Configuration

locals {
  mcp_container_secrets = concat(
    [
      {
        name      = "OPENTOPO_API_KEY"
        valueFrom = "${var.opentopo_api_key_arn}:OPENTOPO_API_KEY::"
      },
      {
        name      = "MAP_KEY"
        valueFrom = "${var.map_key_arn}:MAP_KEY::"
      }
    ],
    var.bdtopo_database_url_secret_arn != "" ? [
      {
        name      = "BDTOPO_DATABASE_URL"
        valueFrom = "${var.bdtopo_database_url_secret_arn}:BDTOPO_DATABASE_URL::"
      }
    ] : []
  )

  mcp_container_definitions = [
    {
      name      = "mcp-server"
      image     = var.mcp_server_container_image
      essential = true

      portMappings = [
        {
          containerPort = var.mcp_server_container_port
          protocol      = "tcp"
          name          = "mcp-http"
        }
      ]

      environment = [
        {
          name  = "LOG_LEVEL"
          value = var.mcp_server_log_level
        },
        {
          name  = "WORKERS"
          value = var.mcp_server_workers
        },
        {
          name  = "PYTHONUNBUFFERED"
          value = "1"
        },
        {
          name  = "DEBUG"
          value = var.debug_enabled ? "true" : "false"
        },
        {
          name  = "GEOSERVER_BASE_URL"
          value = var.geoserver_base_url
        },
        {
          name  = "GEOSERVER_RISK_LAYER"
          value = var.geoserver_risk_layer
        },
        {
          name  = "FIRE_ARCHIVE_DIR"
          value = var.fire_archive_dir
        }
      ]

      secrets = local.mcp_container_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.mcp_server.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "mcp"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:${var.mcp_server_container_port}/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    }
  ]
}

resource "aws_cloudwatch_log_group" "mcp_server" {
  name              = "/ecs/${var.project_name}-mcp"
  retention_in_days = 7

  tags = {
    Name        = "${var.project_name}-mcp-logs"
    Environment = var.environment
  }
}

resource "aws_ecs_task_definition" "mcp_server" {
  family                   = "${var.project_name}-mcp-server"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.mcp_server_cpu
  memory                   = var.mcp_server_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.mcp_task_role_arn

  container_definitions = jsonencode(local.mcp_container_definitions)

  tags = {
    Name        = "${var.project_name}-mcp-task"
    Environment = var.environment
  }
}

resource "aws_ecs_service" "mcp_server" {
  name             = "${var.project_name}-mcp-service"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.mcp_server.arn
  desired_count    = var.mcp_server_desired_count
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  enable_execute_command = var.debug_enabled

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = true
  }

  # Service Discovery configuration
  service_registries {
    registry_arn = var.service_discovery_registry_arn
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name        = "${var.project_name}-mcp-service"
    Environment = var.environment
    Component   = "MCP-Server"
  }
}
