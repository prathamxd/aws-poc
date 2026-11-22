output "instance_id" {
  value = aws_instance.app.id
}

output "instance_arn" {
  value = aws_instance.app.arn
}

output "public_ip" {
  value = aws_instance.app.public_ip
}

output "public_dns" {
  value = aws_instance.app.public_dns
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "ecr_repository_arn" {
  value = aws_ecr_repository.app.arn
}

output "ecr_repository_name" {
  value = aws_ecr_repository.app.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.app.name
}

output "role_name" {
  value = aws_iam_role.ec2.name
}
