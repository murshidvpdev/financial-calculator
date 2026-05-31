# =============================================================================
# VARIABLES — Input parameters for the infrastructure
# =============================================================================
# Variables make Terraform reusable across environments (staging, production).
# Values are set in terraform.tfvars (not committed) or via -var flags.
#
# Variable types: string, number, bool, list, map, object
# =============================================================================

# ── Project ───────────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region to deploy all resources into"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment — controls naming and sizing"
  type        = string
  default     = "production"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "Environment must be 'staging' or 'production'."
  }
}

variable "app_name" {
  description = "Application name — used as prefix for all resource names"
  type        = string
  default     = "finance-calculator"
}

# ── Networking ────────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the VPC (e.g. 10.0.0.0/16 gives 65,536 IPs)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "AZs to deploy into — 2 minimum for high availability"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

# ── ECR / Docker ──────────────────────────────────────────────────────────────

variable "ecr_image_tag" {
  description = "Docker image tag to deploy (set by CI/CD pipeline)"
  type        = string
  default     = "latest"
}

# ── ECS ──────────────────────────────────────────────────────────────────────

variable "ecs_task_cpu" {
  description = "CPU units for ECS task (1024 = 1 vCPU)"
  type        = number
  default     = 512  # 0.5 vCPU — enough for FastAPI app
}

variable "ecs_task_memory" {
  description = "Memory (MB) for ECS task"
  type        = number
  default     = 1024  # 1 GB
}

variable "ecs_desired_count" {
  description = "Number of ECS tasks to run"
  type        = number
  default     = 2  # Minimum 2 for HA across AZs
}

variable "ecs_min_count" {
  description = "Minimum tasks for auto-scaling"
  type        = number
  default     = 2
}

variable "ecs_max_count" {
  description = "Maximum tasks for auto-scaling"
  type        = number
  default     = 10
}

# ── RDS PostgreSQL ────────────────────────────────────────────────────────────

variable "db_instance_class" {
  description = "RDS instance type (db.t3.micro = cheapest, db.r6g.large = production)"
  type        = string
  default     = "db.t3.micro"
}

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "finance_db"
}

variable "db_username" {
  description = "PostgreSQL master username"
  type        = string
  default     = "finance_user"
}

variable "db_allocated_storage" {
  description = "RDS storage in GB (gp3 minimum is 20GB)"
  type        = number
  default     = 20
}

variable "db_multi_az" {
  description = "Enable Multi-AZ for RDS (automatic failover, ~2× cost)"
  type        = bool
  default     = false  # Set true in production after launch
}

# ── ElastiCache Redis ─────────────────────────────────────────────────────────

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t3.micro"
}

# ── Domain ────────────────────────────────────────────────────────────────────

variable "domain_name" {
  description = "Your domain name (e.g. finance.yourdomain.com)"
  type        = string
  default     = "finance.yourdomain.com"
}

variable "certificate_arn" {
  description = "ACM certificate ARN for HTTPS (create manually in AWS Console)"
  type        = string
  default     = ""  # Fill in after creating cert in ACM
}
