# Main Terraform configuration for MPLLM MCP Server

# VPC Module
module "vpc" {
  source = "./modules/vpc"

  project_name        = var.project_name
  environment         = var.environment
  vpc_cidr            = var.vpc_cidr
  availability_zones  = var.availability_zones
  public_subnet_cidrs = var.public_subnet_cidrs
}

# IAM Module
module "iam" {
  source = "./modules/iam"

  project_name         = var.project_name
  environment          = var.environment
  aws_region           = var.aws_region
  aws_account_id       = var.aws_account_id
  opentopo_api_key_arn = var.opentopo_api_key_arn
  map_key_arn          = var.map_key_arn
}

# ECR Module
module "ecr" {
  source = "./modules/ecr"

  project_name      = var.project_name
  environment       = var.environment
  aws_region        = var.aws_region
  aws_account_id    = var.aws_account_id
  github_repository = var.github_repository
}

# ECS Module
module "ecs_mcp_server" {
  source = "./modules/ecs"

  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.public_subnet_ids
  security_group_ids = [module.vpc.security_group_id]

  # MCP Server configuration
  mcp_server_cpu                = var.mcp_server_cpu
  mcp_server_memory             = var.mcp_server_memory
  mcp_server_desired_count      = var.mcp_server_desired_count
  mcp_server_container_image    = "${module.ecr.mcp_server_repository_url}:latest"
  mcp_server_container_port     = var.mcp_server_container_port
  mcp_server_log_level          = var.mcp_server_log_level
  mcp_server_workers            = var.mcp_server_workers
  mcp_server_execution_role_arn = module.iam.ecs_task_execution_role_arn
  mcp_server_task_role_arn      = module.iam.ecs_task_role_arn

  opentopo_api_key_arn = var.opentopo_api_key_arn
  map_key_arn          = var.map_key_arn

  geoserver_base_url   = var.geoserver_base_url
  geoserver_risk_layer = var.geoserver_risk_layer
  fire_archive_dir     = var.fire_archive_dir

  # Agent Server configuration
  agent_server_enabled            = var.agent_server_enabled
  agent_server_container_image    = "${module.ecr.agent_server_repository_url}:latest"
  agent_server_container_port     = var.agent_server_container_port
  agent_server_task_cpu           = var.agent_server_cpu
  agent_server_task_memory        = var.agent_server_memory
  agent_server_desired_count      = var.agent_server_desired_count
  agent_server_log_level          = var.agent_server_log_level
  agent_server_workers            = var.agent_server_workers
  agent_server_mcp_server_url     = var.agent_server_mcp_server_url
  agent_server_bedrock_model_id   = var.agent_server_bedrock_model_id
  agent_server_bedrock_max_tokens = var.agent_server_bedrock_max_tokens

  depends_on = [module.ecr]
}
