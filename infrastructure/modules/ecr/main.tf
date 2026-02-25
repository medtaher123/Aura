# ECR Repository for MCP Server
resource "aws_ecr_repository" "mcp_server" {
  name                 = "${var.project_name}-mcp-server"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name        = "${var.project_name}-mcp-server"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# ECR Lifecycle Policy - Keep last 10 images
resource "aws_ecr_lifecycle_policy" "mcp_server" {
  repository = aws_ecr_repository.mcp_server.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ECR Repository for Streamlit
resource "aws_ecr_repository" "streamlit" {
  name                 = "${var.project_name}-streamlit"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name        = "${var.project_name}-streamlit"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# ECR Lifecycle Policy for Streamlit - Keep last 10 images
resource "aws_ecr_lifecycle_policy" "streamlit" {
  repository = aws_ecr_repository.streamlit.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ECR Repository for Agent Server
resource "aws_ecr_repository" "agent_server" {
  name                 = "${var.project_name}-server"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name        = "${var.project_name}-server"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# ECR Lifecycle Policy for Agent Server - Keep last 10 images
resource "aws_ecr_lifecycle_policy" "agent_server" {
  repository = aws_ecr_repository.agent_server.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# Retrieve GitHub OIDC provider's TLS certificate
data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com"
}

# GitHub Actions OIDC Provider
resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com"
  ]

  thumbprint_list = [
    data.tls_certificate.github.certificates[0].sha1_fingerprint
  ]

  tags = {
    Name        = "github-actions"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM Role for GitHub Actions
resource "aws_iam_role" "github_actions_ecr" {
  name = "github-actions-ecr-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:*"
          }
        }
      }
    ]
  })

  tags = {
    Name        = "github-actions-ecr-role"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM Policy for ECR Push
resource "aws_iam_policy" "github_actions_ecr" {
  name        = "github-actions-ecr-policy"
  description = "Policy for GitHub Actions to push to ECR and update ECS"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ]
        Resource = [
          aws_ecr_repository.mcp_server.arn,
          aws_ecr_repository.agent_server.arn,
          aws_ecr_repository.streamlit.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices"
        ]
        Resource = [
          "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:service/${var.project_name}-cluster/${var.project_name}-mcp-service",
          "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:service/${var.project_name}-cluster/${var.project_name}-streamlit-service",
          "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:service/${var.project_name}-cluster/${var.project_name}-agent-service"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition"
        ]
        Resource = "*"
      }
    ]
  })

  tags = {
    Name        = "github-actions-ecr-policy"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# Attach policy to role
resource "aws_iam_role_policy_attachment" "github_actions_ecr" {
  role       = aws_iam_role.github_actions_ecr.name
  policy_arn = aws_iam_policy.github_actions_ecr.arn
}
