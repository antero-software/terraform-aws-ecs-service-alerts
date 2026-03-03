resource "aws_lambda_function" "ecs_alert" {
  function_name    = "${var.name_prefix}-ecs-alert"
  role             = aws_iam_role.ecs_alert_lambda_role.arn
  handler          = "app.main"
  runtime          = "python3.12"
  filename         = "${path.module}/ecs_alert_lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/ecs_alert_lambda.zip")

  environment {
    variables = {
      NAME_PREFIX             = var.name_prefix
      SLACK_WEBHOOK_URL_PROD  = var.slack_webhook_url_prod
      SLACK_WEBHOOK_URL_LOWER = var.slack_webhook_url_lower
    }
  }

  logging_config {
    log_group  = aws_cloudwatch_log_group.ecs_alert.name
    log_format = "Text"
  }
}

resource "aws_cloudwatch_log_group" "ecs_alert" {
  name              = "/aws/lambda/${var.name_prefix}-ecs-alert"
  retention_in_days = 30
}

resource "aws_iam_role" "ecs_alert_lambda_role" {
  name = "${var.name_prefix}-ecs-alert-role"

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
  name = "${var.name_prefix}-ecs-alert-policy"
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
      {
        Effect   = "Allow"
        Action   = ["ecs:DescribeServices"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_cloudwatch_event_rule" "ecs_task_start_impaired" {
  name        = "${var.name_prefix}-ecs-task-impaired"
  description = "Trigger lambda on ECS task start impaired events"

  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Service Action"]
    detail = {
      eventName = ["SERVICE_TASK_START_IMPAIRED"]
    }
  })
}

resource "aws_cloudwatch_event_rule" "ecs_task_crashed" {
  name        = "${var.name_prefix}-ecs-task-crashed"
  description = "Trigger lambda when an ECS task stops with a non-zero exit code"

  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      lastStatus = ["STOPPED"]
      stopCode   = ["EssentialContainerExited"]
    }
  })
}

resource "aws_cloudwatch_event_target" "ecs_alert_impaired" {
  rule      = aws_cloudwatch_event_rule.ecs_task_start_impaired.name
  target_id = "SendToECSAlertLambda"
  arn       = aws_lambda_function.ecs_alert.arn
}

resource "aws_cloudwatch_event_target" "ecs_alert_crashed" {
  rule      = aws_cloudwatch_event_rule.ecs_task_crashed.name
  target_id = "SendToECSAlertLambdaCrash"
  arn       = aws_lambda_function.ecs_alert.arn
}

resource "aws_lambda_permission" "allow_cloudwatch_impaired" {
  statement_id  = "AllowExecutionFromCloudWatchImpaired"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ecs_alert.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ecs_task_start_impaired.arn
}

resource "aws_lambda_permission" "allow_cloudwatch_crashed" {
  statement_id  = "AllowExecutionFromCloudWatchCrashed"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ecs_alert.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ecs_task_crashed.arn
}
