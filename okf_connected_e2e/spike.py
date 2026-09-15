"""Locate and pin the spike package that implements the connected run.

The runner lives in `caohy1988/caohy1988.github.io` under `rfc/spikes/bq-graph` (package `okf_bq_graph`), next to its
fixtures, SQL and retained evidence, which it reads by relative path. That tree is not a pip-installable distribution,
so this CLI uses a checkout of it: `OKF_SPIKE_ROOT`, `--spike-root`, or `okf-e2e bootstrap` (a sparse clone at
`SPIKE_REF`). The commit actually used is printed in the banner and recorded in the agent transcript.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

SPIKE_REPO = "https://github.com/caohy1988/caohy1988.github.io"
SPIKE_SUBDIR = "rfc/spikes/bq-graph"
SPIKE_REF = "c075801ea04ca8387cf03a52b562c754a57c6bd2"   # rfc/publish-author-bq: okf_bq_graph.publish_connected/0.1.0 + connected/0.1.0


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def resolve(explicit: Optional[str] = None) -> Path:
    candidates = [explicit, os.environ.get("OKF_SPIKE_ROOT"), str(Path.cwd() / ".spike" / SPIKE_SUBDIR)]
    for c in candidates:
        if c and (Path(c) / "okf_bq_graph" / "connected.py").is_file():
            return Path(c).resolve()
    raise SystemExit("spike package not found: set OKF_SPIKE_ROOT, pass --spike-root, or run `okf-e2e bootstrap` "
                     f"(sparse checkout of {SPIKE_REPO}/{SPIKE_SUBDIR} at {SPIKE_REF[:7]})")


def activate(root: Path) -> dict:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    head = _git(root, "rev-parse", "HEAD")
    dirty = _git(root, "status", "--porcelain", "--", ".")
    return {"root": str(root), "head": head, "matches_pin": head == SPIKE_REF, "dirty": bool(dirty) if dirty is not None else None}


def bootstrap(dest: str = ".spike", ref: str = SPIKE_REF) -> str:
    d = Path(dest)
    if not d.exists():
        subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout", SPIKE_REPO, str(d)], check=True)
        subprocess.run(["git", "-C", str(d), "sparse-checkout", "set", SPIKE_SUBDIR], check=True)
    subprocess.run(["git", "-C", str(d), "fetch", "origin", ref], check=True)
    subprocess.run(["git", "-C", str(d), "checkout", "--detach", ref], check=True)
    return f"spike package at {d / SPIKE_SUBDIR} ({ref[:7]}); export OKF_SPIKE_ROOT={(d / SPIKE_SUBDIR).resolve()}"
