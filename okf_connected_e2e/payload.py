"""What the model is allowed to see.

The agent's tool never hands the model a raw run record. `tool_payload` projects the spike's identifier-free
`connected.summary()` into decisions, statuses, waits and labels, and `validate` refuses any payload that still carries
an e-mail, a principal, a scoped concept / publication identifier, a `concept_version_id`, SQL text, a bundle path or a
local filesystem path. A refused payload raises: the model receives nothing rather than something that leaks.
"""
from __future__ import annotations

import json
import re
from typing import Any

FORBIDDEN = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "principal": re.compile(r"serviceAccount:|user:|okf-receipt-restricted|iam\.gserviceaccount"),
    "scoped_identifier": re.compile(r"\|(Concept|Section|Source|Actor|Artifact|LogEntry)\|"),
    "publication_id": re.compile(r"\bpub_[0-9a-f]{16}\b"),
    "concept_version_id": re.compile(r"concept_version_id", re.IGNORECASE),
    "sql_text": re.compile(r"\bSELECT\b|\bFROM `|\bWHERE\b|\bGROUP BY\b|\bJOIN\b"),
    "bundle_path": re.compile(r"\b[\w-]+/[\w./-]+\.md\b"),
    "local_path": re.compile(r"/Users/|/home/|~/|/private/"),
}


class PayloadLeak(ValueError):
    def __init__(self, hits: list[str]):
        super().__init__(f"tool payload refused: it carries {', '.join(hits)}")
        self.hits = hits


def leaks(obj: Any) -> list[str]:
    text = json.dumps(obj, default=str, ensure_ascii=False)
    return sorted(name for name, rx in FORBIDDEN.items() if rx.search(text))


def validate(obj: Any) -> Any:
    hits = leaks(obj)
    if hits:
        raise PayloadLeak(hits)
    return obj


def tool_payload(summary: dict) -> dict:
    """Project `okf_bq_graph.connected.summary(out)` into the tool result the model reads."""
    cases = summary.get("cases") or {}
    approved = cases.get("connected-approved") or {}
    decision = approved.get("decision")
    live = summary.get("mode") == "live"
    ident = summary.get("identity") or {}
    payload = {
        "decision": decision,
        "answer": summary.get("answer") if decision == "RELEASED" else None,
        "run_verdict": summary.get("verdict"),
        "broken_at": summary.get("broken_at"),
        "run_id": summary.get("run_id"),
        "receipt": {"ref": summary.get("receipt_ref"), "verdict": summary.get("receipt_verdict")},
        "facts_readback": summary.get("facts"),
        "cases": {name.replace("connected-", ""): v for name, v in cases.items()},
        "access_checks": summary.get("access") or {},
        "identity": {"status": ident.get("status"), "jobs_by_role": {k: (v or {}).get("jobs") for k, v in (ident.get("roles") or {}).items()}},
        "unresolved_jobs": summary.get("unresolved_jobs"),
        "teardown": summary.get("teardown"),
        "labels": {
            "data": "synthetic invented Acme fixture; no customer data",
            "apis": "live GCP (Dataplex Catalog, BigQuery, IAM)" if live else "hermetic emulation, no cloud call",
            "engine": "relational fallback, not BigQuery Graph",
            "requester": "restricted service account through IAM impersonation",
            "receipt": "the SDK verifier with a requester-held key; no independent attester",
            "sample": "one run",
        },
        "evidence": f"evidence/connected-e2e/{summary.get('run_id')}",
    }
    return validate(payload)
