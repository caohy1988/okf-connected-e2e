"""okf-e2e: run the RFC's full path on its own (`run`) or behind the ADK agent (`agent`).

    okf-e2e bootstrap                       # sparse checkout of the spike package at the pinned commit into ./.spike
    okf-e2e run --hermetic                  # no cloud: in-memory publish, policy emulation, oracle engine, SDK SYNTHETIC emulation
    okf-e2e run --live                      # test-project-0728-467323: publish in BigQuery, then live Catalog, BigQuery, IAM, receipt CLI
    okf-e2e agent --live ["question"]       # Gemini 3.8 Flash (Vertex AI) calls the one tool that performs the live run
    okf-e2e run --live --consume-only       # the PR #1 connected run alone, against a publication that already existed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from . import __version__
from . import spike as S
from .models import DEFAULT_LOCATION, ModelRefused, resolve_model
from .payload import expected_verdict, leaks

PROJECT = "test-project-0728-467323"
DEFAULT_ACME = "/Users/haiyuancao/knowledge-catalog/okf/bundles/acme_retail"
DEFAULT_QUESTION = "What was Acme's gross margin for January 2026, and can I trust the number?"
FULL_PATH = "Author/Publish (BigQuery) → Catalog discovery → pin → retrieval → access + revocation → receipt → consumer"
_TTY = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def banner(mode: str, model: Optional[str], spike: dict, consume_only: bool = False) -> str:
    live = mode == "live"
    rows = [
        ("model", f"{model} (Vertex AI, {DEFAULT_LOCATION})" if model else "none (runner only)"),
        ("project", f"{PROJECT} · " + ("live GCP APIs: BigQuery, Dataplex Catalog, IAM" if live else "hermetic emulation, no cloud call")),
        ("data", "synthetic Acme fixture · no customer data"),
        ("publish", "consume-only: a publication and Catalog entry that already existed (nothing published in this run)" if consume_only
         else "in BigQuery (authority): run-owned dataset, READY on full-row readback, atomic head MERGE; Catalog pin written after"),
        ("requester", "restricted service account via IAM impersonation"),
        ("engine", "relational fallback on the published tables (not BigQuery Graph)"),
        ("runner", f"okf_bq_graph.{'connected' if consume_only else 'publish_connected'} @ {str(spike.get('head') or '?')[:7]} · okf-connected-e2e {__version__}"),
    ]
    width = max(len(k) for k, _ in rows)
    title = ("OKF connected end-to-end (consume-only) · Catalog → publication → retrieval → receipt → consumer, with access + revocation"
             if consume_only else f"OKF RFC full path · {FULL_PATH}")
    lines = [_c("┌─ " + title, "1")]
    lines += [f"│ {k:<{width}}  {v}" for k, v in rows]
    lines.append("└" + "─" * 78)
    return "\n".join(lines)


def _runner(args: argparse.Namespace, spike: dict):
    from okf_bq_graph import BUNDLE_ID, SOURCE_PIN
    from okf_bq_graph import chain as CH
    from okf_bq_graph import connected as E2E
    from okf_bq_graph.catalog import CatalogConfig

    sdk_root = args.sdk_root or CH.sdk_root()
    acme_root = args.acme_root or os.environ.get("OKF_ACME_ROOT", DEFAULT_ACME)
    state: dict[str, Any] = {}

    if args.consume_only:
        cfg = CatalogConfig()
        out_dir = Path(args.out) if args.out else Path(spike["root"]) / "evidence" / "connected-e2e"

        def run() -> dict:
            if args.live:
                env = E2E.LiveEnv(CH.sdk_publication(sdk_root), sdk_root, cfg, wait_s=args.wait_s, sdk_python=args.sdk_python)
            else:
                from okf_bq_graph.compile import compile_bundle
                env = E2E.HermeticEnv(compile_bundle(acme_root, BUNDLE_ID, SOURCE_PIN), sdk_root, cfg)
            out = E2E.run_connected(env, sdk_root, acme_root, out_dir=out_dir, cfg=cfg, progress=E2E.print_progress)
            state["out"] = out
            state["summary"] = E2E.summary(out)
            return state["summary"]
        return run, state

    from okf_bq_graph import publish_connected as PCN
    out_dir = Path(args.out) if args.out else Path(spike["root"]) / "evidence" / "publish-connected"

    def run() -> dict:
        rec = PCN.run(args.live, sdk_root, acme_root, out_dir=out_dir, wait_s=args.wait_s, sdk_python=args.sdk_python, progress=E2E.print_progress)
        state["out"] = rec
        state["summary"] = PCN.summary(rec)
        return state["summary"]
    return run, state


def _run_dir(spike: dict, out: dict) -> Path:
    p = Path(out.get("run_dir") or "")
    return p if p.is_absolute() else Path(spike["root"]) / p


def _print_connected(s: dict) -> None:
    print(_c("consumer decisions", "1"))
    for name, v in (s.get("cases") or {}).items():
        colour = "32" if v.get("acceptance") == "MET" else "31"
        print(f"  {name:32s} {str(v.get('decision')):9s} acceptance={_c(str(v.get('acceptance')), colour)}")
    a = s.get("access") or {}
    print(_c("access and revocation", "1"))
    print(f"  catalog before grant={a.get('catalog_before_grant')} · after grant={a.get('catalog_grant_observed')} ({a.get('catalog_grant_waited_s')}s) · caller is requester={a.get('caller_is_requester')}")
    print(f"  after revocation: fresh request={a.get('fresh_request_after_revocation')} · bypass publication={a.get('bypass_publication')} · "
          f"bypass retrieval={a.get('bypass_retrieval')} · authorization={a.get('authorization_after_revocation')} · receipt launches={a.get('receipt_launches_after_revocation')}")
    ident = s.get("identity") or {}
    roles = ", ".join(f"{k} {v.get('jobs')}" for k, v in (ident.get("roles") or {}).items())
    print(f"  identity={ident.get('status')} ({roles}) · unresolved jobs={s.get('unresolved_jobs')} · teardown={s.get('teardown')}")
    print(f"  connected verdict {s.get('verdict')}" + (f" (broken_at {s.get('broken_at')})" if s.get("broken_at") else "") + f" · consume run {s.get('run_id')}")


def _print_summary(s: dict) -> None:
    full = "publish" in s
    if full:
        p = s["publish"]
        h = p.get("head") or {}
        print(_c("\npublish (BigQuery is the authority)", "1"))
        print(f"  states {' → '.join(p.get('states') or [])} · {p.get('ready')} rows={p.get('rows')} · dataset {p.get('dataset')}")
        print(f"  head {h.get('from')} → {h.get('to')} ({h.get('state')}) · merge job {h.get('merge_job_id')}")
        print(f"  author jobs {len(p.get('author_jobs') or [])} (identity {p.get('author_identity')}) · catalog pin {p.get('catalog_pin')} · "
              f"consumer served this publication: {s.get('consumed')} · originals {p.get('originals')} · cleanup {p.get('cleanup')}")
        c = s.get("connected") or {}
        if c.get("cases"):
            _print_connected(c)
    else:
        print()
        _print_connected(s)
    verdict = str(s.get("verdict"))
    print(_c(f"verdict {verdict}", "1;32" if verdict == expected_verdict(s) else "1;31") + (f" (broken_at {s.get('broken_at')})" if s.get("broken_at") else "")
          + f" · run {s.get('run_id')}")


def cmd_run(args: argparse.Namespace, spike: dict) -> int:
    print(banner("live" if args.live else "hermetic", None, spike, args.consume_only))
    run, _ = _runner(args, spike)
    s = run()
    answer = (s.get("connected") or {}).get("answer") if "publish" in s else s.get("answer")
    if answer and s.get("verdict") == expected_verdict(s):
        print(_c(f"\nreleased: {answer}", "1"))
    _print_summary(s)
    return 0 if s.get("verdict") == expected_verdict(s) else 1


def cmd_agent(args: argparse.Namespace, spike: dict) -> int:
    try:
        model = resolve_model()
    except ModelRefused as e:
        print(f"model refused: {e}", file=sys.stderr)
        return 2
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION)
    from .agent import ask, build_agent, make_tool

    print(banner("live" if args.live else "hermetic", model, spike, args.consume_only))
    run, state = _runner(args, spike)
    payloads: list[dict] = []

    def on_payload(p: dict) -> None:
        payloads.append(p)
        print(_c("\ntool result → model (validated: no identifiers, SQL, principals or paths)", "1"))
        keys = ("decision", "answer", "run_verdict", "publication", "receipt", "facts_readback", "cases", "access_checks", "identity", "teardown")
        print(json.dumps({k: p[k] for k in keys if k in p}, indent=1, ensure_ascii=False))

    def on_event(kind: str, **kw: Any) -> None:
        if kind == "tool_call":
            print(_c(f"\nagent ▸ tool call {kw['name']}({json.dumps(kw.get('args') or {})})", "36"))
        elif kind == "tool_result":
            print(_c(f"agent ◂ tool result {kw['name']}", "36"))

    question = args.question or DEFAULT_QUESTION
    print(_c(f"\nyou ▸ {question}", "1"))
    agent = build_agent(make_tool(run, on_payload=on_payload), model)
    answer = asyncio.run(ask(agent, question, on_event=on_event))
    print(_c(f"\n{model} ▸", "1;35"), answer)
    out, summary = state.get("out"), state.get("summary")
    if out is not None and summary is not None:
        _print_summary(summary)
        transcript = {"question": question, "model": model, "vertex_location": DEFAULT_LOCATION, "tool_payloads": payloads,
                      "answer": answer, "answer_leak_check": leaks(answer), "run_id": out.get("run_id"), "mode": out.get("mode"),
                      "cli": f"okf-connected-e2e {__version__}", "runner": out.get("runner"),
                      "path": "consume-only" if args.consume_only else "publish-then-consume"}
        path = _run_dir(spike, out) / "agent_transcript.json"
        path.write_text(json.dumps(transcript, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"transcript: {out.get('run_dir')}/agent_transcript.json")
    ok = (summary is not None and summary.get("verdict") == expected_verdict(summary) and payloads
          and payloads[-1].get("decision") == "RELEASED" and payloads[-1].get("answer"))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="okf-e2e", description="OKF RFC full path (publish in BigQuery, then the connected run) and its ADK agent")
    ap.add_argument("--spike-root", default=None, help="the spike package directory (default OKF_SPIKE_ROOT, then ./.spike/rfc/spikes/bq-graph)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap", help="sparse checkout of the spike package at the pinned commit")
    b.add_argument("--dest", default=".spike")
    b.add_argument("--ref", default=S.SPIKE_REF)
    for name in ("run", "agent"):
        p = sub.add_parser(name)
        mode = p.add_mutually_exclusive_group()
        mode.add_argument("--live", action="store_true", help=f"live GCP in {PROJECT}")
        mode.add_argument("--hermetic", action="store_true", help="no cloud (default)")
        p.add_argument("--consume-only", action="store_true", help="skip the BigQuery publish: the PR #1 connected run against a publication that already existed")
        p.add_argument("--sdk-root", default=None, help="receipt SDK checkout at its pin (default OKF_SDK_ROOT)")
        p.add_argument("--acme-root", default=None, help="knowledge-catalog acme_retail bundle at its pin (default OKF_ACME_ROOT)")
        p.add_argument("--sdk-python", default=None, help="interpreter for the SDK receipt child (default OKF_SDK_PYTHON)")
        p.add_argument("--wait-s", type=int, default=600, help="live: how long a grant or revocation may be waited for")
        p.add_argument("--out", default=None, help="evidence root (default <spike>/evidence/publish-connected, or connected-e2e with --consume-only)")
        if name == "agent":
            p.add_argument("question", nargs="?", default=None)
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "bootstrap":
        print(S.bootstrap(args.dest, args.ref))
        return 0
    spike = S.activate(S.resolve(args.spike_root))
    return cmd_run(args, spike) if args.cmd == "run" else cmd_agent(args, spike)


if __name__ == "__main__":
    sys.exit(main())
