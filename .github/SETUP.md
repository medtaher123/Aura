# GitHub Actions Deployment Setup

This guide explains how to set up automatic deployment to AWS App Runner using GitHub Actions.

## Prerequisites

1. An AWS account with appropriate permissions
2. This repository pushed to GitHub

## Setup Steps

### Step 1: Create AWS IAM User for GitHub Actions

1. Go to AWS IAM Console
2. Click **"Users"** → **"Create user"**
3. User name: `github-actions-metaplanet`
4. Click **Next**
5. Select **"Attach policies directly"**
6. Attach these policies:
   - `AWSAppRunnerFullAccess`
   - `AmazonEC2ContainerRegistryFullAccess`
7. Click **Next** → **Create user**

### Step 2: Create Access Keys

1. Click on the newly created user
2. Go to **"Security credentials"** tab
3. Scroll to **"Access keys"**
4. Click **"Create access key"**
5. Select **"Application running outside AWS"**
6. Click **Next** → **Create access key**
7. **⚠️ IMPORTANT:** Save both:
   - Access key ID
   - Secret access key
   (You won't be able to see the secret again!)

### Step 3: Add Secrets to GitHub Repository

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **"New repository secret"**
4. Add these two secrets:

   **Secret 1:**
   - Name: `AWS_ACCESS_KEY_ID`
   - Value: [Your AWS Access Key ID from Step 2]

   **Secret 2:**
   - Name: `AWS_SECRET_ACCESS_KEY`
   - Value: [Your AWS Secret Access Key from Step 2]

### Step 4: Configure Workflow (Optional)

The workflow file is located at `.github/workflows/deploy-to-aws.yml`.

You can customize these settings if needed:

```yaml
env:
  AWS_REGION: us-east-1           # Change region if needed
  ECR_REPOSITORY: metaplanet-llm  # Change ECR repo name
  APP_RUNNER_SERVICE: metaplanet-llm  # Change App Runner service name
```

### Step 5: Deploy!

The deployment happens automatically in two ways:

#### Option A: Automatic (on push to main)
```bash
git add .
git commit -m "Deploy to AWS"
git push origin main
```

#### Option B: Manual trigger
1. Go to your GitHub repository
2. Click **Actions** tab
3. Select **"Deploy to AWS App Runner"** workflow
4. Click **"Run workflow"** → **"Run workflow"**

## Monitoring Deployment

### View Progress
1. Go to **Actions** tab in GitHub
2. Click on the running workflow
3. Watch the logs in real-time

### Deployment Steps
The workflow performs these steps automatically:
1. ✅ Checkout code
2. ✅ Configure AWS credentials
3. ✅ Login to Amazon ECR
4. ✅ Create ECR repository (if needed)
5. ✅ Build Docker image (~10-15 minutes)
6. ✅ Push to ECR
7. ✅ Deploy/Update App Runner service
8. ✅ Wait for deployment to complete
9. ✅ Display service URL

### Total Time
- **First deployment:** ~20-25 minutes (includes service creation)
- **Subsequent deployments:** ~15-20 minutes

## After Deployment

Once the workflow completes:

1. Check the **Summary** section in the GitHub Actions run for:
   - Service URL (e.g., `https://xxxxxxxxxx.us-east-1.awsapprunner.com`)
   - Docker image tag
   - Deployment region

2. Access your app at the provided URL

3. **⚠️ First startup takes 5-10 minutes** - The container needs to download the 4GB Mistral model

## Verify Deployment

### Check App Runner Service
```bash
aws apprunner list-services --region us-east-1
```

### View Logs
```bash
aws logs tail /aws/apprunner/metaplanet-llm/service --follow
```

### Get Service URL
```bash
aws apprunner list-services --region us-east-1 \
  --query "ServiceSummaryList[?ServiceName=='metaplanet-llm'].ServiceUrl" \
  --output text
```

## Troubleshooting

### Workflow fails at "Configure AWS credentials"
- ✅ Verify `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are set correctly in GitHub Secrets
- ✅ Check IAM user has required permissions

### Workflow fails at "Create ECR repository"
- ℹ️ This is normal if repository already exists (step uses `continue-on-error: true`)

### Workflow fails at "Build Docker image"
- ✅ Check Dockerfile syntax
- ✅ Verify all required files exist (requirements.txt, streamlit_app.py, etc.)
- ✅ Check GitHub Actions runner has enough disk space

### Workflow fails at "Deploy to AWS App Runner"
- ✅ Verify IAM user has `AWSAppRunnerFullAccess` permission
- ✅ Check AWS region is correct
- ✅ Review CloudWatch logs for service errors

### App Runner service unhealthy
- ✅ Verify 12 GB memory is allocated (minimum for Ollama)
- ✅ Check health check path is `/_stcore/health`
- ✅ Increase health check start period if model download is slow
- ✅ Review CloudWatch logs: `aws logs tail /aws/apprunner/metaplanet-llm/service --follow`

### App is slow or times out
- First LLM query takes 10-30 seconds (normal)
- Consider increasing CPU to 8 vCPU
- Monitor memory usage in CloudWatch

## Cost Estimation

With GitHub Actions + AWS App Runner:

- **GitHub Actions:** Free for public repos, 2000 minutes/month for private repos
- **ECR Storage:** ~$1-2/month (for Docker images)
- **App Runner:** ~$70-120/month (12 GB RAM, 4 vCPU)
- **Data Transfer:** ~$10-20/month
- **Total:** ~$90-150/month

## Updating the Application

Just push to main branch:

```bash
git add .
git commit -m "Update feature X"
git push origin main
```

The workflow automatically:
1. Builds new Docker image
2. Pushes to ECR with commit SHA tag
3. Triggers App Runner deployment
4. Waits for deployment to complete
5. Provides new service URL (same URL, updated app)

## Cleanup

### Delete App Runner Service
```bash
aws apprunner delete-service \
  --service-arn $(aws apprunner list-services --region us-east-1 \
    --query "ServiceSummaryList[?ServiceName=='metaplanet-llm'].ServiceArn" \
    --output text) \
  --region us-east-1
```

### Delete ECR Repository
```bash
aws ecr delete-repository \
  --repository-name metaplanet-llm \
  --region us-east-1 \
  --force
```

### Delete IAM User
1. Go to IAM Console
2. Select `github-actions-metaplanet` user
3. Delete access keys first
4. Then delete user

## Security Best Practices

✅ **Use GitHub Secrets** - Never commit AWS credentials to code  
✅ **Principle of Least Privilege** - IAM user has only required permissions  
✅ **Rotate Credentials** - Periodically rotate AWS access keys  
✅ **Monitor Costs** - Set up AWS Budget alerts  
✅ **Review Logs** - Check CloudWatch logs regularly  

## Next Steps (Optional)

- Add authentication to Streamlit app (AWS Cognito)
- Set up custom domain with Route 53
- Add staging environment (deploy on pull requests)
- Implement blue-green deployments
- Add automated testing before deployment
- Migrate API keys to AWS Secrets Manager
- Set up CloudWatch alarms for monitoring
