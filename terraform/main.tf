data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  account_id  = data.aws_caller_identity.current.account_id
}

# VPC, public/private subnets, routing, security groups
module "network" {
  source = "./modules/network"

  name_prefix        = local.name_prefix
  aws_region         = var.aws_region
  vpc_cidr           = var.vpc_cidr
  allowed_http_cidrs = var.allowed_http_cidrs
}

# Private S3 bucket for ticket attachments
module "storage" {
  source = "./modules/storage"

  name_prefix = local.name_prefix
  account_id  = local.account_id
  aws_region  = var.aws_region
}

# Application secrets (session key + initial admin password) in Secrets Manager
module "secrets" {
  source = "./modules/secrets"

  name_prefix = local.name_prefix
}

# Private Amazon RDS PostgreSQL (password managed by RDS in Secrets Manager)
module "database" {
  source = "./modules/database"

  name_prefix           = local.name_prefix
  private_subnet_ids    = module.network.private_subnet_ids
  db_security_group_id  = module.network.db_security_group_id
  instance_class        = var.db_instance_class
  engine_version        = var.db_engine_version
  allocated_storage     = var.db_allocated_storage
  backup_retention_days = var.db_backup_retention_days
}

# Lambda triggered by S3 ObjectCreated events on attachments/
module "lambda" {
  source = "./modules/lambda"

  name_prefix        = local.name_prefix
  account_id         = local.account_id
  bucket_name        = module.storage.bucket_name
  bucket_arn         = module.storage.bucket_arn
  source_dir         = "${path.root}/../lambda/file_processor"
  allowed_extensions = var.allowed_extensions
  max_upload_mb      = var.max_upload_mb
  log_retention_days = var.log_retention_days
}

# ECR repository, EC2 instance running the container, its IAM role and log group
module "compute" {
  source = "./modules/compute"

  name_prefix           = local.name_prefix
  aws_region            = var.aws_region
  instance_type         = var.instance_type
  subnet_id             = module.network.public_subnet_ids[0]
  app_security_group_id = module.network.app_security_group_id
  bucket_name           = module.storage.bucket_name
  bucket_arn            = module.storage.bucket_arn
  db_host               = module.database.address
  db_port               = module.database.port
  db_name               = module.database.db_name
  db_secret_arn         = module.database.master_user_secret_arn
  app_secret_arn        = module.secrets.app_secret_arn
  allowed_extensions    = var.allowed_extensions
  max_upload_mb         = var.max_upload_mb
  log_retention_days    = var.log_retention_days
}

# GitHub Actions OIDC deploy role (only when github_repository is set)
module "cicd" {
  source = "./modules/cicd"
  count  = var.github_repository == "" ? 0 : 1

  name_prefix          = local.name_prefix
  aws_region           = var.aws_region
  github_repository    = var.github_repository
  create_oidc_provider = var.create_github_oidc_provider
  ecr_repository_arn   = module.compute.ecr_repository_arn
  ec2_instance_arn     = module.compute.instance_arn
}

# CloudWatch alarms, metric filters, SNS topic and dashboard
module "monitoring" {
  source = "./modules/monitoring"

  name_prefix          = local.name_prefix
  aws_region           = var.aws_region
  alert_email          = var.alert_email
  instance_id          = module.compute.instance_id
  db_instance_id       = module.database.instance_id
  lambda_function_name = module.lambda.function_name
  app_log_group_name   = module.compute.log_group_name
}
