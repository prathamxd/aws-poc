"""Helpers shared by the scripts (standard library only, works on Windows/macOS/Linux)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = REPO_ROOT / "terraform"


def require_tools(*tools: str) -> None:
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        sys.exit(f"Missing required tool(s): {', '.join(missing)}. Install them and try again.")


def run(cmd: list[str], capture: bool = False, input_text: str | None = None) -> str:
    print("+", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd,
        check=True,
        text=True,
        input=input_text,
        capture_output=capture,
        cwd=REPO_ROOT,
    )
    return (result.stdout or "").strip() if capture else ""


def terraform_outputs() -> dict:
    """Return `terraform output -json` as a plain {name: value} dict."""
    raw = subprocess.run(
        ["terraform", f"-chdir={TERRAFORM_DIR}", "output", "-json"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    outputs = {k: v["value"] for k, v in json.loads(raw or "{}").items()}
    if not outputs:
        sys.exit("No Terraform outputs found. Run `terraform apply` in the terraform/ folder first.")
    return outputs


def admin_password(outputs: dict) -> str:
    secret = run(
        [
            "aws", "secretsmanager", "get-secret-value",
            "--region", outputs["aws_region"],
            "--secret-id", outputs["app_secret_arn"],
            "--query", "SecretString", "--output", "text",
        ],
        capture=True,
    )
    return json.loads(secret)["admin_password"]
