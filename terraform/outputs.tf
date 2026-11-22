output "aws_region" {
  value = var.aws_region
}

output "app_url" {
  description = "Open this in your browser"
  value       = "http://${module.compute.public_dns}"
}

output "ec2_instance_id" {
  value = module.compute.instance_id
}

output "ec2_public_ip" {
  value = module.compute.public_ip
}

output "ecr_repository_url" {
  value = module.compute.ecr_repository_url
}

output "s3_bucket_name" {
  value = module.storage.bucket_name
}

output "rds_endpoint" {
  value = module.database.address
}

output "rds_instance_id" {
  value = module.database.instance_id
}

output "db_secret_arn" {
  value = module.database.master_user_secret_arn
}

output "app_secret_arn" {
  value = module.secrets.app_secret_arn
}

output "lambda_function_name" {
  value = module.lambda.function_name
}

output "app_log_group" {
  value = module.compute.log_group_name
}

output "lambda_log_group" {
  value = module.lambda.log_group_name
}

output "app_security_group_id" {
  value = module.network.app_security_group_id
}

output "rds_security_group_id" {
  value = module.network.db_security_group_id
}

output "ec2_role_name" {
  value = module.compute.role_name
}

output "lambda_role_name" {
  value = module.lambda.role_name
}

output "github_actions_role_name" {
  value = try(module.cicd[0].role_name, null)
}

output "github_actions_variables" {
  description = "Add these in GitHub: Settings > Secrets and variables > Actions > Variables"
  value = length(module.cicd) == 0 ? null : {
    AWS_REGION      = var.aws_region
    AWS_ROLE_ARN    = try(module.cicd[0].role_arn, "")
    ECR_REPOSITORY  = module.compute.ecr_repository_name
    EC2_INSTANCE_ID = module.compute.instance_id
    APP_URL         = "http://${module.compute.public_dns}"
  }
}

output "cloudwatch_dashboard_url" {
  value = module.monitoring.dashboard_url
}

output "admin_password_command" {
  description = "Prints the admin login (username/password) from Secrets Manager"
  value       = "aws secretsmanager get-secret-value --region ${var.aws_region} --secret-id ${module.secrets.app_secret_arn} --query SecretString --output text"
}

output "ssm_session_command" {
  description = "Shell on the EC2 instance without SSH keys (needs the Session Manager plugin)"
  value       = "aws ssm start-session --region ${var.aws_region} --target ${module.compute.instance_id}"
}
