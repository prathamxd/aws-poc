resource "aws_sns_topic" "alerts" {
  name = "${var.name_prefix}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---------------------------------------------------------------- log-based metrics
resource "aws_cloudwatch_log_metric_filter" "app_errors" {
  name           = "${var.name_prefix}-app-errors"
  log_group_name = var.app_log_group_name
  pattern        = "?ERROR ?Traceback"

  metric_transformation {
    name          = "AppErrors"
    namespace     = "TicketDesk"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "failed_logins" {
  name           = "${var.name_prefix}-failed-logins"
  log_group_name = var.app_log_group_name
  pattern        = "\"Failed login attempt\""

  metric_transformation {
    name          = "FailedLogins"
    namespace     = "TicketDesk"
    value         = "1"
    default_value = "0"
  }
}

# ---------------------------------------------------------------- alarms
resource "aws_cloudwatch_metric_alarm" "ec2_cpu_high" {
  alarm_name          = "${var.name_prefix}-ec2-cpu-high"
  alarm_description   = "TicketDesk EC2 CPU above 80% for 10 minutes"
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  dimensions          = { InstanceId = var.instance_id }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "ec2_status_check" {
  alarm_name          = "${var.name_prefix}-ec2-status-check-failed"
  alarm_description   = "TicketDesk EC2 failed an instance or system status check"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed"
  dimensions          = { InstanceId = var.instance_id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  alarm_name          = "${var.name_prefix}-rds-cpu-high"
  alarm_description   = "TicketDesk RDS CPU above 80% for 10 minutes"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = var.db_instance_id }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "rds_storage_low" {
  alarm_name          = "${var.name_prefix}-rds-free-storage-low"
  alarm_description   = "TicketDesk RDS has less than 2 GB free storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = var.db_instance_id }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 2147483648
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.name_prefix}-lambda-errors"
  alarm_description   = "The attachment processor Lambda reported an error"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = var.lambda_function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "app_errors" {
  alarm_name          = "${var.name_prefix}-app-errors"
  alarm_description   = "5 or more application errors in 5 minutes (CloudWatch Logs metric filter)"
  namespace           = "TicketDesk"
  metric_name         = "AppErrors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "failed_logins" {
  alarm_name          = "${var.name_prefix}-failed-logins"
  alarm_description   = "10 or more failed logins in 5 minutes - possible password guessing"
  namespace           = "TicketDesk"
  metric_name         = "FailedLogins"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# ---------------------------------------------------------------- dashboard
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.name_prefix}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "EC2 CPU utilisation (%)"
          region  = var.aws_region
          view    = "timeSeries"
          stat    = "Average"
          period  = 300
          metrics = [["AWS/EC2", "CPUUtilization", "InstanceId", var.instance_id]]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "RDS CPU (%) and connections"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Average"
          period = 300
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_instance_id],
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", var.db_instance_id, { yAxis = "right" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Lambda file processor"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.lambda_function_name],
            ["AWS/Lambda", "Errors", "FunctionName", var.lambda_function_name],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Application errors and failed logins"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            ["TicketDesk", "AppErrors"],
            ["TicketDesk", "FailedLogins"],
          ]
        }
      },
      {
        type   = "log"
        x      = 0
        y      = 12
        width  = 24
        height = 6
        properties = {
          title  = "Latest application log lines"
          region = var.aws_region
          view   = "table"
          query  = "SOURCE '${var.app_log_group_name}' | fields @timestamp, @message | sort @timestamp desc | limit 50"
        }
      },
      {
        type   = "alarm"
        x      = 0
        y      = 18
        width  = 24
        height = 3
        properties = {
          title = "Alarms"
          alarms = [
            aws_cloudwatch_metric_alarm.ec2_cpu_high.arn,
            aws_cloudwatch_metric_alarm.ec2_status_check.arn,
            aws_cloudwatch_metric_alarm.rds_cpu_high.arn,
            aws_cloudwatch_metric_alarm.rds_storage_low.arn,
            aws_cloudwatch_metric_alarm.lambda_errors.arn,
            aws_cloudwatch_metric_alarm.app_errors.arn,
            aws_cloudwatch_metric_alarm.failed_logins.arn,
          ]
        }
      },
    ]
  })
}
