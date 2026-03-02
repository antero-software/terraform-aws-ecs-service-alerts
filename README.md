# terraform-aws-ecs-service-alerts

Terraform module that sends a Slack alert when an ECS service is unable to consistently start tasks — i.e. when the `SERVICE_TASK_START_IMPAIRED` event fires.

Useful for catching bad deployments (broken config, image pull failures, capacity issues) before they cause prolonged downtime.

## Architecture

```
ECS service events
       │
       ▼
CloudWatch Event Rule         ← filters for SERVICE_TASK_START_IMPAIRED only
       │
       ▼
AWS Lambda (Python 3.12)
       │
       ▼
Slack webhook
```

## Example Slack Alert

```
🚨 myapp-production-ecs-tasks-alert

┃ my-cluster / image_inferrer
┃
┃ image_inferrer is unable to consistently start tasks successfully.
┃ View in console →
```

## Usage

```hcl
module "ecs_service_alerts" {
  source = "git::https://github.com/your-org/terraform-aws-ecs-service-alerts.git"

  app_name          = "myapp"
  environment       = "production"
  slack_webhook_url = var.slack_webhook_url
}
```

> `slack_webhook_url` is marked sensitive — pass it via a secret store or `TF_VAR_slack_webhook_url`.

## Requirements

| Name      | Version   |
|-----------|-----------|
| terraform | >= 1.3    |
| aws       | >= 5.0    |

## Inputs

| Name                | Type     | Default            | Required | Description                              |
|---------------------|----------|--------------------|----------|------------------------------------------|
| `app_name`          | `string` | —                  | yes      | Application name                         |
| `environment`       | `string` | —                  | yes      | Environment name (e.g. `production`)     |
| `aws_region`        | `string` | `ap-southeast-2`   | no       | AWS region                               |
| `slack_webhook_url` | `string` | —                  | yes      | Slack incoming webhook URL (sensitive)   |

## Outputs

| Name                       | Description                                        |
|----------------------------|----------------------------------------------------|
| `lambda_function_arn`      | ARN of the ECS alert Lambda function               |
| `lambda_function_name`     | Name of the ECS alert Lambda function              |
| `cloudwatch_event_rule_arn`| ARN of the CloudWatch event rule                   |

## Resources Created

| Resource                          | Name pattern                                  |
|-----------------------------------|-----------------------------------------------|
| `aws_lambda_function`             | `{app_name}-{environment}-ecs-alert`          |
| `aws_cloudwatch_log_group`        | `/aws/lambda/{app_name}-{environment}-ecs-alert` |
| `aws_iam_role`                    | `{app_name}-{environment}-ecs-alert-role`     |
| `aws_iam_role_policy`             | `{app_name}-{environment}-ecs-alert-policy`   |
| `aws_cloudwatch_event_rule`       | `{app_name}-{environment}-ecs-task-impaired`  |
| `aws_cloudwatch_event_target`     | —                                             |
| `aws_lambda_permission`           | —                                             |
