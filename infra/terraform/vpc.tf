# =============================================================================
# VPC — Virtual Private Cloud (your private network on AWS)
# =============================================================================
# A VPC is an isolated network inside AWS — like having your own datacenter.
# Everything you create (EC2, RDS, ECS) lives inside a VPC.
#
# Subnet architecture (3-tier):
#
#   Internet
#      │
#   IGW (Internet Gateway) — door to the internet
#      │
#   ┌──────────────────────────────────────────────────────┐
#   │  PUBLIC subnets (10.0.0.x, 10.0.1.x, 10.0.2.x)     │
#   │  • Application Load Balancer (faces internet)        │
#   │  • NAT Gateway (lets private subnets reach internet) │
#   └──────────────────────────────────────────────────────┘
#      │ (via NAT)
#   ┌──────────────────────────────────────────────────────┐
#   │  PRIVATE subnets (10.0.10.x, 10.0.11.x, 10.0.12.x) │
#   │  • ECS tasks (app containers) — NO direct internet   │
#   │  • Traffic comes in via ALB only                     │
#   └──────────────────────────────────────────────────────┘
#      │ (app talks to DB)
#   ┌──────────────────────────────────────────────────────┐
#   │  DATABASE subnets (10.0.20.x, 10.0.21.x, 10.0.22.x)│
#   │  • RDS PostgreSQL — not reachable from internet      │
#   │  • ElastiCache Redis — not reachable from internet   │
#   └──────────────────────────────────────────────────────┘
#
# Why 3 AZs?
#   If one AWS availability zone goes down (rare but happens), traffic
#   automatically shifts to the other 2. No downtime.
# =============================================================================

# ── VPC ───────────────────────────────────────────────────────────────────────
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true  # Allows EC2/RDS instances to get DNS names
  enable_dns_support   = true

  tags = { Name = "${var.app_name}-vpc" }
}

# ── Internet Gateway ──────────────────────────────────────────────────────────
# The IGW is the door between your VPC and the internet.
# Without it, nothing in your VPC can reach the internet (or be reached).
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.app_name}-igw" }
}

# ── PUBLIC Subnets ────────────────────────────────────────────────────────────
# One per AZ. The ALB and NAT Gateways live here.
resource "aws_subnet" "public" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)  # 10.0.0.0/24, 10.0.1.0/24, 10.0.2.0/24
  availability_zone = var.availability_zones[count.index]

  # Resources launched here get a public IP automatically
  map_public_ip_on_launch = true

  tags = { Name = "${var.app_name}-public-${var.availability_zones[count.index]}" }
}

# ── PRIVATE Subnets ───────────────────────────────────────────────────────────
# ECS tasks run here — no direct internet access, but can reach internet via NAT.
resource "aws_subnet" "private" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)  # 10.0.10.0/24, 10.0.11.0/24, 10.0.12.0/24
  availability_zone = var.availability_zones[count.index]

  tags = { Name = "${var.app_name}-private-${var.availability_zones[count.index]}" }
}

# ── DATABASE Subnets ──────────────────────────────────────────────────────────
# RDS + ElastiCache. Isolated, no outbound internet.
resource "aws_subnet" "database" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 20)  # 10.0.20.0/24, 10.0.21.0/24, 10.0.22.0/24
  availability_zone = var.availability_zones[count.index]

  tags = { Name = "${var.app_name}-database-${var.availability_zones[count.index]}" }
}

# ── NAT Gateway ───────────────────────────────────────────────────────────────
# Lets private subnet resources reach the internet (for pulling Docker images,
# calling external APIs) WITHOUT being reachable FROM the internet.
# One NAT per AZ for resilience (if an AZ dies, other AZs still have NAT).
#
# Cost note: NAT Gateways are ~$32/month EACH. For dev/staging, use 1 NAT only.
resource "aws_eip" "nat" {
  count  = length(var.availability_zones)
  domain = "vpc"
  tags   = { Name = "${var.app_name}-nat-eip-${count.index}" }
}

resource "aws_nat_gateway" "main" {
  count         = length(var.availability_zones)
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id  # NAT lives in PUBLIC subnet

  tags = { Name = "${var.app_name}-nat-${var.availability_zones[count.index]}" }

  depends_on = [aws_internet_gateway.main]
}

# ── Route Tables ──────────────────────────────────────────────────────────────
# A route table tells traffic WHERE to go based on its destination.

# Public route table: all internet traffic → IGW
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.app_name}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = length(var.availability_zones)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Private route tables: internet traffic → NAT Gateway (one per AZ)
resource "aws_route_table" "private" {
  count  = length(var.availability_zones)
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }

  tags = { Name = "${var.app_name}-private-rt-${var.availability_zones[count.index]}" }
}

resource "aws_route_table_association" "private" {
  count          = length(var.availability_zones)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# Database subnets: no internet route (fully isolated)
resource "aws_route_table" "database" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.app_name}-database-rt" }
}

resource "aws_route_table_association" "database" {
  count          = length(var.availability_zones)
  subnet_id      = aws_subnet.database[count.index].id
  route_table_id = aws_route_table.database.id
}

# ── DB Subnet Group ───────────────────────────────────────────────────────────
# RDS requires a "subnet group" — a named collection of subnets it can use.
resource "aws_db_subnet_group" "main" {
  name       = "${var.app_name}-db-subnet-group"
  subnet_ids = aws_subnet.database[*].id
  tags       = { Name = "${var.app_name}-db-subnet-group" }
}

# ── ElastiCache Subnet Group ──────────────────────────────────────────────────
resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.app_name}-cache-subnet-group"
  subnet_ids = aws_subnet.database[*].id
}

# ── Security Groups ───────────────────────────────────────────────────────────
# A security group is a stateful firewall — controls inbound + outbound traffic.
# "Stateful" means: if you allow inbound traffic, the response is automatically allowed out.

# ALB security group: internet → ALB (HTTP/HTTPS only)
resource "aws_security_group" "alb" {
  name        = "${var.app_name}-alb-sg"
  description = "Allow HTTP/HTTPS from internet to ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.app_name}-alb-sg" }
}

# ECS security group: ALB → ECS (port 8000 only)
resource "aws_security_group" "ecs" {
  name        = "${var.app_name}-ecs-sg"
  description = "Allow traffic from ALB to ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "App port from ALB only"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All outbound (for DB, Redis, ECR, internet)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.app_name}-ecs-sg" }
}

# RDS security group: ECS → RDS (PostgreSQL port 5432 only)
resource "aws_security_group" "rds" {
  name        = "${var.app_name}-rds-sg"
  description = "Allow PostgreSQL from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from ECS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  tags = { Name = "${var.app_name}-rds-sg" }
}

# Redis security group: ECS → Redis (port 6379 only)
resource "aws_security_group" "redis" {
  name        = "${var.app_name}-redis-sg"
  description = "Allow Redis from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from ECS"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  tags = { Name = "${var.app_name}-redis-sg" }
}
