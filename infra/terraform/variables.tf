variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "cognito_user_pool_id" {
  description = "Shared Cognito user pool ID for auth."
  type        = string
  default     = "us-east-1_QzbkX105v"
}

variable "cognito_app_client_id" {
  description = "Shared Cognito app client ID for auth."
  type        = string
  default     = "9j409k1g1kgu67qq2t4ii86rt"
}

variable "cors_allowed_origins" {
  description = "Allowed browser origins for cross-origin API requests in non-dev environments."
  type        = list(string)
  default = [
    "*",
  ]
}

variable "project_name" {
  description = "Project name used in resource names and tags."
  type        = string
  default     = "transcriptapi"
}

variable "service_name" {
  description = "Logical service name."
  type        = string
  default     = "transcriptservice"
}

variable "domain_name" {
  description = "Public hostname for the ALB listener certificate and GoDaddy CNAME."
  type        = string
  default     = "transcriptservice.crtfystudent.com"
}

variable "enable_managed_acm_certificate" {
  description = "When true, Terraform requests an ACM certificate for domain_name."
  type        = bool
  default     = true
}

variable "existing_certificate_arn" {
  description = "Use an existing issued ACM certificate ARN instead of creating one."
  type        = string
  default     = null
  nullable    = true
}

variable "certificate_validation_record_fqdns" {
  description = "FQDNs of DNS validation records created manually in GoDaddy. Supply these on the second apply so Terraform can wait for ACM issuance."
  type        = list(string)
  default     = []
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "availability_zone_count" {
  description = "Number of AZs to spread across."
  type        = number
  default     = 2
}

variable "container_port" {
  description = "Port exposed by the FastAPI container."
  type        = number
  default     = 8000
}

variable "task_cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Desired ECS task count."
  type        = number
  default     = 1
}

variable "app_env" {
  description = "APP_ENV passed to the container."
  type        = string
  default     = "prod"
}

variable "use_bedrock" {
  description = "USE_BEDROCK passed to the container."
  type        = bool
  default     = true
}

variable "use_textract" {
  description = "USE_TEXTRACT passed to the container."
  type        = bool
  default     = true
}

variable "bedrock_model_id" {
  description = "Default Bedrock model ID used by the service."
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "health_check_path" {
  description = "ALB target group health check path."
  type        = string
  default     = "/health"
}

variable "ecr_image_tag" {
  description = "Image tag the ECS service should deploy from ECR."
  type        = string
  default     = "latest"
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
  default     = 30
}

variable "db_name" {
  description = "Application PostgreSQL database name."
  type        = string
  default     = "crtfystudent"
}

variable "db_username" {
  description = "Master username for the PostgreSQL instance."
  type        = string
  default     = "crtfy_app"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.small"
}

variable "db_allocated_storage" {
  description = "Initial allocated storage in GB."
  type        = number
  default     = 20
}

variable "db_max_allocated_storage" {
  description = "Autoscaling storage ceiling in GB."
  type        = number
  default     = 100
}

variable "db_backup_retention_period" {
  description = "Automated backup retention in days."
  type        = number
  default     = 7
}

variable "db_multi_az" {
  description = "Whether the RDS instance should be Multi-AZ."
  type        = bool
  default     = false
}

variable "db_deletion_protection" {
  description = "Whether to protect the RDS instance from deletion."
  type        = bool
  default     = false
}

variable "db_skip_final_snapshot" {
  description = "Whether to skip the final snapshot when destroying the database."
  type        = bool
  default     = true
}

variable "db_enable_local_access" {
  description = "When true, place the RDS instance in public subnets, mark it publicly accessible, and allow ingress from db_local_access_cidrs for local testing."
  type        = bool
  default     = false
}

variable "db_local_access_cidrs" {
  description = "CIDR blocks allowed to connect directly to PostgreSQL when db_enable_local_access is true."
  type        = list(string)
  default     = []
}

variable "db_enable_bastion" {
  description = "When true, create a small public EC2 bastion for SSH tunneling into the VPC."
  type        = bool
  default     = false
}

variable "db_bastion_public_key_path" {
  description = "Path to the SSH public key used for the bastion instance when db_enable_bastion is true."
  type        = string
  default     = null
  nullable    = true
}

variable "tags" {
  description = "Additional tags to apply to resources."
  type        = map(string)
  default     = {}
}
