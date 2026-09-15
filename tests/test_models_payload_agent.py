import copy

import pytest

from okf_connected_e2e import agent as A
from okf_connected_e2e import cli as CLI
from okf_connected_e2e import models as M
from okf_connected_e2e import payload as P

SUMMARY = {
    "run_id": "e2e-20260915t070000z-0123abcd", "mode": "live", "engine": "fallback", "verdict": "E2E_CONNECTED", "broken_at": None,
    "answer": "[LIVE] Gross margin: $400.00 USD · VERIFIED", "receipt_ref": "<id:1a2b3c4d>", "receipt_verdict": "VERIFIED", "facts": "OK",
    "cases": {"connected-approved": {"decision": "RELEASED", "acceptance": "MET"},
              "connected-sql-substitution": {"decision": "REFUSED", "acceptance": "MET"},
              "connected-denied-intermediate": {"decision": "REFUSED", "acceptance": "MET"},
              "connected-unauthorized-output": {"decision": "REFUSED", "acceptance": "MET"},
              "connected-revocation": {"decision": "REFUSED", "acceptance": "MET"}},
    "access": {"catalog_before_grant": "DENIED", "catalog_grant_observed": "ALLOWED", "catalog_grant_waited_s": 70,
               "caller_is_requester": True, "revocation_observed": True, "fresh_request_after_revocation": "CATALOG_ERROR",
               "bypass_publication": "ERROR", "bypass_retrieval": "DENIED", "authorization_after_revocation": "DENIED",
               "receipt_launches_after_revocation": 0},
    "identity": {"status": "BOUND", "roles": {"graph": {"jobs": 60, "status": "BOUND"}, "receipt": {"jobs": 2, "status": "BOUND"}}},
    "unresolved_jobs": 0, "teardown": {"catalog": "VERIFIED", "broker": "VERIFIED"},
    "labels": {"data": "synthetic"}, "run_dir": "evidence/connected-e2e/e2e-20260915t070000z-0123abcd",
}

# publish_connected.summary(rec) shape: the BigQuery publish, then the connected summary nested under `connected`
FULL = {
    "run_id": "kp-20260915t090000z-ab12", "mode": "live", "runner": "okf_bq_graph.publish_connected/0.1.0",
    "verdict": "E2E_PUBLISH_CONNECTED", "broken_at": None, "consumed": "MATCH", "stopped_at": None,
    "publish": {"authority": "BigQuery", "dataset": "okf_kp_publish_kp_20260915t090000z_ab12", "publication_id": "pub_190192147fd7fd78",
                "states": ["PLANNED", "PREPARING", "BQ_STAGED", "BQ_COMMITTED", "KC_APPLIED", "COMPLETE"], "ready": "READY",
                "rows": {"nodes": 44, "edges": 109, "sections": 22},
                "head": {"state": "SWITCHED", "from": None, "to": "pub_190192147fd7fd78", "merge_job_id": "okf_cc_kp_merge_head_0123"},
                "author_jobs": [{"role": "load_nodes", "job_id": "okf_cc_kp_load_nodes_0123", "state": "DONE"},
                                {"role": "merge_head", "job_id": "okf_cc_kp_merge_head_0123", "state": "DONE"}],
                "author_identity": "BOUND", "catalog_pin": "OK", "entry": "projects/p/locations/l/entryGroups/g/entries/acme-retail-kp-publish/x/metrics/gross-margin",
                "originals": "UNCHANGED", "cleanup": "COMPLETE"},
    "connected": copy.deepcopy(SUMMARY),
    "run_dir": "evidence/publish-connected/kp-20260915t090000z-ab12",
}


def test_default_model_is_gemini_3_8_flash_and_older_families_are_refused():
    assert M.resolve_model({}) == "gemini-3.8-flash"
    assert M.resolve_model({"DEMO_MODEL_ID": "gemini-3.8-flash-high"}) == "gemini-3.8-flash-high"
    for bad in ("gemini-2.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-001", "gpt-5", ""):
        with pytest.raises(M.ModelRefused):
            M.check_model(bad)
    with pytest.raises(M.ModelRefused):
        M.resolve_model({"DEMO_MODEL_ID": "gemini-2.5-flash"})


def test_tool_payload_is_identifier_free_and_keeps_the_decision():
    p = P.tool_payload(SUMMARY)
    assert p["decision"] == "RELEASED" and p["answer"].endswith("VERIFIED") and p["cases"]["revocation"]["decision"] == "REFUSED"
    assert p["access_checks"]["receipt_launches_after_revocation"] == 0 and p["identity"]["jobs_by_role"] == {"graph": 60, "receipt": 2}
    assert "consume-only" in p["path"] and "publication" not in p
    assert P.leaks(p) == []


