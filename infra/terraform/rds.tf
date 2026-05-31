# =============================================================================
# RDS — Managed PostgreSQL Database
# =============================================================================
# Amazon RDS (Relational Database Service) runs PostgreSQL for you.
# AWS handles: backups, patching, monitoring, failover, storage scaling.
#
# Why RDS over running PostgreSQL on EC2?
#   Self-managed: you handle backups, OS patches, HA setup, storage
#   RDS:          AWS handles all of that — you just connect and query
#
# RDS components:
#   Instance: the virtual server running PostgreSQL
#   Parameter group: database configuration (like postgresql.conf)
#   Subnet group: which subnets it can use (created in vpc.tf)
#   Snapshot: automatic backups (point-in-time recovery)
# =============================================================================

# ── Random password for RDS ───────────────────────────────────────────────────
# Never hardcode database passwords. Generate them with Terraform
# and store them in AWS Secrets Manager automatically.
resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%^&*()-_=+[]{}|;:,.<>?"
}

# ── Store DB password in Secrets Manager ──────────────────────────────────────
# ECS tasks read credentials from Secrets Manager at runtime.
# No secrets in environment variables, no secrets in code.
resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${var.app_name}/db-password"
  description             = "RDS PostgreSQL password for finance-calculator"
  recovery_window_in_days = 7  # 7-day recovery window before permanent deletion
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id = aws_secretsmanager_secret.db_password.id
  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db_password.result
    host     = aws_db_instance.main.address
    port     = 5432
    dbname   = var.db_name
    url      = "postgresql+asyncpg://${var.db_username}:${random_password.db_password.result}@${aws_db_instance.main.address}:5432/${var.db_name}"
  })
}

# ── RDS Parameter Group ───────────────────────────────────────────────────────
# Tune PostgreSQL settings for our workload.
resource "aws_db_parameter_group" "main" {
  family = "postgres16"
  name   = "${var.app_name}-pg16-params"

  parameter {
    name  = "log_connections"
    value = "1"  # Log every new connection (useful for debugging connection pool issues)
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"  # Log queries slower than 1 second (slow query log)
  }

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"  # Enable query statistics extension
  }
}

# ── RDS Instance ─────────────────────────────────────────────────────────────
resource "aws_db_instance" "main" {
  identifier = "${var.app_name}-postgres"

  # ── Engine ────────────────────────────────────────────────────────────────
  engine               = "postgres"
  engine_version       = "16.3"
  instance_class       = var.db_instance_class
  parameter_group_name = aws_db_parameter_group.main.name

  # ── Database ──────────────────────────────────────────────────────────────
  db_name  = var.db_name
  username = var.db_username
  password = random_password.db_password.result

  # ── Storage ───────────────────────────────────────────────────────────────
  # gp3 = latest generation SSD (faster + cheaper than gp2)
  # autoscaling: automatically grows storage when >10% free space left
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = 100  # Auto-scale storage up to 100GB
  storage_type          = "gp3"
  storage_encrypted     = true  # Encrypt data at rest (compliance requirement)

  # ── High Availability ─────────────────────────────────────────────────────
  # Multi-AZ: AWS maintains a standby replica in another AZ.
  # On primary failure: automatic failover in ~60 seconds (no manual action).
  multi_az = var.db_multi_az

  # ── Networking ────────────────────────────────────────────────────────────
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false  # NEVER expose DB to internet

  # ── Backups ───────────────────────────────────────────────────────────────
  # AWS automatically creates daily snapshots and keeps them for 7 days.
  # You can restore to any point within the backup window.
  backup_retention_period = 7
  backup_window           = "03:00-04:00"  # UTC — low traffic window

  # ── Maintenance ───────────────────────────────────────────────────────────
  maintenance_window         = "Mon:04:00-Mon:05:00"  # After backup window
  auto_minor_version_upgrade = true  # Auto-apply minor patches (16.3 → 16.4)

  # ── Deletion Protection ───────────────────────────────────────────────────
  # Prevents accidental `terraform destroy` from wiping your database.
  # Set to false ONLY when you intentionally want to delete.
  deletion_protection = true
  skip_final_snapshot = false  # Take a final snapshot before deletion
  final_snapshot_identifier = "${var.app_name}-final-snapshot"

  tags = { Name = "${var.app_name}-postgres" }
}
