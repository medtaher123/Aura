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

# ECS Module with both MCP and Streamlit services
module "ecs" {
  source = "./modules/ecs"

  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.public_subnet_ids
  security_group_ids = [module.vpc.security_group_id]

  # MCP Server configuration
  task_cpu        = var.mcp_server_cpu
  task_memory     = var.mcp_server_memory
  desired_count   = var.mcp_server_desired_count
  container_image = "${module.ecr.mcp_repository_url}:latest"
  container_port  = 8000

  log_level = var.mcp_log_level
  workers   = var.mcp_workers

  execution_role_arn = module.iam.ecs_task_execution_role_arn
  task_role_arn      = module.iam.ecs_task_role_arn

  opentopo_api_key_arn = var.opentopo_api_key_arn
  map_key_arn          = var.map_key_arn

  geoserver_base_url   = var.geoserver_base_url
  geoserver_risk_layer = var.geoserver_risk_layer
  fire_archive_dir     = var.fire_archive_dir

  # Service Discovery
  service_discovery_registry_arn = module.service_discovery.mcp_server_service_arn

  # Streamlit configuration
  streamlit_container_image = "${module.ecr.streamlit_repository_url}:latest"
  streamlit_cpu             = var.streamlit_cpu
  streamlit_memory          = var.streamlit_memory
  streamlit_desired_count   = var.streamlit_desired_count
  target_group_arn          = module.alb.target_group_arn
  mcp_server_url            = "http://${module.service_discovery.mcp_server_dns_name}:8000"
  maptiler_api_key_arn      = var.maptiler_api_key_arn

  depends_on = [module.ecr, module.service_discovery, module.alb]
}
