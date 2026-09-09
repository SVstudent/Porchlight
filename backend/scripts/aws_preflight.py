#!/usr/bin/env python3
"""Check that this machine can actually run Porchlight on Amazon Bedrock, then write backend/.env.

Run it after signing in:

    aws login                 # browser sign-in, temporary refreshing credentials
    python scripts/aws_preflight.py            # check only
    python scripts/aws_preflight.py --write    # also update backend/.env

It verifies, in order: credentials resolve, Bedrock is reachable, which Anthropic models this account may
invoke, that a real invocation succeeds through the Strands SDK, and whether AgentCore Runtime has any quota.
Nothing is written unless --write is passed, and only the model keys are touched.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ENV_PATH = BACKEND / ".env"

# Preference order: newest and cheapest-capable first. The first id the account can invoke wins.
PREFERRED = [
    "global.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-sonnet-4-6",
    "anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-haiku-4-5",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
]

OK, WARN, BAD = "PASS", "WARN", "FAIL"
results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    mark = {OK: "  ok  ", WARN: " warn ", BAD: " FAIL "}[status]
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def aws(*args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(["aws", *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except FileNotFoundError:
        return 127, "aws CLI not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def check_cli() -> None:
    code, out = aws("--version", timeout=30)
    if code != 0:
        record("AWS CLI installed", BAD, out)
        return
    m = re.search(r"aws-cli/(\d+)\.", out)
    major = int(m.group(1)) if m else 0
    if major >= 2:
        record("AWS CLI installed", OK, out.split()[0])
    else:
        record("AWS CLI installed", WARN, f"{out.split()[0]} — v2 is needed for `aws login`")


def check_shadowing_keys() -> None:
    """Static keys in ~/.aws/credentials win over a browser sign-in for the same profile.

    This is the failure that looks like nothing at all: `aws login` reports success, and every call still
    comes back InvalidClientTokenId, because the credential chain never reaches the session.
    """
    path = Path.home() / ".aws" / "credentials"
    if not path.exists():
        return
    profile = os.environ.get("AWS_PROFILE", "default")
    try:
        text = path.read_text()
    except OSError:
        return
    section = re.search(rf"^\[{re.escape(profile)}\]$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if section and "aws_access_key_id" in section.group(1):
        record(
            "No stale keys shadowing the sign-in", WARN,
            f"[{profile}] in ~/.aws/credentials has static keys that take priority over `aws login`. "
            f"If sign-in appears to work but calls still fail: mv ~/.aws/credentials ~/.aws/credentials.bak",
        )


def check_identity() -> str | None:
    code, out = aws("sts", "get-caller-identity", "--output", "json")
    if code != 0:
        record("Credentials resolve", BAD, out.splitlines()[-1][:160])
        check_shadowing_keys()
        print("\n  Sign in first:  aws login", flush=True)
        print("  If your account is IAM Identity Center:  aws configure sso\n", flush=True)
        return None
    ident = json.loads(out)
    record("Credentials resolve", OK, f"account {ident['Account']} as {ident['Arn'].split('/')[-1]}")
    return ident["Account"]


def check_region() -> str:
    code, out = aws("configure", "get", "region", timeout=30)
    region = out.strip() if code == 0 and out.strip() else "us-east-1"
    record("Region", OK, region)
    return region


def check_models(region: str) -> list[str]:
    code, out = aws("bedrock", "list-foundation-models", "--region", region,
                    "--by-provider", "anthropic", "--output", "json")
    if code != 0:
        record("Bedrock reachable", BAD, out.splitlines()[-1][:160])
        return []
    ids = [m["modelId"] for m in json.loads(out).get("modelSummaries", [])]
    if not ids:
        record("Anthropic models listed", BAD, "none returned; request model access in the Bedrock console")
        return []
    record("Bedrock reachable", OK, f"{len(ids)} Anthropic models listed")

    # Inference profiles are what you actually invoke for the newer models.
    code, out = aws("bedrock", "list-inference-profiles", "--region", region, "--output", "json")
    if code == 0:
        for p in json.loads(out).get("inferenceProfileSummaries", []):
            pid = p.get("inferenceProfileId", "")
            if "anthropic" in pid and pid not in ids:
                ids.append(pid)
    return ids


def pick_model(available: list[str]) -> str | None:
    for want in PREFERRED:
        if want in available:
            return want
    claude = [i for i in available if "claude" in i.lower()]
    return claude[0] if claude else None


def check_invoke(model_id: str, region: str) -> bool:
    """The only check that proves the account can actually run the agents."""
    try:
        sys.path.insert(0, str(BACKEND))
        from strands import Agent
        from strands.models import BedrockModel
    except Exception as e:  # noqa: BLE001
        record("Strands SDK importable", BAD, str(e)[:160])
        return False
    try:
        agent = Agent(model=BedrockModel(model_id=model_id, region_name=region, temperature=0),
                      callback_handler=None, system_prompt="Reply with exactly: READY")
        reply = str(agent("Say READY.")).strip()
        record("Live model invocation", OK, f"{model_id} replied {reply[:40]!r}")
        return True
    except Exception as e:  # noqa: BLE001
        record("Live model invocation", BAD, f"{model_id}: {str(e)[:200]}")
        return False


def check_agentcore_quota(region: str) -> None:
    """New accounts often have AgentCore Runtime quota at 0. Optional, so this only warns."""
    code, out = aws("service-quotas", "list-service-quotas", "--service-code", "bedrock-agentcore",
                    "--region", region, "--output", "json", timeout=60)
    if code != 0:
        record("AgentCore quota", WARN, "could not read quotas (AgentCore is optional)")
        return
    try:
        quotas = json.loads(out).get("Quotas", [])
    except json.JSONDecodeError:
        record("AgentCore quota", WARN, "unexpected response (AgentCore is optional)")
        return
    runtimes = [q for q in quotas if "runtime" in q.get("QuotaName", "").lower()]
    if not runtimes:
        record("AgentCore quota", WARN, "no runtime quota found (AgentCore is optional)")
        return
    q = runtimes[0]
    value = q.get("Value", 0)
    status = OK if value and value > 0 else WARN
    record("AgentCore quota", status, f"{q['QuotaName']} = {value:g}"
           + ("" if value else "; request an increase to deploy to AgentCore"))


def check_ses(region: str) -> None:
    code, out = aws("ses", "list-identities", "--region", region, "--output", "json", timeout=45)
    if code != 0:
        record("SES identities", WARN, "not reachable (email channel optional)")
        return
    ids = json.loads(out).get("Identities", [])
    record("SES identities", OK if ids else WARN,
           ", ".join(ids[:3]) if ids else "none verified yet (email channel optional)")


def write_env(model_id: str, region: str) -> None:
    if not ENV_PATH.exists():
        example = BACKEND / ".env.example"
        ENV_PATH.write_text(example.read_text() if example.exists() else "")
        print(f"\ncreated {ENV_PATH} from .env.example", flush=True)
    lines = ENV_PATH.read_text().splitlines()
    updates = {"MODEL_PROVIDER": "bedrock", "BEDROCK_MODEL_ID": model_id, "AWS_REGION": region}
    seen = set()
    out = []
    for line in lines:
        m = re.match(r"^\s*#?\s*([A-Z_]+)=", line)
        key = m.group(1) if m else None
        if key in updates and key not in seen:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(out) + "\n")
    print(f"\nwrote to {ENV_PATH}:", flush=True)
    for key, val in updates.items():
        print(f"  {key}={val}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify this machine can run Porchlight on Amazon Bedrock.")
    ap.add_argument("--write", action="store_true", help="update backend/.env with the working model settings")
    ap.add_argument("--region", default=None, help="override the region to test")
    ap.add_argument("--model", default=None, help="test a specific model id instead of auto-picking")
    args = ap.parse_args()

    print("Porchlight AWS preflight\n" + "=" * 60, flush=True)
    check_cli()
    if check_identity() is None:
        return 1
    region = args.region or check_region()

    available = check_models(region)
    model_id = args.model or pick_model(available)
    if not model_id:
        record("Model selected", BAD, "no Claude model available to this account")
        print("\n  Open the Bedrock console > Model access and request an Anthropic model.\n", flush=True)
        return 1
    record("Model selected", OK, model_id)

    invoked = check_invoke(model_id, region)
    check_agentcore_quota(region)
    check_ses(region)

    print("\n" + "=" * 60, flush=True)
    failures = [r for r in results if r[1] == BAD]
    if invoked and args.write:
        write_env(model_id, region)
    elif invoked:
        print(f"Ready. Run again with --write to set these in backend/.env:\n"
              f"  MODEL_PROVIDER=bedrock\n  BEDROCK_MODEL_ID={model_id}\n  AWS_REGION={region}", flush=True)

    if failures:
        print(f"\n{len(failures)} blocking problem(s): " + ", ".join(f[0] for f in failures), flush=True)
        return 1
    print("\nAll blocking checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
