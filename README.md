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
module "ecs_alerts" {
  source = "git::https://github.com/your-org/terraform-aws-ecs-service-alerts.git"

  name_prefix             = "myapp"
  slack_webhook_url_prod  = var.slack_webhook_url_prod
  slack_webhook_url_lower = var.slack_webhook_url_lower

  # Optional: suppress alerts during a nightly maintenance window (UTC)
  maintenance_window_enabled = true
  maintenance_window_start   = "01:00"
  maintenance_window_end     = "05:00"
}
```

> Alerts are routed automatically — clusters with `prod` in their name go to the prod channel, all others to the lower env channel.

> Webhook URL'leri sensitive — secret store veya `TF_VAR_` ile geçirin.

## Requirements

| Name      | Version   |
|-----------|-----------|
| terraform | >= 1.3    |
| aws       | >= 5.0    |

## Maintenance Window

You can define a recurring UTC time window during which **deployment-related** Slack alerts are suppressed. This is useful for planned maintenance (e.g. automated deployments, AMI rotations) that would otherwise trigger a flood of false-positive alerts.

**Runtime crash alerts (OOM kills, non-zero exit codes) and Spot interruptions are never suppressed** — these indicate real issues even during maintenance.

- **Disabled by default** — set `maintenance_window_enabled = true` to activate.
- **Events are still logged** — the Lambda still executes and writes to CloudWatch Logs with a `[MAINTENANCE WINDOW]` prefix, preserving the audit trail.
- **Overnight windows supported** — e.g. `start = "23:00"`, `end = "01:00"` works correctly across midnight.
- **All times are UTC** to avoid daylight saving time edge cases.

### What gets suppressed during the window

| Alert Type | Suppressed | Reason |
|---|---|---|
| Service Start Impaired | ✅ Yes | Expected during rolling updates |
| Deployment Failed | ✅ Yes | Deployment lifecycle noise |
| Task Failed to Start | ✅ Yes | Image pull / resource allocation during update |
| Task Stopped Manually | ✅ Yes | Likely part of maintenance |
| **Task Crashed (OOM, non-zero exit)** | ❌ **No** | Real runtime issue |
| **Spot Interruption** | ❌ **No** | AWS-initiated, unrelated to maintenance |

## Inputs

| Name                | Type     | Default            | Required | Description                              |
|---------------------|----------|--------------------|----------|------------------------------------------|
| `name_prefix`              | `string` | —                | yes      | Prefix used for all resource names                        |
| `aws_region`               | `string` | `ap-southeast-2` | no       | AWS region                                                |
| `slack_webhook_url_prod`   | `string` | —                | yes      | Slack webhook for prod alerts (clusters containing `prod`)|
| `slack_webhook_url_lower`  | `string` | —                | yes      | Slack webhook for lower environment alerts (sensitive)    |
| `maintenance_window_enabled` | `bool` | `false`          | no       | Enable maintenance window alert suppression               |
| `maintenance_window_start`   | `string` | `01:00`        | no       | Start time in HH:MM (UTC)                                 |
| `maintenance_window_end`     | `string` | `05:00`        | no       | End time in HH:MM (UTC). Overnight windows supported      |

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