def test_full_path_payload_carries_the_bigquery_publish_without_identifiers():
    p = P.tool_payload(FULL)
    assert p["decision"] == "RELEASED" and p["answer"].endswith("VERIFIED") and p["run_verdict"] == "E2E_PUBLISH_CONNECTED"
    pub = p["publication"]
    assert pub["authority"] == "BigQuery" and pub["ready"] == "READY" and pub["head_switched"] is True
    assert pub["author_jobs"] == 2 and pub["consumer_served_this_publication"] is True and pub["cleanup"] == "COMPLETE"
    assert p["path"].startswith("author/publish in BigQuery") and p["evidence"] == "evidence/publish-connected/kp-20260915t090000z-ab12"
    assert P.leaks(p) == []


def test_full_path_answer_is_withheld_when_publish_or_teardown_did_not_hold():
    """The consumer released and the connected run connected, but the full run did not: no number for the agent."""
    s = dict(copy.deepcopy(FULL), verdict="E2E_INCOMPLETE", broken_at="cleanup")
    p = P.tool_payload(s)
    assert p["decision"] == "RELEASED" and p["answer"] is None and "E2E_INCOMPLETE" in p["withheld"] and "publish" in p["withheld"]
    s = dict(copy.deepcopy(FULL), verdict="E2E_BROKEN", broken_at="consumed", consumed="MISMATCH")
    assert P.tool_payload(s)["answer"] is None and P.tool_payload(s)["publication"]["consumer_served_this_publication"] is False


def test_answer_is_withheld_unless_released():
    s = copy.deepcopy(SUMMARY)
    s["cases"]["connected-approved"]["decision"] = "REFUSED"
    p = P.tool_payload(s)
    assert p["answer"] is None and "refused" in p["withheld"]


def test_answer_is_withheld_when_the_run_did_not_connect():
    """The first live run released the approved number while a later access case failed: the agent must not get it."""
    s = dict(copy.deepcopy(SUMMARY), verdict="E2E_BROKEN", broken_at="connected-unauthorized-output")
    p = P.tool_payload(s)
    assert p["decision"] == "RELEASED" and p["answer"] is None and "E2E_BROKEN" in p["withheld"]
    assert P.tool_payload(SUMMARY)["withheld"] is None


@pytest.mark.parametrize("field,value,hit", [
    ("broken_at", "okf-receipt-restricted@test-project.iam.gserviceaccount.com", "email"),
    ("broken_at", "acme_retail|pub_190192147fd7fd78|Concept|metrics/gross-margin", "scoped_identifier"),
    ("broken_at", "pub_190192147fd7fd78", "publication_id"),
    ("broken_at", "SELECT SUM(x) FROM `p.d.t` WHERE y", "sql_text"),
    ("broken_at", "computations/gross-margin-period.md", "bundle_path"),
    ("broken_at", "/Users/someone/evidence", "local_path"),
    ("broken_at", "concept_version_id=abc", "concept_version_id"),
])
def test_a_leaking_payload_is_refused(field, value, hit):
    for base in (SUMMARY, FULL):
        s = dict(copy.deepcopy(base), **{field: value})
        with pytest.raises(P.PayloadLeak) as e:
            P.tool_payload(s)
        assert hit in e.value.hits


def test_the_tool_refuses_an_undeclared_period_without_running():
    calls = []
    tool = A.make_tool(lambda: calls.append(1) or FULL)
    r = tool("2025-12")
    assert r["decision"] == "REFUSED" and r["answer"] is None and calls == []
    seen = []
    tool = A.make_tool(lambda: FULL, on_payload=seen.append)
    assert tool("January 2026")["decision"] == "RELEASED" and len(seen) == 1
    assert A.is_declared_period("2026-01") and A.is_declared_period("jan 2026") and not A.is_declared_period("2026-02")


def test_cli_defaults_to_the_full_path_and_labels_consume_only():
    args = CLI.build_parser().parse_args(["run", "--live"])
    assert args.consume_only is False
    assert CLI.build_parser().parse_args(["agent", "--consume-only"]).consume_only is True
    full = CLI.banner("live", "gemini-3.8-flash", {"head": "abcdef0123"})
    assert "Author/Publish (BigQuery)" in full and "publish_connected @ abcdef0" in full and "READY" in full
    only = CLI.banner("live", None, {"head": "abcdef0123"}, consume_only=True)
    assert "consume-only" in only and "nothing published in this run" in only
    assert P.expected_verdict(FULL) == "E2E_PUBLISH_CONNECTED" and P.expected_verdict(SUMMARY) == "E2E_CONNECTED"
