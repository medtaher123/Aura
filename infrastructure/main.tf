# Main Terraform configuration for MPLLM MCP Server

module "vpc" {
  source = "./modules/vpc"

  project_name         = var.project_name
  environment          = var.environment
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  public_subnet_cidrs  = var.public_subnet_cidrs
}

# IAM roles (using existing roles)
data "aws_iam_role" "ecs_task_execution_role" {
  name = "ecsTaskExecutionRole"
}

data "aws_iam_role" "ecs_task_role" {
  name = "ecsTaskRole"
}

module "ecs_mcp_server" {
  source = "./modules/ecs"

  project_name          = var.project_name
  environment           = var.environment
  aws_region            = var.aws_region
  vpc_id                = module.vpc.vpc_id
  subnet_ids            = module.vpc.public_subnet_ids
  security_group_ids    = [module.vpc.security_group_id]
  
  task_cpu              = var.mcp_server_cpu
  task_memory           = var.mcp_server_memory
  desired_count         = var.mcp_server_desired_count
  container_image       = var.mcp_server_image
  container_port        = 8000
  
  log_level             = var.mcp_log_level
  workers               = var.mcp_workers
  
  execution_role_arn    = data.aws_iam_role.ecs_task_execution_role.arn
  task_role_arn         = data.aws_iam_role.ecs_task_role.arn
  
  opentopo_api_key_arn  = var.opentopo_api_key_arn
  map_key_arn           = var.map_key_arn
}
