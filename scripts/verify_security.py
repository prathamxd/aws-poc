"""Checks the deployed AWS resources against the POC's security pass/fail rules.

Run from the repository root (inside your virtualenv, which has boto3):
    python scripts/verify_security.py
Prints PASS/FAIL per check and saves a Markdown report to docs/evidence/.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import REPO_ROOT, terraform_outputs

try:
    import boto3
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install -r requirements.txt")

# Actions that AWS only supports with Resource "*" (no resource-level permissions).
STAR_RESOURCE_OK = {
    "ecr:getauthorizationtoken",
    "ssm:getcommandinvocation",
    "ssm:listcommandinvocations",
}

results: list[tuple[str, str, bool, str]] = []


def check(check_id: str, name: str, ok: bool, detail: str = "") -> None:
    results.append((check_id, name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {check_id} {name} {('- ' + detail) if detail else ''}", flush=True)


def as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def role_findings(iam, role_name: str) -> tuple[list[str], list[str]]:
    """Return (problems, managed_policies) for an IAM role."""
    problems: list[str] = []
    for policy_name in iam.list_role_policies(RoleName=role_name)["PolicyNames"]:
        doc = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)["PolicyDocument"]
        for stmt in as_list(doc.get("Statement", [])):
            if stmt.get("Effect") != "Allow":
                continue
            actions = [a.lower() for a in as_list(stmt.get("Action", []))]
            resources = as_list(stmt.get("Resource", []))
            if any(a == "*" or a.endswith(":*") for a in actions):
                problems.append(f"{policy_name}: wildcard action {actions}")
            if "*" in resources and not set(actions) <= STAR_RESOURCE_OK:
                problems.append(f"{policy_name}: Resource '*' for {actions}")
    managed = [p["PolicyName"] for p in iam.list_attached_role_policies(RoleName=role_name)["AttachedPolicies"]]
    return problems, managed


def main() -> None:
    out = terraform_outputs()
    session = boto3.Session(region_name=out["aws_region"])
    rds, ec2, s3 = session.client("rds"), session.client("ec2"), session.client("s3")
    iam, sm = session.client("iam"), session.client("secretsmanager")

    # ---------------- RDS
    db = rds.describe_db_instances(DBInstanceIdentifier=out["rds_instance_id"])["DBInstances"][0]
    check("SEC-01", "RDS is NOT publicly accessible", db["PubliclyAccessible"] is False, f"PubliclyAccessible={db['PubliclyAccessible']}")
    check("SEC-02", "RDS storage is encrypted", db["StorageEncrypted"])
    check("SEC-03", "RDS master password managed in Secrets Manager", "MasterUserSecret" in db)
    subnet_ids = [s["SubnetIdentifier"] for s in db["DBSubnetGroup"]["Subnets"]]
    route_tables = ec2.describe_route_tables(Filters=[{"Name": "vpc-id", "Values": [db["DBSubnetGroup"]["VpcId"]]}])["RouteTables"]
    main_rt = next((rt for rt in route_tables if any(a.get("Main") for a in rt.get("Associations", []))), {"Routes": []})

    def route_table_for(subnet_id: str) -> dict:
        for rt in route_tables:
            if any(a.get("SubnetId") == subnet_id for a in rt.get("Associations", [])):
                return rt
        return main_rt

    internet_facing = [s for s in subnet_ids
                       if any(r.get("GatewayId", "").startswith("igw-") for r in route_table_for(s)["Routes"])]
    check("SEC-04", "RDS subnets are private (no route to an internet gateway)", not internet_facing,
          f"subnets={subnet_ids}" + (f" internet-facing={internet_facing}" if internet_facing else ""))

    rds_sg = ec2.describe_security_groups(GroupIds=[out["rds_security_group_id"]])["SecurityGroups"][0]
    cidr_rules = [r for r in rds_sg["IpPermissions"] if r.get("IpRanges") or r.get("Ipv6Ranges")]
    sources = {p["GroupId"] for r in rds_sg["IpPermissions"] for p in r.get("UserIdGroupPairs", [])}
    check(
        "SEC-05",
        "RDS security group allows PostgreSQL only from the app security group",
        not cidr_rules and sources == {out["app_security_group_id"]},
        f"sources={sorted(sources)} cidr_rules={len(cidr_rules)}",
    )

    # ---------------- EC2
    app_sg = ec2.describe_security_groups(GroupIds=[out["app_security_group_id"]])["SecurityGroups"][0]
    inbound = [(r.get("IpProtocol"), r.get("FromPort"), r.get("ToPort"), [i["CidrIp"] for i in r.get("IpRanges", [])])
               for r in app_sg["IpPermissions"]]
    ssh_open = any(p == "-1" or (f is not None and f <= 22 <= t) for p, f, t, _ in inbound)
    check("SEC-06", "No SSH (22) open - admin access via SSM Session Manager", not ssh_open, str(inbound))
    check("SEC-07", "EC2 exposes only HTTP 80", all(f == 80 and t == 80 for _, f, t, _ in inbound), str(inbound))

    inst = ec2.describe_instances(InstanceIds=[out["ec2_instance_id"]])["Reservations"][0]["Instances"][0]
    check("SEC-08", "IMDSv2 required on EC2", inst["MetadataOptions"]["HttpTokens"] == "required")
    check("SEC-09", "EC2 uses an IAM instance profile (no access keys on the server)", "IamInstanceProfile" in inst)
    volume_ids = [m["Ebs"]["VolumeId"] for m in inst.get("BlockDeviceMappings", []) if "Ebs" in m]
    volumes = ec2.describe_volumes(VolumeIds=volume_ids)["Volumes"] if volume_ids else []
    check("SEC-10", "EBS volumes encrypted", volumes and all(v["Encrypted"] for v in volumes))

    user_data_b64 = ec2.describe_instance_attribute(InstanceId=inst["InstanceId"], Attribute="userData")["UserData"].get("Value", "")
    user_data = base64.b64decode(user_data_b64).decode("utf-8", errors="ignore") if user_data_b64 else ""
    app_secret = json.loads(sm.get_secret_value(SecretId=out["app_secret_arn"])["SecretString"])
    db_secret = json.loads(sm.get_secret_value(SecretId=out["db_secret_arn"])["SecretString"])
    leaked = [n for n, v in (("admin_password", app_secret.get("admin_password")),
                             ("secret_key", app_secret.get("secret_key")),
                             ("db_password", db_secret.get("password"))) if v and v in user_data]
    check("SEC-11", "No secret values in EC2 user data (only secret ARNs)", not leaked, f"found={leaked}" if leaked else "")

    # ---------------- S3
    bucket = out["s3_bucket_name"]
    pab = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    check("SEC-12", "S3 Block Public Access fully enabled", all(pab.values()), str(pab))
    enc = s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"]
    check("SEC-13", "S3 default encryption enabled", bool(enc), enc[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"])
    policy = s3.get_bucket_policy(Bucket=bucket)["Policy"]
    check("SEC-14", "S3 bucket policy denies non-HTTPS access", "aws:SecureTransport" in policy)

    # ---------------- IAM least privilege
    roles = {"EC2 app role": out["ec2_role_name"], "Lambda role": out["lambda_role_name"]}
    if out.get("github_actions_role_name"):
        roles["GitHub Actions role"] = out["github_actions_role_name"]
    for n, (label, role_name) in enumerate(roles.items(), start=15):
        problems, managed = role_findings(iam, role_name)
        detail = "; ".join(problems) if problems else f"scoped inline policy; managed: {managed or 'none'}"
        check(f"SEC-{n}", f"{label} ({role_name}) has no wildcard permissions", not problems, detail)

    # ---------------- Repository hygiene
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        tracked = []
    if tracked:
        bad = [f for f in tracked if Path(f).name == ".env" or f.endswith((".tfstate", ".tfvars", ".pem")) or ".tfstate." in f]
        check("SEC-20", "No .env / tfstate / tfvars / key files committed", not bad, ", ".join(bad))
        key_re = re.compile(r"AKIA[0-9A-Z]{16}")
        hits = []
        for f in tracked:
            path = REPO_ROOT / f
            if path.is_file() and path.stat().st_size < 2_000_000:
                if key_re.search(path.read_text(encoding="utf-8", errors="ignore")):
                    hits.append(f)
        check("SEC-21", "No AWS access keys in tracked files", not hits, ", ".join(hits))
    else:
        print("[SKIP] repository checks (not a git repository yet)")

    write_report()


def write_report() -> None:
    passed = sum(1 for r in results if r[2])
    stamp = datetime.now(timezone.utc)
    lines = [
        f"# Security verification - {stamp:%Y-%m-%d %H:%M:%S} UTC",
        "",
        f"Result: **{passed}/{len(results)} checks passed**",
        "",
        "| ID | Check | Result | Detail |",
        "|----|-------|--------|--------|",
    ]
    lines += [f"| {i} | {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')[:180]} |" for i, n, ok, d in results]
    out_dir = REPO_ROOT / "docs" / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"security-check-{stamp:%Y%m%d-%H%M%S}.md"
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(results)} passed. Report saved to {out_file.relative_to(REPO_ROOT)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
