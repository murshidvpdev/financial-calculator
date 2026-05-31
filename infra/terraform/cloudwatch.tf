# =============================================================================
# CLOUDWATCH — Monitoring, Alerting, Dashboards
# =============================================================================
# CloudWatch is AWS's observability service.
# Three pillars of observability:
#   Logs    → what happened (structured JSON from structlog)
#   Metrics → how much / how fast (CPU, memory, request count, latency)
#   Alarms  → alert when something is wrong (SNS → email/Slack)
#
# Every AWS service automatically sends metrics to CloudWatch.
# We add custom alarms + a dashboard on top.
# =============================================================================

# ── SNS Topic — alert delivery channel ───────────────────────────────────────
# SNS (Simple Notification Service) delivers alerts to email, Slack, PagerDuty.
# CloudWatch alarms → SNS topic → subscribers (email)
resource "aws_sns_topic" "alerts" {
  name = "${var.app_name}-alerts"
  tags = { Name = "${var.app_name}-alerts" }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "murshidveypey790@gmail.com"
  # After apply: check email and click "Confirm subscription"
}

# ── ECS Alarms ────────────────────────────────────────────────────────────────

# Alert when CPU stays above 80% for 5 minutes
resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  alarm_name          = "${var.app_name}-ecs-cpu-high"
  alarm_description   = "ECS CPU above 80% for 5 minutes — consider scaling up"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3        # 3 consecutive periods
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60       # 1-minute periods
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.app.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# Alert when memory stays above 85%
resource "aws_cloudwatch_metric_alarm" "ecs_memory_high" {
  alarm_name          = "${var.app_name}-ecs-memory-high"
  alarm_description   = "ECS memory above 85% — potential memory leak"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.app.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Alert when running task count drops below desired (tasks are crashing)
resource "aws_cloudwatch_metric_alarm" "ecs_tasks_low" {
  alarm_name          = "${var.app_name}-ecs-tasks-low"
  alarm_description   = "Running ECS tasks below desired count — tasks may be crashing"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "RunningTaskCount"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = var.ecs_min_count
  treat_missing_data  = "breaching"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.app.name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# ── ALB Alarms ────────────────────────────────────────────────────────────────

# Alert when 5xx error rate exceeds 5%
resource "aws_cloudwatch_metric_alarm" "alb_5xx_high" {
  alarm_name          = "${var.app_name}-alb-5xx-high"
  alarm_description   = "ALB 5xx error rate above 5% — app is returning server errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 5
  treat_missing_data  = "notBreaching"

  # Use a metric math expression: (5xx / total requests) × 100
  metric_query {
    id          = "error_rate"
    expression  = "(errors / requests) * 100"
    label       = "5xx Error Rate %"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      metric_name = "HTTPCode_Target_5XX_Count"
      namespace   = "AWS/ApplicationELB"
      period      = 60
      stat        = "Sum"
      dimensions  = { LoadBalancer = aws_lb.main.arn_suffix }
    }
  }

  metric_query {
    id = "requests"
    metric {
      metric_name = "RequestCount"
      namespace   = "AWS/ApplicationELB"
      period      = 60
      stat        = "Sum"
      dimensions  = { LoadBalancer = aws_lb.main.arn_suffix }
    }
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Alert when p99 response time exceeds 3 seconds
resource "aws_cloudwatch_metric_alarm" "alb_latency_high" {
  alarm_name          = "${var.app_name}-alb-latency-high"
  alarm_description   = "ALB p99 latency above 3s — app is slow"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p99"
  threshold           = 3
  treat_missing_data  = "notBreaching"

  dimensions = { LoadBalancer = aws_lb.main.arn_suffix }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# ── RDS Alarms ────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  alarm_name          = "${var.app_name}-rds-cpu-high"
  alarm_description   = "RDS CPU above 80% — queries may need optimization"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"

  dimensions = { DBInstanceIdentifier = aws_db_instance.main.id }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Alert when free storage drops below 5GB
resource "aws_cloudwatch_metric_alarm" "rds_storage_low" {
  alarm_name          = "${var.app_name}-rds-storage-low"
  alarm_description   = "RDS free storage below 5GB — add storage soon"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 5 * 1024 * 1024 * 1024  # 5GB in bytes
  treat_missing_data  = "notBreaching"

  dimensions = { DBInstanceIdentifier = aws_db_instance.main.id }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# Alert when DB connections exceed 80% of max
resource "aws_cloudwatch_metric_alarm" "rds_connections_high" {
  alarm_name          = "${var.app_name}-rds-connections-high"
  alarm_description   = "RDS connections above 80 — connection pool may be exhausted"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 80  # db.t3.micro max_connections ≈ 100
  treat_missing_data  = "notBreaching"

  dimensions = { DBInstanceIdentifier = aws_db_instance.main.id }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# ── CloudWatch Dashboard ───────────────────────────────────────────────────────
# A single-pane-of-glass view of all key metrics.
# Access: AWS Console → CloudWatch → Dashboards → finance-calculator
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = var.app_name

  dashboard_body = jsonencode({
    widgets = [
      # ── Row 1: ECS ───────────────────────────────────────────────────────
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 8
        height = 6
        properties = {
          title  = "ECS CPU Utilization %"
          view   = "timeSeries"
          period = 60
          stat   = "Average"
          metrics = [[
            "AWS/ECS", "CPUUtilization",
            "ClusterName", aws_ecs_cluster.main.name,
            "ServiceName", aws_ecs_service.app.name
          ]]
          annotations = { horizontal = [{ value = 80, label = "Alert threshold", color = "#ff0000" }] }
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 0
        width  = 8
        height = 6
        properties = {
          title  = "ECS Memory Utilization %"
          view   = "timeSeries"
          period = 60
          stat   = "Average"
          metrics = [[
            "AWS/ECS", "MemoryUtilization",
            "ClusterName", aws_ecs_cluster.main.name,
            "ServiceName", aws_ecs_service.app.name
          ]]
          annotations = { horizontal = [{ value = 85, label = "Alert threshold", color = "#ff0000" }] }
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 0
        width  = 8
        height = 6
        properties = {
          title   = "ECS Running Task Count"
          view    = "timeSeries"
          period  = 60
          stat    = "Average"
          metrics = [["AWS/ECS", "RunningTaskCount", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.app.name]]
        }
      },
      # ── Row 2: ALB ───────────────────────────────────────────────────────
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "ALB Request Count"
          view   = "timeSeries"
          period = 60
          stat   = "Sum"
          metrics = [["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.main.arn_suffix]]
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "ALB Response Time p99 (seconds)"
          view   = "timeSeries"
          period = 60
          metrics = [["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix, { stat = "p99" }]]
          annotations = { horizontal = [{ value = 3, label = "SLA threshold", color = "#ff0000" }] }
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "ALB HTTP 5xx Errors"
          view   = "timeSeries"
          period = 60
          stat   = "Sum"
          metrics = [["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", aws_lb.main.arn_suffix]]
        }
      },
      # ── Row 3: RDS ───────────────────────────────────────────────────────
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 8
        height = 6
        properties = {
          title   = "RDS CPU %"
          view    = "timeSeries"
          period  = 60
          stat    = "Average"
          metrics = [["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.main.id]]
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 12
        width  = 8
        height = 6
        properties = {
          title   = "RDS DB Connections"
          view    = "timeSeries"
          period  = 60
          stat    = "Average"
          metrics = [["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", aws_db_instance.main.id]]
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 12
        width  = 8
        height = 6
        properties = {
          title   = "RDS Free Storage (GB)"
          view    = "timeSeries"
          period  = 300
          stat    = "Average"
          metrics = [["AWS/RDS", "FreeStorageSpace", "DBInstanceIdentifier", aws_db_instance.main.id]]
        }
      },
    ]
  })
}
