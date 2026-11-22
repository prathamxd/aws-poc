variable "project_name" {
  description = "Short name used in every resource name"
  type        = string
  default     = "ticketdesk"
}

variable "environment" {
  description = "Environment name (poc, dev, prod...)"
  type        = string
  default     = "poc"
}

variable "owner" {
  description = "Your name - added as an Owner tag on every resource"
  type        = string
  default     = "student"
}

variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "ap-south-1"
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "allowed_http_cidrs" {
  description = "Who may open the app on port 80. Use [\"<your-public-ip>/32\"] to restrict it to you."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "instance_type" {
  description = "EC2 instance type (x86_64)"
  type        = string
  default     = "t3.micro"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_engine_version" {
  description = "PostgreSQL major version for RDS"
  type        = string
  default     = "16"
}

variable "db_allocated_storage" {
  description = "RDS storage in GB"
  type        = number
  default     = 20
}

variable "db_backup_retention_days" {
  description = "Days of automated RDS backups (free-tier accounts may only allow 0 or 1)"
  type        = number
  default     = 1
}

variable "allowed_extensions" {
  description = "File types accepted by the app and by the Lambda processor"
  type        = string
  default     = ".png,.jpg,.jpeg,.gif,.pdf,.txt,.log,.csv,.docx,.xlsx"
}

variable "max_upload_mb" {
  description = "Maximum attachment size in MB"
  type        = number
  default     = 5
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention"
  type        = number
  default     = 14
}

variable "github_repository" {
  description = "GitHub repo as owner/name (exact case). Empty = skip creating the CI/CD deploy role."
  type        = string
  default     = ""
}

variable "create_github_oidc_provider" {
  description = "Set to false if your AWS account already has the GitHub OIDC provider"
  type        = bool
  default     = true
}

variable "alert_email" {
  description = "Email for CloudWatch alarm notifications (confirm the subscription email). Empty = no email."
  type        = string
  default     = ""
}
