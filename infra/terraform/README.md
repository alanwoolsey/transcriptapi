# ECS/Fargate deployment for `transcriptservice.crtfystudent.com`

This Terraform stack creates:

- A VPC with public and private subnets across two AZs
- An internet-facing ALB
- An ECS cluster and Fargate service
- An ECR repository for the container image
- CloudWatch logging
- An RDS PostgreSQL instance in private subnets
- A Secrets Manager secret for the application database connection
- IAM roles for ECS execution and the app task
- Bedrock inference permissions for the app task
- Full Textract permissions for the app task
- An ACM certificate flow for `transcriptservice.crtfystudent.com`

## What this stack assumes

- AWS region: `us-east-1` by default
- DNS is hosted in GoDaddy, not Route 53
- The app runs as a single container on port `8000`
- You will build and push the Docker image to ECR
- Alembic migrations run automatically on application startup once the database exists

## Files

- Terraform root: `infra/terraform`
- Container build: `Dockerfile`
- Python runtime deps: `requirements.txt`

## 1. Prepare variables

Copy `infra/terraform/terraform.tfvars.example` to `infra/terraform/terraform.tfvars` and edit any values you need.

## 2. Initialize Terraform

```powershell
cd infra/terraform
terraform init
```

## 3. First apply

Run the first apply before creating GoDaddy DNS entries:

```powershell
terraform apply
```

This creates the network, ECR repo, ECS resources, ALB, and requests an ACM certificate. Because GoDaddy is external DNS, Terraform cannot create the certificate validation records for you.

After apply, inspect these outputs:

```powershell
terraform output acm_validation_records
terraform output alb_dns_name
terraform output ecr_repository_url
terraform output database_endpoint
```

## 4. Add GoDaddy DNS records

Create these records in GoDaddy:

1. ACM validation CNAME record(s):
   Use every entry returned by `acm_validation_records`.

2. Service CNAME record:
   - Host: `transcriptservice`
   - Points to: the value from `alb_dns_name`

Do not replace the ACM validation host with the ALB hostname. Those are separate CNAME records.

## 5. Build and push the container image

Authenticate Docker to ECR:

```powershell
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
```

Build and push:

```powershell
docker build -t transcriptservice:latest ../..
docker tag transcriptservice:latest <ecr_repository_url>:latest
docker push <ecr_repository_url>:latest
```

Replace `<account-id>` and `<ecr_repository_url>` with your values from AWS and Terraform output.

## 6. Second apply for HTTPS

Once the ACM validation records exist in GoDaddy, update `terraform.tfvars` with the created validation record names:

```hcl
certificate_validation_record_fqdns = [
  "_example1.transcriptservice.crtfystudent.com",
]
```

Then run:

```powershell
terraform apply
```

Terraform will wait for ACM to issue the certificate and then create the HTTPS listener on the ALB. At that point:

- `https://transcriptservice.crtfystudent.com/health` should respond
- HTTP on port 80 redirects to HTTPS

## IAM attached to the ECS task

The ECS task role grants:

- `bedrock:InvokeModel`
- `bedrock:InvokeModelWithResponseStream`
- `bedrock:GetInferenceProfile`
- `bedrock:ListInferenceProfiles`
- `textract:*`

The Bedrock permission choice is based on AWS Bedrock Converse documentation, which states Converse requires `bedrock:InvokeModel`, and ConverseStream requires `bedrock:InvokeModelWithResponseStream`:

- https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-call.html

The Textract permission scope is intentionally full because you asked for full Textract access:

- https://docs.aws.amazon.com/textract/latest/dg/security_iam_service-with-iam.html

## Cost note

This stack uses one NAT gateway so private Fargate tasks can reach ECR, CloudWatch, Bedrock, Textract, and Secrets Manager. That is the standard layout here, but it does add steady hourly cost.

The database runs on RDS PostgreSQL in private subnets and accepts traffic only from the ECS service security group. The ECS task receives `DATABASE_SECRET_JSON` from Secrets Manager and uses it to connect and apply Alembic migrations automatically on startup.

## GitHub Actions deployment

The repo now includes [`.github/workflows/deploy.yml`](c:/alan/transcriptapi/.github/workflows/deploy.yml), which does the following on pushes to `main` or manual dispatch:

- Applies Terraform only when files under `infra/terraform/` changed
- Builds and pushes the app container only when `app/`, `Dockerfile`, or `requirements.txt` changed
- Forces an ECS rolling deployment after a new image is pushed

It uses the two repository secrets you already created:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

The workflow also bootstraps and uses an S3 backend automatically:

- S3 bucket: `transcriptapi-terraform-state-<account-id>-us-east-1`
That keeps Terraform state out of the GitHub runner filesystem and avoids repeated attempts to recreate the stack from scratch. GitHub Actions `concurrency` prevents overlapping deploys.
