variable "name_prefix" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "github_repository" {
  description = "owner/name"
  type        = string
}

variable "create_oidc_provider" {
  type = bool
}

variable "ecr_repository_arn" {
  type = string
}

variable "ec2_instance_arn" {
  type = string
}
