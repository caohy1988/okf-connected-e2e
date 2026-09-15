import copy

import pytest

from okf_connected_e2e import agent as A
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
    assert P.leaks(p) == []


def test_answer_is_withheld_unless_released():
    s = copy.deepcopy(SUMMARY)
    s["cases"]["connected-approved"]["decision"] = "REFUSED"
    assert P.tool_payload(s)["answer"] is None


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
    s = dict(SUMMARY, **{field: value})
    with pytest.raises(P.PayloadLeak) as e:
        P.tool_payload(s)
    assert hit in e.value.hits


def test_the_tool_refuses_an_undeclared_period_without_running():
    calls = []
    tool = A.make_tool(lambda: calls.append(1) or SUMMARY)
    r = tool("2025-12")
    assert r["decision"] == "REFUSED" and r["answer"] is None and calls == []
    seen = []
    tool = A.make_tool(lambda: SUMMARY, on_payload=seen.append)
    assert tool("January 2026")["decision"] == "RELEASED" and len(seen) == 1
    assert A.is_declared_period("2026-01") and A.is_declared_period("jan 2026") and not A.is_declared_period("2026-02")
