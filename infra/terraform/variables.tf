variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
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

variable "tags" {
  description = "Additional tags to apply to resources."
  type        = map(string)
  default     = {}
}
