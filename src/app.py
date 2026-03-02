import functools
import json
import os
import sys
import urllib.request
from urllib.error import HTTPError
from typing import Any, Callable, Optional


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


@log_on_error
def main(event, _ctxt=None, *, sender: Optional[SlackSender] = None):
    if sender is None:
        sender = urllib.request.urlopen

    app_name = os.environ["APP_NAME"]
    environment = os.environ["ENVIRONMENT"]
    aws_region = os.environ["AWS_REGION"]
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]

    # The 'resources' list will contain a list of ECS service ARNs, e.g.
    #
    #     arn:aws:ecs:eu-west-1:1234567890:service/pipeline/image_inferrer
    #
    # Extract the cluster/service name; in this case 'pipeline' and
    # 'image_inferrer'.
    for r in event["resources"]:
        _, cluster_name, service_name = r.split("/")

        slack_payload = {
            "username": f"{app_name}-{environment}-ecs-tasks-alert",
            "icon_emoji": ":rotating_light:",
            "attachments": [
                {
                    "color": "danger",
                    "title": f"{cluster_name} / {service_name}",
                    "fields": [
                        {
                            "value": f"{service_name} is unable to consistently start tasks successfully. <https://{aws_region}.console.aws.amazon.com/ecs/v2/clusters/{cluster_name}/services/{service_name}/deployments?region={aws_region}|View in console>"
                        }
                    ],
                }
            ],
        }

        print("Sending message %s" % json.dumps(slack_payload))

        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(slack_payload).encode("utf8"),
            headers={"Content-Type": "application/json"},
        )

        try:
            sender(req)
        except HTTPError as err:
            raise Exception(f"{err} - {err.read()}")

def handler(event, context):
    return main(event, context)
