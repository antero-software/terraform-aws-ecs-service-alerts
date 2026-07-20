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

  # Optional: suppress alerts while the SSM patch manager's window is actively
  # patching/rebooting instances, instead of guessing a fixed clock range
  patch_maintenance_window_id = module.patch_manager.maintenance_window_id

  # Optional: suppress alerts for ad hoc maintenance via an SSM parameter
  maintenance_marker_parameter_name = "/myapp/maintenance-marker"
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

Slack alerts can be suppressed while maintenance is happening. Two independent signals feed into the same suppression check — either one being active is enough to suppress:

1. **Patch manager window** — `patch_maintenance_window_id` set to the ID of an SSM Maintenance Window, e.g. the `maintenance_window_id` output of [`terraform-aws-ssm-patch-manager`](https://github.com/antero-software/terraform-aws-ssm-patch-manager). The Lambda checks whether that window currently has an execution `IN_PROGRESS`, so suppression tracks real patch/reboot activity instead of a guessed clock range — if a patch run finishes early or runs long, the suppression window follows it exactly.
2. **Manual marker** — `maintenance_marker_parameter_name` set to an SSM Parameter Store parameter name. Set the parameter to a truthy value (`true`/`1`/`active`/`on`/`yes`) to suppress ad hoc, outside any schedule.

Both are optional and off by default.

- **Events are still logged** — the Lambda still executes and writes to CloudWatch Logs with a `[MAINTENANCE WINDOW]` prefix, preserving the audit trail.

### What gets suppressed when a maintenance signal is active

| Alert Type | Suppressed | Reason |
|---|---|---|
| Service Start Impaired | ✅ Yes | Expected during rolling updates |
| Deployment Failed | ✅ Yes | Deployment lifecycle noise |
| Task Failed to Start | ✅ Yes | Image pull / resource allocation during update |
| Task Stopped Manually | ✅ Yes | Likely part of maintenance |
| Task Crashed (OOM, non-zero exit) | ✅ Yes | Patching-induced reboots can SIGKILL containers (exit 137); real if no maintenance signal is active |
| **Spot Interruption** | ❌ **No** | AWS-initiated, unrelated to maintenance |

## Inputs

| Name                | Type     | Default            | Required | Description                              |
|---------------------|----------|--------------------|----------|------------------------------------------|
| `name_prefix`              | `string` | —                | yes      | Prefix used for all resource names                        |
| `aws_region`               | `string` | `ap-southeast-2` | no       | AWS region                                                |
| `slack_webhook_url_prod`   | `string` | —                | yes      | Slack webhook for prod alerts (clusters containing `prod`)|
| `slack_webhook_url_lower`  | `string` | —                | yes      | Slack webhook for lower environment alerts (sensitive)    |
| `patch_maintenance_window_id` | `string` | `""`          | no       | SSM Maintenance Window ID to suppress alerts while it has an execution in progress (e.g. from `terraform-aws-ssm-patch-manager`) |
| `maintenance_marker_parameter_name` | `string` | `""`   | no       | SSM Parameter Store parameter name for manual ad hoc suppression |

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
