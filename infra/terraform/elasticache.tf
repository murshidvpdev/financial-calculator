# =============================================================================
# ELASTICACHE — Managed Redis (caching + sessions)
# =============================================================================
# ElastiCache runs Redis for you — same as RDS but for Redis.
# Used in this app for: JWT token blacklist, rate limiting, session cache.
# =============================================================================

resource "aws_elasticache_cluster" "redis" {
  cluster_id      = "${var.app_name}-redis"
  engine          = "redis"
  node_type       = var.redis_node_type
  num_cache_nodes = 1  # Single node (for Multi-AZ use replication group)
  port            = 6379

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  # Automatically apply minor version updates
  auto_minor_version_upgrade = true

  # Daily backup at low-traffic time
  snapshot_window          = "02:00-03:00"
  snapshot_retention_limit = 3  # Keep 3 days of backups

  tags = { Name = "${var.app_name}-redis" }
}
