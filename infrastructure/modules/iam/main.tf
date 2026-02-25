# ECS Task Execution Role (shared)
# Used by ECS to pull images, write logs, and access secrets
resource "aws_iam_role" "ecs_task_execution_role" {
  name = "ecsTaskExecutionRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "ecsTaskExecutionRole"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_task_execution_secrets" {
  name = "ecs-task-execution-secrets"
  role = aws_iam_role.ecs_task_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = [
          var.opentopo_api_key_arn,
          var.map_key_arn,
          var.maptiler_api_key_arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

# --------------------------------------------------------------------------
# Per-service Task Roles
# --------------------------------------------------------------------------

locals {
  ecs_assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  shared_statements = [
    {
      Sid    = "CloudWatchLogs"
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/ecs/${var.project_name}-*:*"
    },
    {
      Sid    = "ECSDescribe"
      Effect = "Allow"
      Action = [
        "ec2:DescribeNetworkInterfaces",
        "ecs:DescribeTasks"
      ]
      Resource = "*"
    }
  ]
}

# --- MCP Server Task Role ---
# Needs: CloudWatch, ECS describe, S3, Athena, Glue (tool execution layer)
resource "aws_iam_role" "mcp_task_role" {
  name               = "${var.project_name}-mcp-task-role"
  assume_role_policy = local.ecs_assume_role_policy

  tags = {
    Name        = "${var.project_name}-mcp-task-role"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_role_policy" "mcp_task_role_policy" {
  name = "mcp-task-role-policy"
  role = aws_iam_role.mcp_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(local.shared_statements, [
      {
        Sid    = "S3Access"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:HeadObject",
          "s3:GetBucketLocation"
        ]
        Resource = [
          "arn:aws:s3:::metaplanet-*",
          "arn:aws:s3:::metaplanet-*/*",
          "arn:aws:s3:::${var.project_name}-*",
          "arn:aws:s3:::${var.project_name}-*/*"
        ]
      },
      {
        Sid    = "AthenaAccess"
        Effect = "Allow"
        Action = [
          "athena:*",
        ]
        Resource = "*"
      },
      {
        Sid    = "GlueAccess"
        Effect = "Allow"
        Action = [
          "glue:*",
        ]
        Resource = [
          "*"
        ]
      }
    ])
  })
}

# --- Agent Server Task Role ---
# Needs: CloudWatch, ECS describe, Bedrock (LLM orchestration layer)
resource "aws_iam_role" "agent_task_role" {
  name               = "${var.project_name}-agent-task-role"
  assume_role_policy = local.ecs_assume_role_policy

  tags = {
    Name        = "${var.project_name}-agent-task-role"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_role_policy" "agent_task_role_policy" {
  name = "agent-task-role-policy"
  role = aws_iam_role.agent_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(local.shared_statements, [
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:${var.aws_account_id}:inference-profile/*"
        ]
      }
    ])
  })
}

# --- Streamlit Task Role ---
# Needs: CloudWatch, ECS describe only (UI layer, talks to Agent server via WebSocket)
resource "aws_iam_role" "streamlit_task_role" {
  name               = "${var.project_name}-streamlit-task-role"
  assume_role_policy = local.ecs_assume_role_policy

  tags = {
    Name        = "${var.project_name}-streamlit-task-role"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_iam_role_policy" "streamlit_task_role_policy" {
  name = "streamlit-task-role-policy"
  role = aws_iam_role.streamlit_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = local.shared_statements
  })
}
