# Main Terraform configuration for EO-Agent Services

# VPC Module
module "vpc" {
  source = "./modules/vpc"

  project_name         = var.project_name
  environment          = var.environment
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
}

# IAM Module
module "iam" {
  source = "./modules/iam"

  project_name                   = var.project_name
  environment                    = var.environment
  aws_region                     = var.aws_region
  aws_account_id                 = var.aws_account_id
  execution_role_name            = var.execution_role_name
  opentopo_api_key_arn           = var.opentopo_api_key_arn
  map_key_arn                    = var.map_key_arn
  maptiler_api_key_arn           = var.maptiler_api_key_arn
  bdtopo_database_url_secret_arn = var.bdtopo_database_url_secret_arn
  bdtopo_pipeline_enabled        = var.bdtopo_pipeline_enabled
  cognito_client_secret_arn      = var.cognito_client_secret_arn
}

# ECR Module
module "ecr" {
  source = "./modules/ecr"

  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  aws_account_id     = var.aws_account_id
  github_repository  = var.github_repository
  create_github_oidc = var.create_github_oidc
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

  enable_https      = var.alb_enable_https
  alb_domain_name   = var.alb_domain_name
  route53_zone_name = var.route53_zone_name
}

# Managed PostGIS baseline for BDTOPO full-France workloads
module "postgis" {
  source = "./modules/postgis"

  enabled                    = var.postgis_enabled
  project_name               = var.project_name
  environment                = var.environment
  vpc_id                     = module.vpc.vpc_id
  subnet_ids                 = module.vpc.private_subnet_ids
  allowed_security_group_ids = [module.vpc.security_group_id]
  instance_class             = var.postgis_instance_class
  allocated_storage          = var.postgis_allocated_storage
  max_allocated_storage      = var.postgis_max_allocated_storage
  multi_az                   = var.postgis_multi_az
  backup_retention_period    = var.postgis_backup_retention_period
  db_name                    = var.postgis_db_name
  master_username            = var.postgis_master_username
  deletion_protection        = var.postgis_deletion_protection
}

# CloudFront CDN in front of the Streamlit ALB (edge TLS via *.cloudfront.net)
module "cloudfront" {
  source = "./modules/cloudfront"
  count  = var.cloudfront_enabled ? 1 : 0

  project_name = var.project_name
  environment  = var.environment
  alb_dns_name = module.alb.alb_dns_name
}

locals {
  # Public HTTPS URL of the app: CloudFront when enabled, else the ALB custom domain/HTTP.
  cloudfront_url = one(module.cloudfront[*].url)

  # Cognito redirect URIs: explicit tfvars value wins; otherwise derive from CloudFront.
  cognito_redirect_uri_effective = (
    var.cognito_redirect_uri != "" ? var.cognito_redirect_uri :
    local.cloudfront_url != null ? "${local.cloudfront_url}/" :
    ""
  )
  cognito_logout_redirect_uri_effective = (
    var.cognito_logout_redirect_uri != "" ? var.cognito_logout_redirect_uri :
    local.cloudfront_url != null ? "${local.cloudfront_url}/" :
    ""
  )
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

  execution_role_arn      = module.iam.ecs_task_execution_role_arn
  mcp_task_role_arn       = module.iam.mcp_task_role_arn
  agent_task_role_arn     = module.iam.agent_task_role_arn
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

  geoserver_base_url             = var.geoserver_base_url
  geoserver_risk_layer           = var.geoserver_risk_layer
  fire_archive_dir               = var.fire_archive_dir
  bdtopo_database_url_secret_arn = var.bdtopo_database_url_secret_arn

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
  agent_server_enabled                 = var.agent_server_enabled
  agent_server_container_image         = "${module.ecr.agent_repository_url}:latest"
  agent_server_container_port          = 8080
  agent_server_task_cpu                = var.agent_server_cpu
  agent_server_task_memory             = var.agent_server_memory
  agent_server_desired_count           = var.agent_server_desired_count
  agent_server_log_level               = var.agent_server_log_level
  agent_server_workers                 = var.agent_server_workers
  agent_server_mcp_server_url          = "http://${module.service_discovery.mcp_server_dns_name}:8000"
  agent_server_bedrock_model_id        = var.agent_server_bedrock_model_id
  agent_server_bedrock_max_tokens      = var.agent_server_bedrock_max_tokens
  agent_service_discovery_registry_arn = module.service_discovery.agent_server_service_arn


  # Cognito / Authentication (shared by Agent Server and Streamlit)
  auth_enabled                = var.auth_enabled
  agent_auth_providers        = var.agent_auth_providers
  cognito_region              = var.cognito_region
  cognito_user_pool_id        = var.cognito_user_pool_id
  cognito_domain              = var.cognito_domain
  cognito_app_client_id       = var.cognito_app_client_id
  cognito_token_use           = var.cognito_token_use
  cognito_jwt_leeway_seconds  = var.cognito_jwt_leeway_seconds
  cognito_client_secret_arn   = var.cognito_client_secret_arn
  cognito_redirect_uri        = local.cognito_redirect_uri_effective
  cognito_logout_redirect_uri = local.cognito_logout_redirect_uri_effective
  cognito_scopes              = var.cognito_scopes

  # BDTOPO Pipeline configuration
  bdtopo_pipeline_enabled                    = var.bdtopo_pipeline_enabled
  bdtopo_pipeline_container_image            = "${module.ecr.bdtopo_pipeline_repository_url}:latest"
  bdtopo_pipeline_cpu                        = var.bdtopo_pipeline_cpu
  bdtopo_pipeline_memory                     = var.bdtopo_pipeline_memory
  bdtopo_pipeline_ephemeral_storage_gib      = var.bdtopo_pipeline_ephemeral_storage_gib
  bdtopo_pipeline_task_role_arn              = module.iam.bdtopo_pipeline_task_role_arn
  eventbridge_scheduler_role_arn             = module.iam.eventbridge_scheduler_role_arn
  bdtopo_pipeline_schedule_enabled           = var.bdtopo_pipeline_schedule_enabled
  bdtopo_pipeline_work_dir                   = var.bdtopo_pipeline_work_dir
  bdtopo_pipeline_max_parts                  = var.bdtopo_pipeline_max_parts
  bdtopo_pipeline_download_timeout_seconds   = var.bdtopo_pipeline_download_timeout_seconds
  bdtopo_pipeline_download_max_retries       = var.bdtopo_pipeline_download_max_retries
  bdtopo_pipeline_extraction_timeout_seconds = var.bdtopo_pipeline_extraction_timeout_seconds
  bdtopo_pipeline_quality_threshold          = var.bdtopo_pipeline_quality_threshold
  bdtopo_pipeline_keep_downloads             = var.bdtopo_pipeline_keep_downloads
  bdtopo_pipeline_keep_extracted             = var.bdtopo_pipeline_keep_extracted
  bdtopo_pipeline_full_api_resource_url      = var.bdtopo_pipeline_full_api_resource_url
  bdtopo_pipeline_diff_api_resource_url      = var.bdtopo_pipeline_diff_api_resource_url

  depends_on = [module.ecr, module.service_discovery, module.alb]
}
