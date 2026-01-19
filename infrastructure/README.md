# MPLLM MCP Server - Terraform Infrastructure

This directory contains Terraform configuration for deploying the MPLLM MCP Server to AWS ECS Fargate.

## 📁 Structure

```
terraform/
├── main.tf                    # Main configuration, module orchestration
├── providers.tf               # AWS provider and backend configuration
├── variables.tf               # Input variable definitions
├── outputs.tf                 # Output value definitions
├── terraform.tfvars           # Variable values (gitignored)
├── terraform.tfvars.example   # Example variable values
├── .gitignore                 # Terraform-specific gitignore
└── modules/
    ├── vpc/                   # VPC module (network infrastructure)
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    └── ecs/                   # ECS module (container orchestration)
        ├── main.tf
        ├── variables.tf
        └── outputs.tf
```

## 🚀 Quick Start

### Prerequisites

1. **Install Terraform** (v1.5.0 or later)
   ```bash
   # On macOS
   brew install terraform
   
   # On Linux
   wget https://releases.hashicorp.com/terraform/1.5.0/terraform_1.5.0_linux_amd64.zip
   unzip terraform_1.5.0_linux_amd64.zip
   sudo mv terraform /usr/local/bin/
   ```

2. **AWS CLI configured**
   ```bash
   aws configure
   # Enter your AWS Access Key ID, Secret Access Key, and default region (eu-west-3)
   ```

3. **Verify AWS credentials**
   ```bash
   aws sts get-caller-identity
   ```

### Initial Setup

1. **Navigate to terraform directory**
   ```bash
   cd infrastructure/terraform
   ```

2. **Review and customize variables**
   ```bash
   # The terraform.tfvars file is already configured with your values
   # Review it and make any necessary changes
   cat terraform.tfvars
   ```

3. **Initialize Terraform**
   ```bash
   terraform init
   ```

## 📋 Deployment

### Plan Changes

Always review what Terraform will do before applying:

```bash
terraform plan
```

This will show you:
- Resources to be created
- Resources to be modified
- Resources to be destroyed

### Apply Configuration

Deploy the infrastructure:

```bash
terraform apply
```

Review the plan and type `yes` to confirm.

### View Outputs

After successful deployment:

```bash
terraform output
```

Example output:
```
cluster_name = "mpllm-cluster"
mcp_service_name = "mpllm-mcp-service"
vpc_id = "vpc-xxxxx"
public_subnet_ids = ["subnet-xxxxx", "subnet-yyyyy", "subnet-zzzzz"]
```

## 🔄 Common Operations

### Update Container Image

1. Update the `mcp_server_image` variable in [terraform.tfvars](terraform.tfvars)
2. Apply the change:
   ```bash
   terraform apply
   ```

### Scale Service

1. Update `mcp_server_desired_count` in [terraform.tfvars](terraform.tfvars)
2. Apply:
   ```bash
   terraform apply
   ```

### View Current State

```bash
# List all resources
terraform state list

# Show specific resource details
terraform state show module.ecs_mcp_server.aws_ecs_service.mcp_server
```

### Refresh State

Sync Terraform state with actual AWS resources:

```bash
terraform refresh
```

## 🗑️ Destroy Infrastructure

**⚠️ Warning: This will delete all resources!**

```bash
terraform destroy
```

Review the plan and type `yes` to confirm.

## 🔐 Remote State (Optional but Recommended)

For team collaboration, store Terraform state in S3:

