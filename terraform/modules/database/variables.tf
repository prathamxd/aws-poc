variable "name_prefix" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "db_security_group_id" {
  type = string
}

variable "instance_class" {
  type = string
}

variable "engine_version" {
  type = string
}

variable "allocated_storage" {
  type = number
}

variable "backup_retention_days" {
  type = number
}

variable "db_name" {
  type    = string
  default = "ticketdesk"
}

variable "master_username" {
  type    = string
  default = "tdadmin"
}
