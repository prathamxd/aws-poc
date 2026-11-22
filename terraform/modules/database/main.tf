resource "aws_db_subnet_group" "main" {
  name        = "${var.name_prefix}-db-subnets"
  description = "Private subnets for TicketDesk RDS"
  subnet_ids  = var.private_subnet_ids

  tags = {
    Name = "${var.name_prefix}-db-subnets"
  }
}

resource "aws_db_instance" "main" {
  identifier     = "${var.name_prefix}-db"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class
  port           = 5432

  allocated_storage = var.allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.master_username

  # RDS generates the password and stores it in Secrets Manager.
  # It never appears in code, variables or user data.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.db_security_group_id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period    = var.backup_retention_days
  backup_window              = "18:00-18:30"
  maintenance_window         = "sun:19:00-sun:19:30"
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true
  apply_immediately          = true

  # POC settings so `terraform destroy` removes everything cleanly
  deletion_protection = false
  skip_final_snapshot = true

  tags = {
    Name = "${var.name_prefix}-db"
  }
}
