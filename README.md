# okf-connected-e2e

This repository holds the runnable CLI and ADK agent for the OKF RFC's **connected end-to-end run**. The RFC's "What is still open" section asks for:

> One run doing all of it at once: catalog discovery, pinned publication, governed retrieval, caller-delegated
> computation, result-bound receipt and enforcing consumer, with access and revocation checks holding throughout.

The runner is `okf_bq_graph.connected`, in the spike package at
[`caohy1988.github.io/rfc/spikes/bq-graph`](https://github.com/caohy1988/caohy1988.github.io/tree/rfc/connected-e2e/rfc/spikes/bq-graph).
This repository drives it from:
- a command line (`okf-e2e run`);
- an ADK agent on **Gemini 3.8 Flash** (`okf-e2e agent`), which gets exactly one tool, and that tool performs the run.

It is experimental. The data is synthetic, and one run is not readiness.

## What one run does

The run uses one requester, a restricted service account reached through IAM impersonation, on every execution leg:
the Catalog read, the BigQuery reads and the receipt computation. It covers five cases, in order.

| Case | What happens | Expected |
|---|---|---|
| `connected-approved` | The requester reads the Catalog entry itself, getting a validated pin. Next comes the exact READY publication (head observed, never followed), then governed retrieval, then a payload check against the clean pinned source. It then binds to the receipt example's declaration and gets authorization under the requester. After that, the synthetic facts are read back against their selected digest, the receipt CLI runs under the requester, and the enforcing consumer decides. | RELEASED on VERIFIED |
| `connected-sql-substitution` | Same path, but the executed SQL is swapped. | REFUSED (receipt REJECTED) |
| `connected-denied-intermediate` | A row policy hides the intermediate concept, so the seed is visible and no path returns. | REFUSED, nothing executed |
| `connected-unauthorized-output` | The pin, retrieval and bind all hold, but the requester cannot read the computation's tables. | REFUSED before execution |
| `connected-revocation` | Access is observed present, then Catalog, graph and fact access are revoked, and each denial is observed. After that, a fresh request, a bypass with the cached pin, and the stored receipt are each tried. | all refused, nothing executed |

The run grants Catalog viewer on one entry group, dataset reads and a row-policy grantee. Each is snapshotted, then
restored and read back. Every BigQuery job it submits is read back, and its identity is bound to the role that
submitted it. The verdict is `E2E_CONNECTED` only when every case is MET, identity is BOUND, no job is unresolved, and
both restores are VERIFIED.

**Honesty labels**
- Data: synthetic Acme fixture, no customer data. APIs: live GCP in `--live`, emulated in `--hermetic`.
- Engine: relational fallback, not BigQuery Graph / GQL.
- Receipt: the SDK example's own verifier with a requester-held key, and no independent attester.
- The denied-intermediate seed is an injected legacy seed on the `_rls` copy, not a Catalog discovery.
- Catalog concept seeds disable the retrieval cache, so revocation is not shown on a cached replay.
- n = 1, with no latency or cost benchmark.

## Prerequisites (live)

- `gcloud auth application-default login` as an operator on `test-project-0728-467323`. The operator needs
  `roles/iam.serviceAccountTokenCreator` on the restricted service account, plus rights to change the demo entry
  group's IAM policy and the spike datasets' ACLs.
- The receipt SDK checkout at `6719eb5` (`OKF_SDK_ROOT`), clean.
- `knowledge-catalog` at `31da799` (`OKF_ACME_ROOT` pointing at `okf/bundles/acme_retail`), clean.
- An interpreter with user site-packages enabled, for the SDK child (`OKF_SDK_PYTHON`, for example Homebrew
  `python3.13`). A virtualenv disables `usercustomize`, which carries the requester's e-mail-scope shim.
- Vertex AI access to `gemini-3.8-flash` in location `global`.

## Run

```bash
python3.13 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
okf-e2e bootstrap && export OKF_SPIKE_ROOT=$PWD/.spike/rfc/spikes/bq-graph   # or point at an existing checkout
pytest -q                                                                   # this repo's tests (no cloud)
okf-e2e run --hermetic                                                      # the whole run against emulation
export OKF_SDK_PYTHON=/usr/local/opt/python@3.13/bin/python3.13
okf-e2e run --live                                                          # live GCP, no model
DEMO_MODEL_ID=gemini-3.8-flash okf-e2e agent --live "What was Acme's gross margin for January 2026, and can I trust the number?"
```

`DEMO_MODEL_ID` defaults to `gemini-3.8-flash`, and model ids older than Gemini 3 are refused. The banner prints the
model id, project, data and API labels, and the spike commit.

## What the model sees

`payload.tool_payload` projects the run summary into the consumer decision, the released answer (only when RELEASED),
the receipt verdict, per-case decisions, access and revocation observations, the identity status and teardown. It
**refuses** a payload containing any of:
- an e-mail or principal;
- a scoped concept or publication id, or `concept_version_id`;
- SQL text;
- a bundle path or a local path.

The retained evidence lives with the spike, under `rfc/spikes/bq-graph/evidence/connected-e2e/<run_id>/`. It includes
the agent transcript `agent_transcript.json`.
