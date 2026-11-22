output "bucket_name" {
  value = aws_s3_bucket.attachments.id
}

output "bucket_arn" {
  value = aws_s3_bucket.attachments.arn
}
