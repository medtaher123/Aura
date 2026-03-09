# BDTOPO Pipeline – standalone Fargate task (batch job, not a service)

resource "aws_cloudwatch_log_group" "bdtopo_pipeline" {
  count             = var.bdtopo_pipeline_enabled ? 1 : 0
  name              = "/ecs/${var.project_name}-bdtopo-pipeline"
  retention_in_days = 30

  tags = {
    Name        = "${var.project_name}-bdtopo-pipeline-logs"
    Environment = var.environment
  }
}

resource "aws_ecs_task_definition" "bdtopo_pipeline" {
  count                    = var.bdtopo_pipeline_enabled ? 1 : 0
  family                   = "${var.project_name}-bdtopo-pipeline"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.bdtopo_pipeline_cpu
  memory                   = var.bdtopo_pipeline_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.bdtopo_pipeline_task_role_arn

  ephemeral_storage {
    size_in_gib = var.bdtopo_pipeline_ephemeral_storage_gib
  }

  container_definitions = jsonencode([
    {
      name      = "bdtopo-pipeline"
      image     = var.bdtopo_pipeline_container_image
      essential = true

      environment = [
        {
          name  = "PYTHONUNBUFFERED"
          value = "1"
        }
      ]

      secrets = [
        {
          name      = "BDTOPO_DATABASE_URL"
          valueFrom = "${var.bdtopo_database_url_secret_arn}:BDTOPO_DATABASE_URL::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.bdtopo_pipeline[0].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "bdtopo"
        }
      }
    }
  ])

  tags = {
    Name        = "${var.project_name}-bdtopo-pipeline-task"
    Environment = var.environment
  }
}

# --------------------------------------------------------------------------
# EventBridge Scheduler – quarterly full-France refresh
# --------------------------------------------------------------------------

resource "aws_scheduler_schedule" "bdtopo_quarterly" {
  count       = var.bdtopo_pipeline_enabled ? 1 : 0
  name        = "${var.project_name}-bdtopo-quarterly-refresh"
  group_name  = "default"
  description = "Quarterly BDTOPO full-France ingestion (16th of Jan/Apr/Jul/Oct at 03:00 UTC)"

  schedule_expression          = "cron(0 3 16 3,6,9,12 ? *)"
  schedule_expression_timezone = "UTC"
  state                        = var.bdtopo_pipeline_schedule_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = var.eventbridge_scheduler_role_arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.bdtopo_pipeline[0].arn
      launch_type         = "FARGATE"
      platform_version    = "LATEST"
      task_count          = 1

      network_configuration {
        subnets          = var.subnet_ids
        security_groups  = var.security_group_ids
        assign_public_ip = true
      }
    }

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}
