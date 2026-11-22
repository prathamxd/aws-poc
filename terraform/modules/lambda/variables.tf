variable "name_prefix" {
  type = string
}

variable "account_id" {
  type = string
}

variable "bucket_name" {
  type = string
}

variable "bucket_arn" {
  type = string
}

variable "source_dir" {
  description = "Folder containing handler.py"
  type        = string
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
