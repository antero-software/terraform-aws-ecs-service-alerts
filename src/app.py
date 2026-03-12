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


def _handle_service_impaired(event, *, ecs_client, name_prefix, aws_region, webhook_prod, webhook_lower, sender):
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


def _handle_deployment_failed(event, *, ecs_client, name_prefix, aws_region, webhook_prod, webhook_lower, sender):
    # Same ARN structure as service action events:
    #   arn:aws:ecs:region:account:service/cluster/service
    for r in event["resources"]:
        _, cluster_name, service_name = r.split("/")

        webhook_url = _pick_webhook(cluster_name, webhook_prod=webhook_prod, webhook_lower=webhook_lower)

        # Fetch recent events to surface why the deployment failed.
        recent_events = _fetch_recent_events(ecs_client, cluster_name, service_name)

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


def _handle_task_stopped(event, *, name_prefix, aws_region, webhook_prod, webhook_lower, sender):
    detail = event["detail"]

    # Only alert for service tasks, not standalone tasks.
    group = detail.get("group", "")
    if not group.startswith("service:"):
        return
    service_name = group.split(":", 1)[1]

    cluster_name = detail["clusterArn"].split("/")[-1]
    stop_code = detail.get("stopCode", "")

    webhook_url = _pick_webhook(cluster_name, webhook_prod=webhook_prod, webhook_lower=webhook_lower)

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
    # Skip graceful shutdowns — only alert when at least one container
    # exited with a non-zero exit code.
    crashed = [
        c for c in detail.get("containers", [])
        if c.get("exitCode") is not None and c.get("exitCode") != 0
    ]
    if not crashed:
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

    sess = boto3.Session()
    ecs_client = sess.client("ecs", region_name=aws_region)

    detail_type = event.get("detail-type")
    event_name = event.get("detail", {}).get("eventName")

    if detail_type == "ECS Service Action":
        if event_name == "SERVICE_DEPLOYMENT_FAILED":
            _handle_deployment_failed(
                event,
                ecs_client=ecs_client,
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
                name_prefix=name_prefix,
                aws_region=aws_region,
                webhook_prod=webhook_prod,
                webhook_lower=webhook_lower,
                sender=sender,
            )
    elif detail_type == "ECS Task State Change":
        _handle_task_stopped(
            event,
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
