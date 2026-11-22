output "instance_id" {
  value = aws_db_instance.main.identifier
}

output "address" {
  value = aws_db_instance.main.address
}

output "port" {
  value = aws_db_instance.main.port
}

output "db_name" {
  value = aws_db_instance.main.db_name
}

output "master_user_secret_arn" {
  description = "Secrets Manager secret (JSON with username/password) created and rotated by RDS"
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}
