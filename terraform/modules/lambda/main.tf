locals {
  function_name = "${var.name_prefix}-file-processor"
}

data "archive_file" "processor" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.root}/.build/file_processor.zip"
  excludes    = ["__pycache__"]
}

# Created before the function so Terraform owns it (deleted on destroy, retention set)
resource "aws_cloudwatch_log_group" "processor" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "processor" {
  name               = "${local.function_name}-role"
  description        = "TicketDesk file processor Lambda - logs + read/tag attachments only"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Least privilege: only its own log group and only objects under attachments/
data "aws_iam_policy_document" "processor" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.processor.arn}:*"]
  }

  statement {
    sid       = "ReadAndTagAttachments"
    actions   = ["s3:GetObject", "s3:GetObjectTagging", "s3:PutObjectTagging"]
    resources = ["${var.bucket_arn}/attachments/*"]
  }
}

resource "aws_iam_role_policy" "processor" {
  name   = "file-processor-least-privilege"
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.processor.json
}

resource "aws_lambda_function" "processor" {
  function_name    = local.function_name
  description      = "Validates TicketDesk attachments uploaded to S3 and tags the result"
  role             = aws_iam_role.processor.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.processor.output_path
  source_code_hash = data.archive_file.processor.output_base64sha256
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      ALLOWED_EXTENSIONS = var.allowed_extensions
      MAX_SIZE_MB        = tostring(var.max_upload_mb)
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.processor,
    aws_iam_role_policy.processor,
  ]
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id   = "AllowInvokeFromAttachmentsBucket"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.processor.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = var.bucket_arn
  source_account = var.account_id
}

resource "aws_s3_bucket_notification" "attachments" {
  bucket = var.bucket_name

  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "attachments/"
  }

  depends_on = [aws_lambda_permission.allow_s3]
}
