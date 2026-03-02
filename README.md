# terraform-aws-ecs-service-alerts

Terraform module that sends Slack alerts for two ECS failure scenarios:

- **Service start impaired** — ECS service is unable to consistently start tasks (`SERVICE_TASK_START_IMPAIRED`)
- **Container crash** — a running container exits with a non-zero exit code (including OOM kills)

Useful for catching bad deployments, image pull failures, capacity issues, and runtime crashes before they cause prolonged downtime.

## Architecture

```
ECS events
     │
     ├─── ECS Service Action ──────────────────────────────────┐
     │    (SERVICE_TASK_START_IMPAIRED)                        │
     │                                                         │
     └─── ECS Task State Change ───────────────────────────────┤
          (lastStatus=STOPPED, stopCode=EssentialContainerExited)│
                                                               ▼
                                                  CloudWatch Event Rules
                                                               │
                                                               ▼
                                                  AWS Lambda (Python 3.12)
                                                               │
                                                               ▼
                                                        Slack webhook
```

## Example Slack Alerts

**Service start impaired:**
```
🚨 myapp-ecs-tasks-alert

┃ my-cluster / image_inferrer
┃
┃ image_inferrer is unable to consistently start tasks successfully.
┃ View in console →
┃
┃ Recent Events
┃ • (service image_inferrer) failed to launch a task with (error EssentialContainerExited).
┃ • service image_inferrer: task definition image_inferrer:42 does not exist.
```

**Container crash / OOM kill:**
```
🚨 myapp-ecs-tasks-alert

┃ my-cluster / image_inferrer — task crashed
┃
┃ View in console →
┃
┃ Stopped Reason
┃ Essential container in task exited
┃
┃ Crashed Containers
┃ • api: OOM killed (exit code 137)
```

## Usage

```hcl
module "ecs_service_alerts" {
  source = "git::https://github.com/your-org/terraform-aws-ecs-service-alerts.git"

  app_name          = "myapp"
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
| `aws_region`        | `string` | `ap-southeast-2`   | no       | AWS region                               |
| `slack_webhook_url` | `string` | —                  | yes      | Slack incoming webhook URL (sensitive)   |

## Outputs

| Name                       | Description                                        |
|----------------------------|----------------------------------------------------|
| `lambda_function_arn`      | ARN of the ECS alert Lambda function               |
| `lambda_function_name`     | Name of the ECS alert Lambda function              |
| `cloudwatch_event_rule_arn`| ARN of the CloudWatch event rule (service impaired)|

## Resources Created

| Resource                          | Name pattern                                         |
|-----------------------------------|------------------------------------------------------|
| `aws_lambda_function`             | `{app_name}-{environment}-ecs-alert`                 |
| `aws_cloudwatch_log_group`        | `/aws/lambda/{app_name}-{environment}-ecs-alert`     |
| `aws_iam_role`                    | `{app_name}-{environment}-ecs-alert-role`            |
| `aws_iam_role_policy`             | `{app_name}-{environment}-ecs-alert-policy`          |
| `aws_cloudwatch_event_rule`       | `{app_name}-{environment}-ecs-task-impaired`         |
| `aws_cloudwatch_event_rule`       | `{app_name}-{environment}-ecs-task-crashed`          |
| `aws_cloudwatch_event_target` ×2  | —                                                    |
| `aws_lambda_permission` ×2        | —                                                    |
