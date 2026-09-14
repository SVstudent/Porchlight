#!/usr/bin/env python
"""Create the Amazon Bedrock AgentCore Memory resource Porchlight uses for long-term neighbor memory.

Run once from backend/ with AWS credentials that allow bedrock-agentcore:CreateMemory / GetMemory:

    python scripts/create_agentcore_memory.py --region us-east-1

It prints the memory id. Put it in backend/.env:

    AGENTCORE_MEMORY_ID=<printed id>
    AWS_REGION=us-east-1

Strategies (namespace templates match the runtime default in app/agents/agentcore_memory.py):
  * semantic  -> /porchlight/neighbors/{actorId}/                       facts about each neighbor across episodes
  * summary   -> /porchlight/neighbors/{actorId}/episodes/{sessionId}/  one summary per neighbor per episode

Calls used (verified against bedrock_agentcore 1.22.0, bedrock_agentcore/memory/client.py):
  MemoryClient(region_name=...)
  MemoryClient.create_memory_and_wait(name, strategies, description=None, event_expiry_days=90,
                                      memory_execution_role_arn=None, ..., max_wait=300, poll_interval=10)
Creation can take a few minutes; the call polls until the memory is ACTIVE.
"""
from __future__ import annotations

import argparse
import sys

NAME_DEFAULT = "PorchlightNeighborMemory"
SEMANTIC_NAMESPACE = "/porchlight/neighbors/{actorId}/"
SUMMARY_NAMESPACE = "/porchlight/neighbors/{actorId}/episodes/{sessionId}/"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default=None, help="AWS region (default: boto3 session region, else us-west-2)")
    ap.add_argument("--name", default=NAME_DEFAULT, help="memory resource name (letters, digits, underscores)")
    ap.add_argument("--expiry-days", type=int, default=365, help="how long raw events are retained")
    ap.add_argument("--role-arn", default=None, help="optional memory execution role ARN")
    ap.add_argument("--max-wait", type=int, default=600, help="seconds to wait for the memory to become ACTIVE")
    args = ap.parse_args()

    from bedrock_agentcore.memory import MemoryClient  # fails clearly if the SDK is missing

    client = MemoryClient(region_name=args.region)
    strategies = [
        {"semanticMemoryStrategy": {
            "name": "NeighborFacts",
            "description": "Durable facts about how each neighbor responds to check-ins: which channel they answer, "
                           "how quickly, who answers for them, and what help they needed.",
            "namespaceTemplates": [SEMANTIC_NAMESPACE],
        }},
        {"summaryMemoryStrategy": {
            "name": "EpisodeSummaries",
            "description": "One summary per neighbor per hazard episode.",
            "namespaceTemplates": [SUMMARY_NAMESPACE],
        }},
    ]
    print(f"Creating memory {args.name!r} in {client.region_name} (this can take a few minutes)...", file=sys.stderr)
    memory = client.create_memory_and_wait(
        name=args.name,
        strategies=strategies,
        description="Porchlight neighbor check-in memory: one actor per neighbor, one session per hazard episode.",
        event_expiry_days=args.expiry_days,
        memory_execution_role_arn=args.role_arn,
        max_wait=args.max_wait,
    )
    memory_id = memory.get("memoryId") or memory.get("id")
    print(f"Memory is ACTIVE. Add to backend/.env:\n  AGENTCORE_MEMORY_ID={memory_id}\n  AWS_REGION={client.region_name}", file=sys.stderr)
    print(memory_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
