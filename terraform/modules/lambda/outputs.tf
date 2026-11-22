output "function_name" {
  value = aws_lambda_function.processor.function_name
}

output "function_arn" {
  value = aws_lambda_function.processor.arn
}

output "role_name" {
  value = aws_iam_role.processor.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.processor.name
}
