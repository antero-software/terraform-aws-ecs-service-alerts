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


def _handle_service_impaired(event, *, ecs_client, app_name, environment, aws_region, webhook_url, sender):
    # The 'resources' list will contain a list of ECS service ARNs, e.g.
    #
    #     arn:aws:ecs:eu-west-1:1234567890:service/pipeline/image_inferrer
    #
    # Extract the cluster/service name; in this case 'pipeline' and
    # 'image_inferrer'.
    for r in event["resources"]:
        _, cluster_name, service_name = r.split("/")

        # Fetch the last 5 service events to surface the failure reason.
        recent_events = []
        try:
            response = ecs_client.describe_services(
                cluster=cluster_name,
                services=[service_name],
            )
            services = response.get("services", [])
            if services:
                recent_events = [e["message"] for e in services[0].get("events", [])[:5]]
        except Exception as e:
            print(f"Failed to fetch ECS service events: {e}", file=sys.stderr)

        fields = [
            {
                "value": (
                    f"{service_name} is unable to consistently start tasks successfully. "
                    f"<https://{aws_region}.console.aws.amazon.com/ecs/v2/clusters/"
                    f"{cluster_name}/services/{service_name}/deployments?region={aws_region}"
                    f"|View in console>"
                )
            }
        ]

        if recent_events:
            fields.append({
                "title": "Recent Events",
                "value": "\n".join(f"• {e}" for e in recent_events),
            })

        _send_slack(webhook_url, {
            "username": f"{app_name}-ecs-tasks-alert",
            "icon_emoji": ":rotating_light:",
            "attachments": [
                {
                    "color": "danger",
                    "title": f"{cluster_name} / {service_name}",
                    "fields": fields,
                }
            ],
        }, sender)


def _handle_task_stopped(event, *, app_name, environment, aws_region, webhook_url, sender):
    detail = event["detail"]

    # Only alert for service tasks, not standalone tasks.
    group = detail.get("group", "")
    if not group.startswith("service:"):
        return
    service_name = group.split(":", 1)[1]

    cluster_name = detail["clusterArn"].split("/")[-1]

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

    fields = [
        {
            "value": (
                f"<https://{aws_region}.console.aws.amazon.com/ecs/v2/clusters/"
                f"{cluster_name}/services/{service_name}/deployments?region={aws_region}"
                f"|View in console>"
            )
        },
        {
            "title": "Stopped Reason",
            "value": detail.get("stoppedReason", "Unknown"),
        },
        {
            "title": "Crashed Containers",
            "value": "\n".join(container_lines),
        },
    ]

    _send_slack(webhook_url, {
        "username": f"{app_name}-ecs-tasks-alert",
        "icon_emoji": ":rotating_light:",
        "attachments": [
            {
                "color": "danger",
                "title": f"{cluster_name} / {service_name} — task crashed",
                "fields": fields,
            }
        ],
    }, sender)


@log_on_error
def main(event, _ctxt=None, *, sender: Optional[SlackSender] = None):
    if sender is None:
        sender = urllib.request.urlopen

    app_name = os.environ["APP_NAME"]
    aws_region = os.environ["AWS_REGION"]
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]

    sess = boto3.Session()
    ecs_client = sess.client("ecs", region_name=aws_region)

    detail_type = event.get("detail-type")

    if detail_type == "ECS Service Action":
        _handle_service_impaired(
            event,
            ecs_client=ecs_client,
            app_name=app_name,
            environment=environment,
            aws_region=aws_region,
            webhook_url=webhook_url,
            sender=sender,
        )
    elif detail_type == "ECS Task State Change":
        _handle_task_stopped(
            event,
            app_name=app_name,
            environment=environment,
            aws_region=aws_region,
            webhook_url=webhook_url,
            sender=sender,
        )
    else:
        print(f"Unhandled event detail-type: {detail_type!r}", file=sys.stderr)


def handler(event, context):
    return main(event, context)
