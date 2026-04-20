output "alb_dns_name" {
  description = "DNS name of the application load balancer. Point the GoDaddy CNAME for transcriptservice to this value."
  value       = aws_lb.this.dns_name
}

output "service_url" {
  description = "Best current URL for the service."
  value       = local.https_ready ? "https://${var.domain_name}" : "http://${aws_lb.this.dns_name}"
}

output "ecr_repository_url" {
  description = "ECR repository URL for docker build and push."
  value       = aws_ecr_repository.service.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.service.name
}

output "task_role_arn" {
  description = "IAM role ARN used by the application container for Bedrock and Textract."
  value       = aws_iam_role.task.arn
}

output "certificate_arn" {
  description = "ACM certificate ARN selected for the HTTPS listener."
  value       = local.listener_certificate_arn
}

output "database_endpoint" {
  description = "RDS PostgreSQL endpoint hostname."
  value       = local.active_db_host
}

output "database_port" {
  description = "RDS PostgreSQL port."
  value       = local.active_db_port
}

output "database_publicly_accessible" {
  description = "Whether the RDS instance is publicly reachable."
  value       = local.active_db_public
}

output "database_name" {
  description = "Application database name."
  value       = local.active_db_name
}

output "database_secret_arn" {
  description = "Secrets Manager ARN containing the application database connection payload."
  value       = aws_secretsmanager_secret.database.arn
}

output "db_bastion_public_ip" {
  description = "Public IP of the temporary DB bastion when enabled."
  value       = try(aws_instance.db_bastion[0].public_ip, null)
}

output "db_bastion_instance_id" {
  description = "EC2 instance ID of the DB bastion when enabled."
  value       = try(aws_instance.db_bastion[0].id, null)
}

output "db_bastion_ssm_port_forward_command" {
  description = "AWS CLI command to start a local port forward to PostgreSQL through Session Manager."
  value       = try("aws ssm start-session --target ${aws_instance.db_bastion[0].id} --document-name AWS-StartPortForwardingSessionToRemoteHost --parameters host=${aws_db_instance.postgres.address},portNumber=5432,localPortNumber=15432", null)
}

output "database_private_endpoint" {
  description = "Original private RDS endpoint hostname."
  value       = aws_db_instance.postgres.address
}

output "database_public_clone_endpoint" {
  description = "Public clone RDS endpoint hostname when direct local access is enabled."
  value       = try(aws_db_instance.postgres_public[0].address, null)
}

output "acm_validation_records" {
  description = "DNS validation records to create manually in GoDaddy when using the managed ACM certificate."
  value = local.create_acm_certificate ? [
    for option in aws_acm_certificate.service[0].domain_validation_options : {
      domain_name  = option.domain_name
      record_name  = option.resource_record_name
      record_type  = option.resource_record_type
      record_value = option.resource_record_value
    }
  ] : []
}
