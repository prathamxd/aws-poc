"""Manual deployment (same steps as the GitHub Actions deploy workflow).

Builds the Docker image, pushes it to Amazon ECR and restarts TicketDesk on EC2
through SSM Run Command, then waits until /health reports the new version.

Usage (from the repository root, after `terraform apply`):
    python scripts/deploy.py
Requires: terraform, aws CLI v2 (configured), docker (running), git.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

from _common import require_tools, run, terraform_outputs


def version_tag() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        if sha:
            return sha
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return datetime.now(timezone.utc).strftime("manual-%Y%m%d%H%M%S")


def wait_for_version(url: str, version: str, timeout: int = 240) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=5) as resp:
                body = json.loads(resp.read())
                print(f"  /health -> {body}")
                if body.get("status") == "ok" and body.get("version") == version:
                    return True
        except Exception as exc:  # app restarting
            print(f"  waiting for app... ({exc.__class__.__name__})")
        time.sleep(5)
    return False


def main() -> None:
    require_tools("terraform", "aws", "docker")
    out = terraform_outputs()
    region = out["aws_region"]
    repo_url = out["ecr_repository_url"]
    registry = repo_url.split("/")[0]
    instance_id = out["ec2_instance_id"]
    app_url = out["app_url"]
    version = version_tag()

    print(f"\n== Deploying TicketDesk {version} to {instance_id} ({region})\n")

    password = run(["aws", "ecr", "get-login-password", "--region", region], capture=True)
    run(["docker", "login", "--username", "AWS", "--password-stdin", registry], input_text=password)

    # --platform keeps the image x86_64 even when built on an Apple Silicon Mac (EC2 is t3 = x86_64)
    run([
        "docker", "build", "--platform", "linux/amd64",
        "--build-arg", f"APP_VERSION={version}",
        "-t", f"{repo_url}:{version}", "-t", f"{repo_url}:latest", ".",
    ])
    run(["docker", "push", f"{repo_url}:{version}"])
    run(["docker", "push", f"{repo_url}:latest"])

    command_id = run([
        "aws", "ssm", "send-command", "--region", region,
        "--instance-ids", instance_id,
        "--document-name", "AWS-RunShellScript",
        "--comment", f"TicketDesk deploy {version}",
        "--parameters", '{"commands":["systemctl restart ticketdesk"]}',
        "--query", "Command.CommandId", "--output", "text",
    ], capture=True)
    run(["aws", "ssm", "wait", "command-executed", "--region", region,
         "--command-id", command_id, "--instance-id", instance_id])

    print(f"\n== Waiting for {app_url}/health to report version {version}")
    if wait_for_version(app_url, version):
        print(f"\nDeployed successfully: {app_url}")
    else:
        sys.exit("\nThe new version did not become healthy. Check CloudWatch log group /ticketdesk/app "
                 "or run: sudo journalctl -u ticketdesk -n 100 (via SSM Session Manager).")


if __name__ == "__main__":
    main()
