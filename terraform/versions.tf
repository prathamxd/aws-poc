terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
  }

  # Team setup: state is shared in S3 (backend.tf, created from backend.tf.example)
  # so every member can plan/apply. S3-native locking needs Terraform >= 1.10.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "TicketDesk"
      Environment = var.environment
      Owner       = var.owner
      ManagedBy   = "Terraform"
    }
  }
}
