variable "name_prefix" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "instance_type" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "app_security_group_id" {
  type = string
}

variable "bucket_name" {
  type = string
}

variable "bucket_arn" {
  type = string
}

variable "db_host" {
  type = string
}

variable "db_port" {
  type = number
}

variable "db_name" {
  type = string
}

variable "db_secret_arn" {
  type = string
}

variable "app_secret_arn" {
  type = string
}

variable "allowed_extensions" {
  type = string
}

variable "max_upload_mb" {
  type = number
}

variable "log_retention_days" {
  type = number
}
