data "archive_file" "ecs_alert_lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/ecs_alert_lambda.zip"
}

resource "aws_lambda_function" "ecs_alert" {
  function_name    = "${var.app_name}-${var.environment}-ecs-alert"
  role             = aws_iam_role.ecs_alert_lambda_role.arn
  handler          = "app.main"
  runtime          = "python3.12"
  filename         = data.archive_file.ecs_alert_lambda_zip.output_path
  source_code_hash = data.archive_file.ecs_alert_lambda_zip.output_base64sha256

  environment {
    variables = {
      APP_NAME          = var.app_name
      ENVIRONMENT       = var.environment
      AWS_REGION        = var.aws_region
      SLACK_WEBHOOK_URL = var.slack_webhook_url
    }
  }

  logging_config {
    log_group  = aws_cloudwatch_log_group.ecs_alert.name
    log_format = "Text"
  }
}

resource "aws_cloudwatch_log_group" "ecs_alert" {
  name              = "/aws/lambda/${var.app_name}-${var.environment}-ecs-alert"
  retention_in_days = 30
}

resource "aws_iam_role" "ecs_alert_lambda_role" {
  name = "${var.app_name}-${var.environment}-ecs-alert-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_alert_lambda_policy" {
  name = "${var.app_name}-${var.environment}-ecs-alert-policy"
  role = aws_iam_role.ecs_alert_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
    ]
  })
}

resource "aws_cloudwatch_event_rule" "ecs_task_start_impaired" {
  name        = "${var.app_name}-${var.environment}-ecs-task-impaired"
  description = "Trigger lambda on ECS task start impaired events"

  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Service Action"]
    detail = {
      eventName = ["SERVICE_TASK_START_IMPAIRED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "ecs_alert" {
  rule      = aws_cloudwatch_event_rule.ecs_task_start_impaired.name
  target_id = "SendToECSAlertLambda"
  arn       = aws_lambda_function.ecs_alert.arn
}

resource "aws_lambda_permission" "allow_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ecs_alert.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ecs_task_start_impaired.arn
}
