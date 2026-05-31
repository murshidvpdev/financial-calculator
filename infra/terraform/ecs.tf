# =============================================================================
# ECS — Elastic Container Service (runs Docker containers on AWS)
# =============================================================================
# ECS is AWS's container orchestration service — similar to Kubernetes but
# managed by AWS (no control plane to maintain).
#
# ECS concepts:
#   Cluster:         logical grouping of tasks/services
#   Task Definition: blueprint for a container (image, CPU, memory, env vars)
#   Task:            a running instance of a task definition (like a Pod)
#   Service:         keeps N tasks running, integrates with ALB, handles rolling deploys
#
# ECS launch types:
#   EC2:     you manage the EC2 instances (more control, more work)
#   Fargate: AWS manages the servers (serverless containers) ← we use this
#
# Fargate pricing: pay per task CPU + memory per second (no idle server costs)
# =============================================================================

# ── ECR Repository — stores your Docker images ────────────────────────────────
resource "aws_ecr_repository" "app" {
  name                 = var.app_name
  image_tag_mutability = "MUTABLE"  # Allow overwriting tags (needed for :latest)

  # Scan every pushed image for known CVEs (security vulnerabilities)
  image_scanning_configuration {
    scan_on_push = true
  }

  # Encrypt images at rest using AWS-managed keys
  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = { Name = var.app_name }
}

# ECR lifecycle policy: keep only the last 10 images to control storage costs
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ── IAM Roles ─────────────────────────────────────────────────────────────────
# ECS needs two IAM roles:
#   Execution role: ECS agent uses this to pull images + write logs
#   Task role:      your app code uses this to call other AWS services (S3, Secrets Manager)

resource "aws_iam_role" "ecs_execution" {
  name = "${var.app_name}-ecs-execution-role"

  # Trust policy: who can assume this role
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# AWS-managed policy that grants ECS the minimum permissions it needs
resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Allow ECS to read secrets from Secrets Manager (for DB password, JWT key)
resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "${var.app_name}-secrets-policy"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "kms:Decrypt"
      ]
      Resource = [
        aws_secretsmanager_secret.db_password.arn,
        aws_secretsmanager_secret.app_secrets.arn,
      ]
    }]
  })
}

# Task role: permissions your app code has at runtime
resource "aws_iam_role" "ecs_task" {
  name = "${var.app_name}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# App needs S3 access (for file exports, imports)
resource "aws_iam_role_policy" "ecs_task_s3" {
  name = "${var.app_name}-task-s3-policy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.app.arn,
        "${aws_s3_bucket.app.arn}/*"
      ]
    }]
  })
}

# ── App Secrets in Secrets Manager ────────────────────────────────────────────
resource "random_password" "jwt_secret" {
  length  = 64
  special = false  # JWT secrets should be alphanumeric for safety
}

resource "aws_secretsmanager_secret" "app_secrets" {
  name                    = "${var.app_name}/app-secrets"
  description             = "JWT key and other app secrets"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "app_secrets" {
  secret_id = aws_secretsmanager_secret.app_secrets.id
  secret_string = jsonencode({
    JWT_SECRET_KEY = random_password.jwt_secret.result
    REDIS_PASSWORD = random_password.redis_password.result
  })
}

resource "random_password" "redis_password" {
  length  = 32
  special = false
}

# ── CloudWatch Log Group ──────────────────────────────────────────────────────
# ECS sends container stdout/stderr here. Retain for 30 days.
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.app_name}"
  retention_in_days = 30
}

# ── ECS Cluster ───────────────────────────────────────────────────────────────
resource "aws_ecs_cluster" "main" {
  name = "${var.app_name}-cluster"

  # Container Insights: detailed CloudWatch metrics per task (CPU, memory, network)
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ── ECS Task Definition ───────────────────────────────────────────────────────
# A task definition is a JSON blueprint that describes what to run.
# It's like a docker-compose.yml but for ECS.
resource "aws_ecs_task_definition" "app" {
  family                   = var.app_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"  # Required for Fargate; each task gets its own ENI + IP
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "finance-app"
      image = "${aws_ecr_repository.app.repository_url}:${var.ecr_image_tag}"

      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]

      # Environment variables from ConfigMap equivalent
      environment = [
        { name = "APP_ENV",   value = var.environment },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "LOG_FORMAT", value = "json" },
        { name = "HOST",      value = "0.0.0.0" },
        { name = "PORT",      value = "8000" },
        { name = "REDIS_HOST", value = aws_elasticache_cluster.redis.cache_nodes[0].address },
        { name = "REDIS_PORT", value = "6379" },
        { name = "CORS_ORIGINS", value = "https://${var.domain_name}" },
      ]

      # Secrets injected from Secrets Manager at container start
      # Much safer than env vars — secrets never appear in task definition plaintext
      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = "${aws_secretsmanager_secret_version.db_password.arn}:url::"
        },
        {
          name      = "JWT_SECRET_KEY"
          valueFrom = "${aws_secretsmanager_secret_version.app_secrets.arn}:JWT_SECRET_KEY::"
        },
        {
          name      = "REDIS_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret_version.app_secrets.arn}:REDIS_PASSWORD::"
        },
      ]

      # Send logs to CloudWatch
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.app.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }

      # Health check — ECS restarts task if this fails 3 times
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/api/v1/health/live || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    }
  ])
}

# ── ALB — Application Load Balancer ──────────────────────────────────────────
resource "aws_lb" "main" {
  name               = "${var.app_name}-alb"
  internal           = false  # Internet-facing
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  # Access logs to S3 (track every request for compliance/debugging)
  access_logs {
    bucket  = aws_s3_bucket.app.id
    prefix  = "alb-logs"
    enabled = true
  }

  tags = { Name = "${var.app_name}-alb" }
}

# Target group: where ALB sends traffic (our ECS tasks)
resource "aws_lb_target_group" "app" {
  name        = "${var.app_name}-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"  # Required for Fargate (tasks get IPs directly)

  health_check {
    enabled             = true
    path                = "/api/v1/health/ready"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  # Deregistration delay: give tasks 30s to finish in-flight requests before removal
  deregistration_delay = 30
}

# HTTP listener: redirect all HTTP → HTTPS
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# HTTPS listener: forward to ECS target group
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"  # Modern TLS only
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# ── ECS Service ───────────────────────────────────────────────────────────────
# A Service keeps N tasks running and handles rolling deployments.
resource "aws_ecs_service" "app" {
  name            = "${var.app_name}-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.ecs_desired_count
  launch_type     = "FARGATE"

  # Rolling update: same strategy as Kubernetes Deployment
  deployment_minimum_healthy_percent = 50   # Keep 1 task running during deploy
  deployment_maximum_percent         = 200  # Allow double tasks during deploy

  # Circuit breaker: auto-rollback if deployment fails
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false  # Private subnet, use NAT for outbound
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "finance-app"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.https]
}

# ── Auto Scaling ──────────────────────────────────────────────────────────────
resource "aws_appautoscaling_target" "ecs" {
  max_capacity       = var.ecs_max_count
  min_capacity       = var.ecs_min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.app.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# Scale up when CPU > 70%
resource "aws_appautoscaling_policy" "cpu" {
  name               = "${var.app_name}-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300  # 5 min before scaling down
    scale_out_cooldown = 60   # 1 min before scaling up
  }
}