1. **Create S3 bucket and DynamoDB table** (one-time setup):
   ```bash
   # Create S3 bucket for state
   aws s3 mb s3://mpllm-terraform-state --region eu-west-3
   
   # Enable versioning
   aws s3api put-bucket-versioning \
     --bucket mpllm-terraform-state \
     --versioning-configuration Status=Enabled
   
   # Enable encryption
   aws s3api put-bucket-encryption \
     --bucket mpllm-terraform-state \
     --server-side-encryption-configuration '{
       "Rules": [{
         "ApplyServerSideEncryptionByDefault": {
           "SSEAlgorithm": "AES256"
         }
       }]
     }'
   
   # Create DynamoDB table for state locking
   aws dynamodb create-table \
     --table-name mpllm-terraform-locks \
     --attribute-definitions AttributeName=LockID,AttributeType=S \
     --key-schema AttributeName=LockID,KeyType=HASH \
     --billing-mode PAY_PER_REQUEST \
     --region eu-west-3
   ```

2. **Uncomment backend configuration** in [providers.tf](providers.tf):
   ```hcl
   backend "s3" {
     bucket         = "mpllm-terraform-state"
     key            = "mcp-server/terraform.tfstate"
     region         = "eu-west-3"
     encrypt        = true
     dynamodb_table = "mpllm-terraform-locks"
   }
   ```

3. **Migrate state**:
   ```bash
   terraform init -migrate-state
   ```

## 📊 Monitoring

### View ECS Service Status

```bash
# Service status
aws ecs describe-services \
  --cluster mpllm-cluster \
  --services mpllm-mcp-service \
  --region eu-west-3

# Task status
aws ecs list-tasks \
  --cluster mpllm-cluster \
  --service-name mpllm-mcp-service \
  --region eu-west-3
```

### View Logs

```bash
# View CloudWatch logs
aws logs tail /ecs/mpllm-mcp --follow --region eu-west-3
```

## 🏗️ Architecture

This Terraform configuration creates:

### VPC Module
- **VPC**: 10.0.0.0/16 CIDR block
- **3 Public Subnets**: Across 3 availability zones (eu-west-3a, 3b, 3c)
- **Internet Gateway**: For public internet access
- **Route Tables**: Public routing
- **Security Group**: Allows MCP (8000) and Streamlit (8501) within VPC

### ECS Module
- **ECS Cluster**: Fargate cluster with Container Insights
- **Task Definition**: MCP server container with health checks
- **ECS Service**: Manages task deployment and scaling
- **CloudWatch Log Group**: Centralized logging

## 🔧 Troubleshooting

### Task Not Starting

1. Check task logs:
   ```bash
   aws logs tail /ecs/mpllm-mcp --follow
   ```

2. Verify task definition:
   ```bash
   aws ecs describe-task-definition \
     --task-definition mpllm-mcp-server \
     --region eu-west-3
   ```

### State Lock Issues

If terraform operations are stuck with a state lock:

```bash
# Force unlock (use with caution!)
terraform force-unlock <LOCK_ID>
```

### Permission Issues

Ensure your AWS IAM user/role has permissions for:
- EC2 (VPC, Subnets, Security Groups)
- ECS (Clusters, Services, Tasks)
- IAM (Read access for roles)
- CloudWatch Logs
- Secrets Manager (Read access)

## 📝 Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `aws_region` | AWS region | `eu-west-3` |
| `project_name` | Project name prefix | `mpllm` |
| `environment` | Environment name | `production` |
| `mcp_server_cpu` | CPU units for task | `256` |
| `mcp_server_memory` | Memory for task | `512` |
| `mcp_server_desired_count` | Number of tasks | `1` |
| `mcp_server_image` | Docker image | ECR image URL |

See [variables.tf](variables.tf) for complete list.

## 🔮 Future Enhancements

This infrastructure is designed to accommodate additional services:

- **Streamlit WebApp**: Can be added as another ECS service
- **Agent Services**: Additional containers in the same VPC
- **Load Balancer**: For distributing traffic
- **Auto-scaling**: Based on CPU/memory metrics
- **Private Subnets**: For enhanced security

## 📚 Resources

- [Terraform AWS Provider Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [AWS ECS Best Practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/intro.html)
- [Terraform Modules](https://www.terraform.io/docs/language/modules/index.html)
