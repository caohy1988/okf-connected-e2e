# okf-connected-e2e

The runnable CLI and ADK agent for the OKF RFC's **full path**, run as one invocation:

> Author/Publish (BigQuery) → Discover (Catalog) → pin and retrieve a fixed context → evaluate current access, including
> revocation → validate the calculation (result-bound receipt) → enforcing consumer.

The RFC places the serving authority in BigQuery's relational deployment head, with Catalog as the governed discovery
projection (detailed RFC §04). It advances the head atomically before Catalog is reconciled (§05). The landing page's
"three as one path" starts from a live catalog read of that publication. This repository runs that order.

The runners live in the spike package at
[`caohy1988.github.io/rfc/spikes/bq-graph`](https://github.com/caohy1988/caohy1988.github.io/tree/main/rfc/spikes/bq-graph):
- `okf_bq_graph.publish_connected` covers publish then consume, and is the default;
- `okf_bq_graph.connected` covers consume only.

This repository drives them from:
- a command line (`okf-e2e run`);
- an ADK agent on **Gemini 3.8 Flash** (`okf-e2e agent`). The agent gets exactly one tool, and that tool performs the
  run.

It is experimental. The data is synthetic, and one run is not readiness.

## What one run does

### 1. Author and publish in BigQuery (operator)

1. The pinned synthetic Acme bundle (`knowledge-catalog@31da799`) is compiled into an immutable projection.
2. It is appended to a **run-owned, relational-only BigQuery dataset**, and every row is read back and validated
   against the compiled manifest.
3. The publication is marked `READY`, and the head is advanced with one atomic `MERGE`. Every step is a real BigQuery
   job, and each job id is printed as it completes.
4. Only then is a run-owned Catalog entry written. Its runtime pin is generated from the `READY` rows, and the entry is
   read back through the Catalog parser.

The run records the RFC §05 states it reached: `PLANNED → PREPARING → BQ_STAGED → BQ_COMMITTED → KC_APPLIED → COMPLETE`.

### 2. Consume through the connected path (restricted requester)

The requester is a restricted service account reached through IAM impersonation. It is used on every execution leg:
the Catalog read, the BigQuery reads and the receipt computation. The run covers five cases, in order.

| Case | What happens | Expected |
|---|---|---|
| `connected-approved` | The requester reads the entry itself and gets a validated pin. It resolves exactly the publication step 1 published (head observed, never followed), retrieves the declared calculation under governed retrieval, and passes a payload check against the clean pinned source. It then binds to the receipt example, gets authorization, reads the synthetic facts back against their digest and runs the receipt CLI. The enforcing consumer decides. | RELEASED on VERIFIED |
| `connected-sql-substitution` | Same path, but the executed SQL is swapped. | REFUSED (receipt REJECTED) |
| `connected-denied-intermediate` | A row policy hides the intermediate concept, so no path returns. | REFUSED, nothing executed |
| `connected-unauthorized-output` | The pin, retrieval and bind hold, but the requester cannot read the computation's tables. | REFUSED before execution |
| `connected-revocation` | Access is observed present, then revoked, and the denial is observed. A fresh request, a cached-pin bypass and the stored receipt are then each tried. | all refused, nothing executed |

### 3. Teardown and verdict

Teardown restores grants and reads them back, then deletes the run-owned entry and dataset and reads back their
absence.

The verdict is **`E2E_PUBLISH_CONNECTED`** only when all of these hold:
- the publication was `READY` and the head was observed switched;
- the Catalog pin parsed OK;
- the consumer served exactly that publication in that dataset;
- the connected run is `E2E_CONNECTED`;
- every author job ran as the operator;
- the originals are unchanged;
- cleanup is `COMPLETE`.

**Honesty labels**
- **Data and APIs.** Synthetic Acme fixture, no customer data. APIs are live GCP in `--live` and emulated in
  `--hermetic`.
- **Engine.** Relational fallback, not BigQuery Graph / GQL; access is not shown inside graph queries.
- **Receipt.** The SDK example's own verifier with a requester-held key; no independent attester.
- **Publication id.** Content-addressed from the pinned source. The run deploys the same id the long-lived spike
  dataset holds, into a fresh dataset with fresh rows and jobs. It is a new deployment, not a new knowledge revision.
- **§05 is simplified.** One owned dataset with `active_publication`; no `sync_id`, `deployment_heads` or `*_current`
  views.
- **Access setup.** The harness grants the requester Catalog viewer on the entry group.
- **Denied intermediate.** Uses an injected legacy seed on the long-lived `_rls` copy.
- **Sample.** n = 1, with no latency or cost benchmark.

## Prerequisites (live)

- **Operator.** `gcloud auth application-default login` as an operator on `test-project-0728-467323`. The operator
  needs:
  - BigQuery dataset create/delete;
  - Dataplex entry create/delete in the demo entry group, and rights to change that group's IAM policy;
  - `roles/iam.serviceAccountTokenCreator` on the restricted service account.
- **Receipt SDK.** A clean checkout at `6719eb5` (`OKF_SDK_ROOT`).
- **Acme bundle.** A clean `knowledge-catalog` checkout at `31da799`, with `OKF_ACME_ROOT` pointing at
  `okf/bundles/acme_retail`.
- **SDK child interpreter.** One with user site-packages enabled (`OKF_SDK_PYTHON`, for example Homebrew `python3.13`).
  A virtualenv disables `usercustomize`, which carries the requester's e-mail-scope shim.
- **Model.** Vertex AI access to `gemini-3.8-flash` in location `global`.

## Run

```bash
python3.13 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
okf-e2e bootstrap && export OKF_SPIKE_ROOT=$PWD/.spike/rfc/spikes/bq-graph   # or point at an existing checkout
pytest -q                                                                   # this repo's tests (no cloud)
okf-e2e run --hermetic                                                      # the whole path against emulation
export OKF_SDK_PYTHON=/usr/local/opt/python@3.13/bin/python3.13
okf-e2e run --live                                                          # live GCP: publish in BigQuery, then consume; no model
DEMO_MODEL_ID=gemini-3.8-flash okf-e2e agent --live "What was Acme's gross margin for January 2026, and can I trust the number?"
okf-e2e run --live --consume-only                                           # PR #1 behaviour: consume a publication that already existed
```

`DEMO_MODEL_ID` defaults to `gemini-3.8-flash`, and model ids older than Gemini 3 are refused. The banner prints the
model id, project, data, publish and API labels, and the spike commit.

## What the model sees

`payload.tool_payload` projects the run summary into:
- the consumer decision and the released answer (only when the whole run held);
- a `publication` block: authority `BigQuery`, the §05 states, `READY`, head switched, the author job count and
  identity, the Catalog pin, whether the consumer served this publication, and cleanup;
- the receipt verdict and per-case decisions;
- the access and revocation observations, identity and teardown.

It **refuses** a payload containing any of:
- an e-mail or principal;
- a scoped concept or publication id, or `concept_version_id`;
- SQL text;
- a bundle path or a local path.

Job ids and the publication id are printed to the terminal only.

Retained evidence lives with the spike, under `rfc/spikes/bq-graph/evidence/publish-connected/<run_id>/`. It holds:
- `publish/`: the lifecycle journal, ownership and cleanup receipts;
- `connected/<e2e run id>/`: the connected record;
- `publish_connected_live.json`;
- `agent_transcript.json`.
