import functools
import json
import os
import sys
import urllib.request
from urllib.error import HTTPError
from typing import Any, Callable, Optional

import boto3


SlackSender = Callable[[urllib.request.Request], Any]


def log_on_error(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            print(f"args   = {args!r}", file=sys.stderr)
            print(f"kwargs = {kwargs!r}", file=sys.stderr)
            raise

    return wrapper


def _pick_webhook(cluster_name, *, webhook_prod, webhook_lower):
    """Route to prod channel if cluster name contains 'prod', otherwise lower env."""
    return webhook_prod if "prod" in cluster_name.lower() else webhook_lower


def _log_maintenance_suppressed(event_type, event):
    """Log a suppressed event during a maintenance window for audit."""
    print(f"[MAINTENANCE WINDOW] {event_type} alert suppressed. "
          f"event={json.dumps(event, default=str)}")


def _maintenance_marker_active(ssm_client, marker_parameter_name):
    if not marker_parameter_name:
        return False

    try:
        response = ssm_client.get_parameter(Name=marker_parameter_name)
        value = response["Parameter"]["Value"].strip().lower()
        return value in {"true", "1", "active", "on", "yes"}
    except Exception as exc:
        print(f"Failed to read maintenance marker {marker_parameter_name!r}: {exc}", file=sys.stderr)
        return False


def _patch_window_active(ssm_client, window_id):
    """Check whether the given SSM Maintenance Window (e.g. the patch manager's
    weekly window) currently has an execution in progress.

    This reflects real patching/reboot activity rather than a fixed clock
    schedule, so alerts are suppressed exactly while patching is actually
    running instead of an approximate manually-configured time range.
    """
    if not window_id:
        return False

    try:
        response = ssm_client.describe_maintenance_window_executions(
            WindowId=window_id,
            Filters=[{"Key": "Status", "Values": ["IN_PROGRESS"]}],
            MaxResults=1,
        )
        return bool(response.get("WindowExecutions"))
    except Exception as exc:
        print(f"Failed to check patch maintenance window {window_id!r}: {exc}", file=sys.stderr)
        return False


def _maintenance_suppression_reason(event, *, ssm_client, marker_parameter_name, patch_window_id):
    if _maintenance_marker_active(ssm_client, marker_parameter_name):
        return "maintenance marker"

    if _patch_window_active(ssm_client, patch_window_id):
        return "patch manager window"

    return None


def _send_slack(webhook_url, payload, sender):
    print("Sending message %s" % json.dumps(payload))
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        sender(req)
    except HTTPError as err:
        raise Exception(f"{err} - {err.read()}")


def _fetch_recent_events(ecs_client, cluster_name, service_name):
    """Return the last 5 ECS service event messages, or [] on failure."""
    try:
        response = ecs_client.describe_services(
            cluster=cluster_name,
            services=[service_name],
        )
        services = response.get("services", [])
        if services:
            return [e["message"] for e in services[0].get("events", [])[:5]]
    except Exception as e:
        print(f"Failed to fetch ECS service events: {e}", file=sys.stderr)
    return []


def _handle_service_impaired(event, *, ecs_client, ssm_client, maintenance_marker_parameter_name, patch_maintenance_window_id, name_prefix, aws_region, webhook_prod, webhook_lower, sender):
    # The 'resources' list will contain a list of ECS service ARNs, e.g.
    #
    #     arn:aws:ecs:eu-west-1:1234567890:service/pipeline/image_inferrer
    #
    # Extract the cluster/service name; in this case 'pipeline' and
    # 'image_inferrer'.
    for r in event["resources"]:
        _, cluster_name, service_name = r.split("/")

        webhook_url = _pick_webhook(cluster_name, webhook_prod=webhook_prod, webhook_lower=webhook_lower)

        recent_events = _fetch_recent_events(ecs_client, cluster_name, service_name)

        suppression_reason = _maintenance_suppression_reason(
            event,
            ssm_client=ssm_client,
            marker_parameter_name=maintenance_marker_parameter_name,
            patch_window_id=patch_maintenance_window_id,
        )
        if suppression_reason:
            _log_maintenance_suppressed("SERVICE_TASK_START_IMPAIRED", event)
            return

        console_url = (
            f"https://{aws_region}.console.aws.amazon.com/ecs/v2/clusters/"
            f"{cluster_name}/services/{service_name}/deployments?region={aws_region}"
        )

        fields = [
            {"title": "ECS Cluster", "value": cluster_name, "short": True},
            {"title": "ECS Service", "value": service_name, "short": True},
            {"title": "Details", "value": f"{service_name} is unable to consistently start tasks successfully.", "short": False},
        ]

        if recent_events:
            fields.append({
                "title": "Recent Events",
                "value": "\n".join(f"• {e}" for e in recent_events),
            })

        _send_slack(webhook_url, {
            "username": f"{name_prefix}-ecs-tasks-alert",
            "icon_emoji": ":rotating_light:",
            "attachments": [
                {
                    "color": "danger",
                    "pretext": ":cat_shake: *Service Start Impaired*",
                    "mrkdwn_in": ["pretext"],
                    "fields": fields,
                    "actions": [
                        {"type": "button", "text": "View in Console :arrow_upper_right:", "url": console_url},
                    ],
                }
            ],
        }, sender)


def _handle_deployment_failed(event, *, ecs_client, ssm_client, maintenance_marker_parameter_name, patch_maintenance_window_id, name_prefix, aws_region, webhook_prod, webhook_lower, sender):
    # Same ARN structure as service action events:
    #   arn:aws:ecs:region:account:service/cluster/service
    for r in event["resources"]:
        _, cluster_name, service_name = r.split("/")

        webhook_url = _pick_webhook(cluster_name, webhook_prod=webhook_prod, webhook_lower=webhook_lower)

        # Fetch recent events to surface why the deployment failed.
        recent_events = _fetch_recent_events(ecs_client, cluster_name, service_name)

        suppression_reason = _maintenance_suppression_reason(
            event,
            ssm_client=ssm_client,
            marker_parameter_name=maintenance_marker_parameter_name,
            patch_window_id=patch_maintenance_window_id,
        )
        if suppression_reason:
            _log_maintenance_suppressed("SERVICE_DEPLOYMENT_FAILED", event)
            return

        console_url = (
            f"https://{aws_region}.console.aws.amazon.com/ecs/v2/clusters/"
            f"{cluster_name}/services/{service_name}/deployments?region={aws_region}"
        )

        fields = [
            {"title": "ECS Cluster", "value": cluster_name, "short": True},
            {"title": "ECS Service", "value": service_name, "short": True},
        ]

        if recent_events:
            fields.append({
                "title": "Recent Events",
                "value": "\n".join(f"• {e}" for e in recent_events),
            })

        _send_slack(webhook_url, {
            "username": f"{name_prefix}-ecs-tasks-alert",
            "icon_emoji": ":rotating_light:",
            "attachments": [
                {
                    "color": "danger",
                    "pretext": ":alert: *Deployment Failed*",
                    "mrkdwn_in": ["pretext"],
                    "fields": fields,
                    "actions": [
                        {"type": "button", "text": "View in Console :arrow_upper_right:", "url": console_url},
                    ],
                }
            ],
        }, sender)


def _handle_task_stopped(event, *, ssm_client, maintenance_marker_parameter_name, patch_maintenance_window_id, name_prefix, aws_region, webhook_prod, webhook_lower, sender):
    detail = event["detail"]

    # Only alert for service tasks, not standalone tasks.
    group = detail.get("group", "")
    if not group.startswith("service:"):
        return
    service_name = group.split(":", 1)[1]

    cluster_name = detail["clusterArn"].split("/")[-1]
    stop_code = detail.get("stopCode", "")

    webhook_url = _pick_webhook(cluster_name, webhook_prod=webhook_prod, webhook_lower=webhook_lower)

    suppression_reason = _maintenance_suppression_reason(
        event,
        ssm_client=ssm_client,
        marker_parameter_name=maintenance_marker_parameter_name,
        patch_window_id=patch_maintenance_window_id,
    )

    console_url = (
        f"https://{aws_region}.console.aws.amazon.com/ecs/v2/clusters/"
        f"{cluster_name}/services/{service_name}/deployments?region={aws_region}"
    )

    if stop_code == "SpotInterruptionTermination":
        _send_slack(webhook_url, {
            "username": f"{name_prefix}-ecs-tasks-alert",
            "icon_emoji": ":rotating_light:",
            "attachments": [
                {
                    "color": "warning",
                    "pretext": ":warning: *Spot Instance Interrupted*",
                    "mrkdwn_in": ["pretext"],
                    "fields": [
                        {"title": "ECS Cluster", "value": cluster_name, "short": True},
                        {"title": "ECS Service", "value": service_name, "short": True},
                        {"title": "Reason", "value": detail.get("stoppedReason", "AWS reclaimed the spot instance"), "short": False},
                    ],
                    "actions": [
                        {"type": "button", "text": "View in Console :arrow_upper_right:", "url": console_url},
                    ],
                }
            ],
        }, sender)
        return

    if stop_code == "UserInitiated":
        # Manual stop — likely part of maintenance, suppress during window.
        if suppression_reason:
            _log_maintenance_suppressed("UserInitiated", event)
            return

        _send_slack(webhook_url, {
            "username": f"{name_prefix}-ecs-tasks-alert",
            "icon_emoji": ":rotating_light:",
            "attachments": [
                {
                    "color": "warning",
                    "pretext": ":warning: *Task Stopped Manually*",
                    "mrkdwn_in": ["pretext"],
                    "fields": [
                        {"title": "ECS Cluster", "value": cluster_name, "short": True},
                        {"title": "ECS Service", "value": service_name, "short": True},
                        {"title": "Reason", "value": detail.get("stoppedReason", "Unknown"), "short": False},
                    ],
                    "actions": [
                        {"type": "button", "text": "View in Console :arrow_upper_right:", "url": console_url},
                    ],
                }
            ],
        }, sender)
        return

    if stop_code == "TaskFailedToStart":
        # Task never started — image pull failure, resource allocation failure, etc.
        # Deployment-related — suppress during maintenance window.
        if suppression_reason:
            _log_maintenance_suppressed("TaskFailedToStart", event)
            return

        # Containers won't have exit codes; the reason lives in stoppedReason.
        stopped_reason = detail.get("stoppedReason", "Unknown")
        container_lines = [
            f"• *{c['name']}*: {c['reason']}"
            for c in detail.get("containers", [])
            if c.get("reason")
        ]
        fields = [
            {"title": "ECS Cluster", "value": cluster_name, "short": True},
            {"title": "ECS Service", "value": service_name, "short": True},
            {"title": "Reason", "value": stopped_reason, "short": False},
        ]
        if container_lines:
            fields.append({"title": "Container Errors", "value": "\n".join(container_lines), "short": False})

        _send_slack(webhook_url, {
            "username": f"{name_prefix}-ecs-tasks-alert",
            "icon_emoji": ":rotating_light:",
            "attachments": [
                {
                    "color": "danger",
                    "pretext": ":alert: *Task Failed to Start*",
                    "mrkdwn_in": ["pretext"],
                    "fields": fields,
                    "actions": [
                        {"type": "button", "text": "View in Console :arrow_upper_right:", "url": console_url},
                    ],
                }
            ],
        }, sender)
        return

    # EssentialContainerExited / ServiceSchedulerInitiated:
    # Skip intentional stops — draining instances and scaling/deployment activity
    # are expected and should not page.
    stopped_reason = detail.get("stoppedReason", "")
    if "DRAINING" in stopped_reason or "Scaling activity initiated by" in stopped_reason or "Availability-zone rebalancing" in stopped_reason:
        return

    # Skip graceful shutdowns — only alert when at least one container exited
    # with a non-zero, non-graceful exit code.
    # 0   = clean exit
    # 143 = SIGTERM (graceful shutdown initiated by ECS/AWS)
    _GRACEFUL_EXIT_CODES = {0, 143}
    crashed = [
        c for c in detail.get("containers", [])
        if c.get("exitCode") is not None and c.get("exitCode") not in _GRACEFUL_EXIT_CODES
    ]
    if not crashed:
        return

    if suppression_reason:
        _log_maintenance_suppressed("TaskCrashed", event)
        return

    container_lines = []
    for c in crashed:
        name = c.get("name", "unknown")
        exit_code = c.get("exitCode")
        reason = c.get("reason", "")
        if "OOMKilled" in reason:
            container_lines.append(f"• *{name}*: OOM killed (exit code {exit_code})")
        else:
            line = f"• *{name}*: exit code {exit_code}"
            if reason:
                line += f" — {reason}"
            container_lines.append(line)

    _send_slack(webhook_url, {
        "username": f"{name_prefix}-ecs-tasks-alert",
        "icon_emoji": ":rotating_light:",
        "attachments": [
            {
                "color": "danger",
                "pretext": ":alert: *Task Crashed*",
                "mrkdwn_in": ["pretext"],
                "fields": [
                    {"title": "ECS Cluster", "value": cluster_name, "short": True},
                    {"title": "ECS Service", "value": service_name, "short": True},
                    {"title": "Stopped Reason", "value": detail.get("stoppedReason", "Unknown"), "short": False},
                    {"title": "Crashed Containers", "value": "\n".join(container_lines), "short": False},
                ],
                "actions": [
                    {"type": "button", "text": "View in Console :arrow_upper_right:", "url": console_url},
                ],
            }
        ],
    }, sender)


@log_on_error
def main(event, _ctxt=None, *, sender: Optional[SlackSender] = None):
    if sender is None:
        sender = urllib.request.urlopen

    name_prefix = os.environ["NAME_PREFIX"]
    aws_region = os.environ["AWS_REGION"]
    webhook_prod = os.environ["SLACK_WEBHOOK_URL_PROD"]
    webhook_lower = os.environ["SLACK_WEBHOOK_URL_LOWER"]
    maintenance_marker_parameter_name = os.environ.get("MAINTENANCE_MARKER_PARAMETER_NAME", "")
    patch_maintenance_window_id = os.environ.get("PATCH_MAINTENANCE_WINDOW_ID", "")

    sess = boto3.Session()
    ecs_client = sess.client("ecs", region_name=aws_region)
    ssm_client = sess.client("ssm", region_name=aws_region)

    detail_type = event.get("detail-type")
    event_name = event.get("detail", {}).get("eventName")

    if detail_type == "ECS Service Action":
        if event_name == "SERVICE_DEPLOYMENT_FAILED":
            _handle_deployment_failed(
                event,
                ecs_client=ecs_client,
                ssm_client=ssm_client,
                maintenance_marker_parameter_name=maintenance_marker_parameter_name,
                patch_maintenance_window_id=patch_maintenance_window_id,
                name_prefix=name_prefix,
                aws_region=aws_region,
                webhook_prod=webhook_prod,
                webhook_lower=webhook_lower,
                sender=sender,
            )
        else:
            _handle_service_impaired(
                event,
                ecs_client=ecs_client,
                ssm_client=ssm_client,
                maintenance_marker_parameter_name=maintenance_marker_parameter_name,
                patch_maintenance_window_id=patch_maintenance_window_id,
                name_prefix=name_prefix,
                aws_region=aws_region,
                webhook_prod=webhook_prod,
                webhook_lower=webhook_lower,
                sender=sender,
            )
    elif detail_type == "ECS Task State Change":
        _handle_task_stopped(
            event,
            ssm_client=ssm_client,
            maintenance_marker_parameter_name=maintenance_marker_parameter_name,
            patch_maintenance_window_id=patch_maintenance_window_id,
            name_prefix=name_prefix,
            aws_region=aws_region,
            webhook_prod=webhook_prod,
            webhook_lower=webhook_lower,
            sender=sender,
        )
    else:
        print(f"Unhandled event detail-type: {detail_type!r}", file=sys.stderr)


def handler(event, context):
    return main(event, context)
