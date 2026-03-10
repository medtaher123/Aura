resource "aws_db_subnet_group" "this" {
  count = var.enabled ? 1 : 0

  name       = "${var.project_name}-postgis-subnet-group"
  subnet_ids = var.subnet_ids

  tags = {
    Name        = "${var.project_name}-postgis-subnet-group"
    Environment = var.environment
  }
}

resource "aws_security_group" "this" {
  count = var.enabled ? 1 : 0

  name        = "${var.project_name}-postgis-sg"
  description = "PostGIS security group"
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = var.allowed_security_group_ids
    content {
      description     = "PostgreSQL from trusted service SG"
      from_port       = 5432
      to_port         = 5432
      protocol        = "tcp"
      security_groups = [ingress.value]
    }
  }

  egress {
    description = "Allow outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-postgis-sg"
    Environment = var.environment
  }
}

resource "aws_db_instance" "this" {
  count = var.enabled ? 1 : 0

  identifier                      = "${var.project_name}-postgis"
  engine                          = "postgres"
  engine_version                  = "16.4"
  instance_class                  = var.instance_class
  db_name                         = var.db_name
  username                        = var.master_username
  manage_master_user_password     = true
  allocated_storage               = var.allocated_storage
  max_allocated_storage           = var.max_allocated_storage
  storage_type                    = "gp3"
  auto_minor_version_upgrade      = true
  backup_retention_period         = var.backup_retention_period
  multi_az                        = var.multi_az
  db_subnet_group_name            = aws_db_subnet_group.this[0].name
  vpc_security_group_ids          = [aws_security_group.this[0].id]
  deletion_protection             = var.deletion_protection
  publicly_accessible             = false
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${var.project_name}-postgis-final-snapshot"
  delete_automated_backups        = true
  performance_insights_enabled    = true
  enabled_cloudwatch_logs_exports = ["postgresql"]

  tags = {
    Name        = "${var.project_name}-postgis"
    Environment = var.environment
  }
}

