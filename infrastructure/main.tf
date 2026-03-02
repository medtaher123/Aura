# Main Terraform configuration for EO-Agent Services

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
  maptiler_api_key_arn = var.maptiler_api_key_arn
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

# Service Discovery Module
module "service_discovery" {
  source = "./modules/service_discovery"

  project_name = var.project_name
  environment  = var.environment
  vpc_id       = module.vpc.vpc_id
  namespace    = var.service_discovery_namespace
}

# ALB Module for Streamlit
module "alb" {
  source = "./modules/alb"

  project_name = var.project_name
  environment  = var.environment
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.public_subnet_ids
}

# ECS Module with MCP, Streamlit, and Agent services
module "ecs" {
  source = "./modules/ecs"

  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.public_subnet_ids
  security_group_ids = [module.vpc.security_group_id]

  execution_role_arn     = module.iam.ecs_task_execution_role_arn
  mcp_task_role_arn      = module.iam.mcp_task_role_arn
  agent_task_role_arn    = module.iam.agent_task_role_arn
  streamlit_task_role_arn = module.iam.streamlit_task_role_arn

  # MCP Server configuration
  mcp_server_container_image = "${module.ecr.mcp_repository_url}:latest"
  mcp_server_container_port  = 8000
  mcp_server_cpu             = var.mcp_server_cpu
  mcp_server_memory          = var.mcp_server_memory
  mcp_server_desired_count   = var.mcp_server_desired_count
  mcp_server_log_level       = var.mcp_log_level
  mcp_server_workers         = var.mcp_workers

  opentopo_api_key_arn = var.opentopo_api_key_arn
  map_key_arn          = var.map_key_arn

  geoserver_base_url   = var.geoserver_base_url
  geoserver_risk_layer = var.geoserver_risk_layer
  fire_archive_dir     = var.fire_archive_dir

  service_discovery_registry_arn = module.service_discovery.mcp_server_service_arn

  # Streamlit configuration
  streamlit_container_image = "${module.ecr.streamlit_repository_url}:latest"
  streamlit_cpu             = var.streamlit_cpu
  streamlit_memory          = var.streamlit_memory
  streamlit_desired_count   = var.streamlit_desired_count
  target_group_arn          = module.alb.target_group_arn
  agent_server_url          = "ws://${module.service_discovery.agent_server_dns_name}:8080"
  maptiler_api_key_arn      = var.maptiler_api_key_arn

  # Agent Server configuration
  agent_server_enabled         = var.agent_server_enabled
  agent_server_container_image = "${module.ecr.agent_repository_url}:latest"
  agent_server_container_port  = 8080
  agent_server_task_cpu        = var.agent_server_cpu
  agent_server_task_memory     = var.agent_server_memory
  agent_server_desired_count   = var.agent_server_desired_count
  agent_server_log_level       = var.agent_server_log_level
  agent_server_workers         = var.agent_server_workers
  agent_server_mcp_server_url  = "http://${module.service_discovery.mcp_server_dns_name}:8000"
  agent_server_bedrock_model_id    = var.agent_server_bedrock_model_id
  agent_server_bedrock_max_tokens  = var.agent_server_bedrock_max_tokens
  agent_service_discovery_registry_arn = module.service_discovery.agent_server_service_arn

  depends_on = [module.ecr, module.service_discovery, module.alb]
}
