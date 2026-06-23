terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  backend "s3" {
    bucket  = "eo-agent-terraform-state-963275461308"
    key     = "eo-agent-terraform-2.tfstate"
    region  = "eu-west-3"
    encrypt = true
    #use_lockfile = true

    #profile = "MLOps-963275461308"
  }
}

provider "aws" {
  region = var.aws_region
  #profile = "MLOps-963275461308"

  default_tags {
    tags = {
      Project     = "EO-Agent"
      ManagedBy   = "Terraform"
      Environment = var.environment
    }
  }
}
