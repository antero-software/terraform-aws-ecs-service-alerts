output "lambda_function_arn" {
  value       = aws_lambda_function.ecs_alert.arn
  description = "The ARN of the ECS alert Lambda function"
}

output "lambda_function_name" {
  value       = aws_lambda_function.ecs_alert.function_name
  description = "The name of the ECS alert Lambda function"
}

output "cloudwatch_event_rule_arn" {
  value       = aws_cloudwatch_event_rule.ecs_task_start_impaired.arn
  description = "The ARN of the CloudWatch event rule triggering the alert"
}
