# =============================================================================
# OUTPUTS — Values printed after `terraform apply`
# =============================================================================
# Outputs are like return values from your infrastructure.
# After applying, these values appear in the terminal.
# Other Terraform modules can also reference these values.
# =============================================================================

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "alb_dns_name" {
  description = "ALB DNS name — point your domain's CNAME to this"
  value       = aws_lb.main.dns_name
}

output "ecr_repository_url" {
  description = "ECR URL — use this in CI/CD: docker push <this-url>:tag"
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name — use in cd-staging.yml / cd-production.yml"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.app.name
}

output "rds_endpoint" {
  description = "RDS endpoint — app reads this from Secrets Manager at runtime"
  value       = aws_db_instance.main.address
  sensitive   = true
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint"
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
  sensitive   = true
}

output "s3_bucket_name" {
  description = "S3 bucket for exports and ALB logs"
  value       = aws_s3_bucket.app.id
}

output "db_secret_arn" {
  description = "Secrets Manager ARN for DB credentials — reference in ECS task"
  value       = aws_secretsmanager_secret.db_password.arn
}

output "app_secrets_arn" {
  description = "Secrets Manager ARN for JWT + Redis secrets"
  value       = aws_secretsmanager_secret.app_secrets.arn
}

output "next_steps" {
  description = "What to do after terraform apply"
  value       = <<-EOT

    ✅ Infrastructure created! Next steps:

    1. Point your domain to the ALB:
       Add CNAME record: ${var.domain_name} → ${aws_lb.main.dns_name}

    2. Push your Docker image to ECR:
       aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${aws_ecr_repository.app.repository_url}
       docker build -t ${aws_ecr_repository.app.repository_url}:latest ./backend
       docker push ${aws_ecr_repository.app.repository_url}:latest

    3. Run database migrations:
       aws ecs run-task \
         --cluster ${aws_ecs_cluster.main.name} \
         --task-definition ${var.app_name} \
         --launch-type FARGATE \
         --network-configuration "awsvpcConfiguration={subnets=[${aws_subnet.private[0].id}],securityGroups=[${aws_security_group.ecs.id}]}" \
         --overrides '{"containerOverrides":[{"name":"finance-app","command":["/opt/venv/bin/alembic","upgrade","head"]}]}'

    4. Update GitHub Secrets for CI/CD:
       ECR_REGISTRY    = ${split("/", aws_ecr_repository.app.repository_url)[0]}
       ECR_REPOSITORY  = ${var.app_name}
       ECS_CLUSTER     = ${aws_ecs_cluster.main.name}
       ECS_SERVICE     = ${aws_ecs_service.app.name}
  EOT
}
