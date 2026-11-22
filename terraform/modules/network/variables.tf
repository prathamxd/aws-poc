variable "name_prefix" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "allowed_http_cidrs" {
  type = list(string)
}
