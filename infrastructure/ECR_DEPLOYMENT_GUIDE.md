# MCP Server - ECR Deployment Guide

This document describes the ECR-based deployment pipeline for the MCP Server.

## Overview

The MCP Server is containerized and deployed to AWS ECS Fargate with images stored in Amazon ECR. GitHub Actions automatically builds and pushes new images on commits to main/develop branches.

## Architecture

```
GitHub Repository → GitHub Actions → Amazon ECR → AWS ECS Fargate
```

## Components

### 1. Docker Image ([services/mcp_server/Dockerfile](../../services/mcp_server/Dockerfile))

The Dockerfile includes:
- **Base**: Python 3.11 slim
- **Geospatial libraries**: GDAL, Proj, GEOS for rasterio and shapely
- **Health checks**: HTTP endpoint at `/health`
- **Dependencies**: All MCP server requirements including FastMCP SDK

### 2. ECR Repository (Terraform)

Defined in [infrastructure/ecr.tf](../ecr.tf):
- Repository name: `mpllm-mcp-server`
- Image scanning enabled
- Lifecycle policy: Keep last 10 images
- AES256 encryption

### 3. GitHub Actions Workflow

File: [.github/workflows/mcp-server-ecr.yml](../../.github/workflows/mcp-server-ecr.yml)

**Triggers:**
- Push to `main` or `develop` branches (only when mcp_server changes)
- Pull requests to `main`
- Manual workflow dispatch

**Steps:**
1. Authenticate with AWS using OIDC (no long-lived credentials)
2. Login to ECR
3. Build Docker image with Buildx (includes caching)
4. Push to ECR with multiple tags
5. Update ECS service (main branch only)
6. Wait for deployment stability

**Image Tags:**
- `latest` (main branch only)
- `main-<sha>` or `develop-<sha>`
- Branch name (e.g., `main`, `develop`)
- Semantic versions if tagged

### 4. IAM Role for GitHub Actions

Defined in [infrastructure/ecr.tf](../ecr.tf):

**OIDC Provider**: GitHub Actions identity provider
**Role**: `github-actions-ecr-role`
**Permissions**:
- ECR: Push/pull images
- ECS: Update service and describe tasks
- CloudWatch: Implicit through ECS

## Setup Instructions

### 1. Configure GitHub Repository Secret

Add the AWS Account ID to GitHub Secrets:

```bash
# In GitHub repo settings → Secrets and variables → Actions
# Add secret: AWS_ACCOUNT_ID = 963275461308
```

### 2. Update Terraform Variables

Edit [infrastructure/terraform.tfvars](../terraform.tfvars):

```hcl
github_repository = "your-github-org/mp-llm-ines"
```

### 3. Deploy Infrastructure

```bash
cd infrastructure
terraform init
terraform plan
terraform apply
```

This creates:
- ECR repository
- OIDC provider for GitHub
- IAM role with ECR/ECS permissions
- Updated ECS task definition pointing to ECR

### 4. Initial Image Push

**Option A: Via GitHub Actions**
```bash
git commit -m "Trigger initial build"
git push origin main
```

**Option B: Manual Push**
```bash
cd services/mcp_server

# Login to ECR
aws ecr get-login-password --region eu-west-3 | \
  docker login --username AWS --password-stdin \
  963275461308.dkr.ecr.eu-west-3.amazonaws.com

# Build and push
docker build -t mpllm-mcp-server .
docker tag mpllm-mcp-server:latest \
  963275461308.dkr.ecr.eu-west-3.amazonaws.com/mpllm-mcp-server:latest
docker push 963275461308.dkr.ecr.eu-west-3.amazonaws.com/mpllm-mcp-server:latest
```

## CI/CD Workflow

### Automatic Deployment (Main Branch)

1. Developer pushes to `main` branch
2. GitHub Actions builds Docker image
3. Image is pushed to ECR with `latest` and `main-<sha>` tags
4. ECS service is updated with force new deployment
5. ECS pulls latest image and deploys new tasks
6. Old tasks are drained after health checks pass

### Development Workflow (Feature Branches)

1. Developer pushes to `develop` or feature branch
2. Image is built and pushed with branch-specific tags
3. No automatic ECS deployment (manual update required)

## Monitoring

### Build Status

Check GitHub Actions tab for build status:
```
https://github.com/your-org/mp-llm-ines/actions
```

### Deployment Status

Check ECS service in AWS Console or CLI:
```bash
aws ecs describe-services \
  --cluster mpllm-cluster \
  --services mpllm-mcp-service \
  --region eu-west-3
```

### Image Scan Results

ECR automatically scans images for vulnerabilities:
```bash
aws ecr describe-image-scan-findings \
  --repository-name mpllm-mcp-server \
  --image-id imageTag=latest \
  --region eu-west-3
```

## Terraform Outputs

After applying Terraform, you'll get:

```hcl
ecr_repository_url = "963275461308.dkr.ecr.eu-west-3.amazonaws.com/mpllm-mcp-server"
ecr_repository_arn = "arn:aws:ecr:eu-west-3:963275461308:repository/mpllm-mcp-server"
github_actions_role_arn = "arn:aws:iam::963275461308:role/github-actions-ecr-role"
```

## Troubleshooting

### Build Fails in GitHub Actions

1. Check GitHub Actions logs
2. Verify Dockerfile syntax locally: `docker build services/mcp_server`
3. Check that AWS credentials are configured correctly

### Image Push Fails

1. Verify ECR repository exists: `aws ecr describe-repositories`
2. Check IAM role permissions
3. Verify OIDC provider is configured correctly

### ECS Deployment Fails

1. Check ECS service events: `aws ecs describe-services`
2. Verify task definition is valid
3. Check CloudWatch logs for container errors
4. Ensure secrets (API keys) are accessible

### Health Check Fails

1. Check that `/health` endpoint is responding
2. Verify environment variables are set correctly
3. Check CloudWatch logs for startup errors

## Security Considerations

1. **No long-lived credentials**: Uses OIDC for GitHub Actions authentication
2. **Least privilege**: IAM role has minimal permissions needed
3. **Image scanning**: Automatic vulnerability scanning on push
4. **Encryption**: ECR images encrypted at rest with AES256
5. **Secrets management**: API keys stored in AWS Secrets Manager

## Cost Optimization

1. **Lifecycle policy**: Only keeps last 10 images
2. **Build caching**: GitHub Actions cache reduces build time
3. **Multi-stage builds**: Could be added to reduce image size further
4. **Fargate Spot**: Consider for non-production environments

## Future Enhancements

- [ ] Multi-stage Docker build for smaller images
- [ ] ARM64 support for Graviton instances
- [ ] Blue/Green deployments
- [ ] Automated rollback on health check failures
- [ ] Performance testing in CI pipeline
- [ ] Container image signing
