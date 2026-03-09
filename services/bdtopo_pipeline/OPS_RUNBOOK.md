# BDTOPO Ops Runbook (ECS Fargate + EventBridge)

This runbook covers the minimum production setup for:

- scheduled quarterly ingestion via EventBridge Scheduler + ECS Fargate task
- ad-hoc ingestion via `aws ecs run-task`
- runtime BDTOPO queries in the MCP server on ECS (`bdtopo_query_tool`)

## 1) Required Terraform Variables

### Secrets (AWS Secrets Manager)

Both the pipeline task and the MCP server read `BDTOPO_DATABASE_URL` from the same
Secrets Manager secret, injected via ECS task `secrets`:

- `bdtopo_database_url_secret_arn` (required): ARN of the secret containing the PostGIS DSN.

### Feature flags

- `bdtopo_pipeline_enabled = true`: creates the ECR repo, ECS task definition,
  IAM roles, and EventBridge schedule.
- `bdtopo_pipeline_schedule_enabled = true`: enables the quarterly cron
  (set to `false` to keep the task definition but disable automatic runs).

### Sizing (optional overrides)

- `bdtopo_pipeline_cpu` (default `"4096"`)
- `bdtopo_pipeline_memory` (default `"16384"`)
- `bdtopo_pipeline_ephemeral_storage_gib` (default `100`)

## 2) Create PostGIS DSN Secret

If using the managed PostGIS module, first deploy infra with:

- `postgis_enabled = true`
- suitable sizing values (documented in `infrastructure/terraform.tfvars.example`)

Then create an app-level DSN secret:

```bash
cd infrastructure
terraform output postgis_endpoint
terraform output postgis_port

MASTER_SECRET_ARN="$(terraform output -raw postgis_master_user_secret_arn)"
aws secretsmanager get-secret-value \
  --secret-id "$MASTER_SECRET_ARN" \
  --query SecretString \
  --output text

# Build DSN and store as dedicated app secret
aws secretsmanager create-secret \
  --name "eo-agent/production/BDTOPO_DATABASE_URL" \
  --secret-string '{"BDTOPO_DATABASE_URL":"postgresql://<user>:<password>@<endpoint>:5432/bdtopo"}'
```

Use the returned ARN as `bdtopo_database_url_secret_arn` in `terraform.tfvars`, then:

```bash
terraform apply
```

## 3) Deploy the Pipeline

Enable the pipeline in `terraform.tfvars`:

```hcl
bdtopo_pipeline_enabled          = true
bdtopo_pipeline_schedule_enabled = true
```

Apply:

```bash
cd infrastructure
terraform apply
```

This creates:
- ECR repository `eo-agent-bdtopo-pipeline`
- ECS task definition `eo-agent-bdtopo-pipeline`
- CloudWatch log group `/ecs/eo-agent-bdtopo-pipeline`
- EventBridge schedule `eo-agent-bdtopo-quarterly-refresh` (cron: 16th of Jan/Apr/Jul/Oct at 03:00 UTC)
- IAM roles for the pipeline task and EventBridge scheduler

The Docker image is built and pushed automatically by the
`.github/workflows/bdtopo-pipeline-ecr.yml` CI workflow on pushes to `main`.

## 4) Ad-hoc Runs

Trigger a one-off ingestion with specific parameters:

```bash
aws ecs run-task \
  --cluster eo-agent-cluster \
  --task-definition eo-agent-bdtopo-pipeline \
  --launch-type FARGATE \
  --network-configuration '{
    "awsvpcConfiguration": {
      "subnets": ["subnet-xxx","subnet-yyy","subnet-zzz"],
      "securityGroups": ["sg-xxx"],
      "assignPublicIp": "ENABLED"
    }
  }' \
  --overrides '{
    "containerOverrides": [{
      "name": "bdtopo-pipeline",
      "command": ["--mode", "full", "--edition-date", "2025-12-15"]
    }]
  }'
```

Omit `--command` to use defaults (`--mode full`, edition date = today).

Monitor the task:

```bash
# List running tasks
aws ecs list-tasks --cluster eo-agent-cluster \
  --family eo-agent-bdtopo-pipeline --desired-status RUNNING

# Check logs
aws logs tail /ecs/eo-agent-bdtopo-pipeline --follow
```

## 5) Verification Checklist

- Terraform includes `bdtopo_database_url_secret_arn` and applies cleanly.
- ECS task definitions for both MCP and pipeline contain `BDTOPO_DATABASE_URL` in `secrets`.
- Pipeline Docker image exists in ECR (`eo-agent-bdtopo-pipeline:latest`).
- A manual `aws ecs run-task` completes with exit code 0.
- MCP server starts without config errors and `bdtopo_query_tool` answers requests.
- Data appears in:
  - `bdtopo_raw.*`
  - `bdtopo_curated.mv_admin_latest`, `mv_transport_latest`, `mv_regulated_latest`, `mv_places_latest`

## 6) Secret Rotation

- Rotate secret value in AWS Secrets Manager (same ARN).
- Force ECS redeploy so MCP server pulls the latest secret:
  - `terraform apply` (if task definition changed), or
  - `aws ecs update-service --cluster eo-agent-cluster --service eo-agent-mcp-service --force-new-deployment`
- The pipeline task always fetches the latest secret at launch time (no redeploy needed).

## 7) Common Failure Modes

- **Missing `BDTOPO_DATABASE_URL`**:
  - Pipeline: loader raises `ValueError`.
  - MCP server: query tool returns configuration error.
- **Secret ARN unset in Terraform**:
  - ECS task starts without DB DSN; pipeline fails immediately.
- **Incorrect SG/network path to RDS**:
  - Connection timeout from ECS tasks. Verify the pipeline task's security group
    is in the PostGIS `allowed_security_group_ids`.
- **Missing `BDTOPO_SOURCE_URLS` in `express`/`differential` mode**:
  - Manifest builder raises validation error. Pass URLs via `--command` override
    with env var `BDTOPO_SOURCE_URLS`.
- **Ephemeral storage exhausted**:
  - Task exits with error during extraction. Increase `bdtopo_pipeline_ephemeral_storage_gib`.
