"""What the model is allowed to see.

The agent's tool never hands the model a raw run record. `tool_payload` projects the spike's identifier-free summary into
decisions, statuses, waits and labels, and `validate` refuses any payload that still carries an e-mail, a principal, a
scoped concept / publication identifier, a `concept_version_id`, SQL text, a bundle path or a local filesystem path. A
refused payload raises: the model receives nothing rather than something that leaks.

Two summary shapes are accepted:
- the full path, `okf_bq_graph.publish_connected.summary(rec)`: a BigQuery publish, then the connected run nested
  under `connected`; the number is handed over only when the run verdict is `E2E_PUBLISH_CONNECTED`;
- `--consume-only`, `okf_bq_graph.connected.summary(out)`: the connected run alone, released only on `E2E_CONNECTED`.
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
FULL_PATH = "author/publish in BigQuery -> Catalog discovery -> pin -> governed retrieval -> access + revocation -> receipt -> enforcing consumer"


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


def is_full_path(summary: dict) -> bool:
    return "publish" in summary


def expected_verdict(summary: dict) -> str:
    return "E2E_PUBLISH_CONNECTED" if is_full_path(summary) else "E2E_CONNECTED"


def tool_payload(summary: dict) -> dict:
    """Project the run summary into the tool result the model reads."""
    full = is_full_path(summary)
    c = (summary.get("connected") or {}) if full else summary
    cases = c.get("cases") or {}
    approved = cases.get("connected-approved") or {}
    decision = approved.get("decision")
    live = summary.get("mode") == "live"
    ident = c.get("identity") or {}
    ok = summary.get("verdict") == expected_verdict(summary)
    withheld = None
    if decision != "RELEASED":
        withheld = "the enforcing consumer refused the approved request"
    elif not ok:
        what = "the publish, consumed-publication, access and revocation checks" if full else "the access and revocation checks"
        withheld = (f"run verdict {summary.get('verdict')} at {summary.get('broken_at')}: {what} did not all hold in this run, "
                    "so its number is not handed to the agent")
    payload = {
        "decision": decision,
        "answer": c.get("answer") if decision == "RELEASED" and ok else None,
        "withheld": withheld,
        "path": FULL_PATH if full else "consume-only: a publication and Catalog entry that already existed; nothing was published in this run",
        "run_verdict": summary.get("verdict"),
        "broken_at": summary.get("broken_at"),
        "run_id": summary.get("run_id"),
        "receipt": {"ref": c.get("receipt_ref"), "verdict": c.get("receipt_verdict")},
        "facts_readback": c.get("facts"),
        "cases": {name.replace("connected-", ""): v for name, v in cases.items()},
        "access_checks": c.get("access") or {},
        "identity": {"status": ident.get("status"), "jobs_by_role": {k: (v or {}).get("jobs") for k, v in (ident.get("roles") or {}).items()}},
        "unresolved_jobs": c.get("unresolved_jobs"),
        "teardown": c.get("teardown"),
        "labels": {
            "data": "synthetic invented Acme fixture; no customer data",
            "apis": "live GCP (BigQuery, Dataplex Catalog, IAM)" if live else "hermetic emulation, no cloud call",
            "engine": "relational fallback, not BigQuery Graph",
            "requester": "restricted service account through IAM impersonation",
            "receipt": "the SDK verifier with a requester-held key; no independent attester",
            "sample": "one run",
        },
        "evidence": f"evidence/{'publish-connected' if full else 'connected-e2e'}/{summary.get('run_id')}",
    }
    if full:
        p = summary.get("publish") or {}
        payload["connected_verdict"] = c.get("verdict")
        payload["consume_run_id"] = c.get("run_id")
        payload["publication"] = {
            "authority": "BigQuery",
            "states": p.get("states"),
            "ready": p.get("ready"),
            "rows": p.get("rows"),
            "head_switched": (p.get("head") or {}).get("state") == "SWITCHED",
            "author_jobs": len(p.get("author_jobs") or []),
            "author_identity": p.get("author_identity"),
            "catalog_pin": p.get("catalog_pin"),
            "consumer_served_this_publication": summary.get("consumed") == "MATCH",
            "originals": p.get("originals"),
            "cleanup": p.get("cleanup"),
        }
        payload["labels"]["publish"] = ("BigQuery is the publish authority; the Catalog entry is the discovery projection, "
                                        "written only after the head advanced")
        payload["labels"]["publication"] = ("content-addressed from the pinned source, deployed fresh into a run-owned dataset "
                                            "that is deleted after the run")
    return validate(payload)
