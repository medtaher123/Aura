# Streamlit Service Configuration

locals {
  streamlit_container_definitions = [
    {
      name      = "streamlit"
      image     = var.streamlit_container_image
      essential = true

      portMappings = [
        {
          containerPort = 8501
          protocol      = "tcp"
          name          = "streamlit-http"
        }
      ]

      environment = [
        {
          name  = "PYTHONUNBUFFERED"
          value = "1"
        },
        {
          name  = "AGENT_SERVER_URL"
          value = var.agent_server_url
        },
        {
          name  = "FIRE_ARCHIVE_DIR"
          value = var.fire_archive_dir
        }
      ]

      secrets = [
        {
          name      = "MAPTILER_API_KEY"
          # Inject only the JSON key from SecretString, not the full object.
          valueFrom = "${var.maptiler_api_key_arn}:MAPTILER_API_KEY::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.streamlit.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "streamlit"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8501/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ]
}

resource "aws_cloudwatch_log_group" "streamlit" {
  name              = "/ecs/${var.project_name}-streamlit"
  retention_in_days = 7

  tags = {
    Name        = "${var.project_name}-streamlit-logs"
    Environment = var.environment
  }
}

resource "aws_ecs_task_definition" "streamlit" {
  family                   = "${var.project_name}-streamlit"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.streamlit_cpu
  memory                   = var.streamlit_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.streamlit_task_role_arn

  container_definitions = jsonencode(local.streamlit_container_definitions)

  tags = {
    Name        = "${var.project_name}-streamlit-task"
    Environment = var.environment
  }
}

resource "aws_ecs_service" "streamlit" {
  name             = "${var.project_name}-streamlit-service"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.streamlit.arn
  desired_count    = var.streamlit_desired_count
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "streamlit"
    container_port   = 8501
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [var.target_group_arn]

  tags = {
    Name        = "${var.project_name}-streamlit-service"
    Environment = var.environment
    Component   = "Streamlit"
  }
}
