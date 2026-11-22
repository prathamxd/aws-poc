# Latest Amazon Linux 2023 (x86_64) AMI
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# ---------------------------------------------------------------- container registry
resource "aws_ecr_repository" "app" {
  name                 = var.name_prefix
  image_tag_mutability = "MUTABLE"
  force_delete         = true # POC: lets terraform destroy remove the repo with its images

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the 10 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

# ---------------------------------------------------------------- application logs
resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.name_prefix}/app"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------- IAM role for the EC2 instance
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${var.name_prefix}-ec2-role"
  description        = "TicketDesk app server - pull image, use attachments bucket, read its secrets, write logs"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Session Manager shell access instead of SSH keys / port 22
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "app" {
  statement {
    sid       = "EcrAuthToken"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this action does not support resource-level permissions
  }

  statement {
    sid       = "PullAppImage"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
    resources = [aws_ecr_repository.app.arn]
  }

  statement {
    sid       = "AttachmentsReadWrite"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:GetObjectTagging"]
    resources = ["${var.bucket_arn}/attachments/*"]
  }

  statement {
    sid       = "ReadOwnSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.app_secret_arn, var.db_secret_arn]
  }

  statement {
    sid       = "WriteAppLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "ticketdesk-app-least-privilege"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.name_prefix}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# ---------------------------------------------------------------- EC2 instance
resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.app_security_group_id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  # Rendered bootstrap script: installs Docker and a systemd service that pulls
  # the image from ECR. Contains resource names and secret ARNs only - no secrets.
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    aws_region         = var.aws_region
    registry           = split("/", aws_ecr_repository.app.repository_url)[0]
    image              = "${aws_ecr_repository.app.repository_url}:latest"
    log_group          = aws_cloudwatch_log_group.app.name
    db_host            = var.db_host
    db_port            = var.db_port
    db_name            = var.db_name
    db_secret_arn      = var.db_secret_arn
    app_secret_arn     = var.app_secret_arn
    bucket_name        = var.bucket_name
    allowed_extensions = var.allowed_extensions
    max_upload_mb      = var.max_upload_mb
  })
  user_data_replace_on_change = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2          # the container is one network hop away
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  lifecycle {
    ignore_changes = [ami] # do not replace the server when AWS publishes a newer AMI
  }

  tags = {
    Name = "${var.name_prefix}-app"
  }

  depends_on = [aws_iam_role_policy.app]
}
