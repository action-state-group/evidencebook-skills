# Capsule CLI contract

Compatible implementation: capsule-cli with the MySQL and SQLite backends, installed on the execution host as `capsulectl` on `PATH`. The CLI is a prerequisite, **not** copied into the bundle; invoke it as `capsulectl`. Requires a configured profile on the execution host. No database credentials belong in prompts or bundles.

All successful stdout is a flat JSON object with spec_version=capsule-cli-result/v1. There is no result wrapper. Check process exit status before parsing; a JSON report does not imply success. Errors: 1 operational, 2 input, 3 partial verification, 4 publication pending, 5 conflict. Never suppress errors with an empty-list fallback.

## Resolve the profile

```sh
capsulectl profile list
capsulectl profile show NAME
```

`profile list` returns `{"profiles":[NAME, …]}` — the configured profile names, for discovery only (it carries no store/namespace details). Resolve a specific one with `profile show NAME` (NAME is positional, not a `--profile` flag). Read `StoreID`, `Namespace` and `LogID` to freeze the target; `ReadOnly` describes write configuration. Do not save the entire profile or its credentials in the run or bundle. The store backend (`Type`) may be `mysql` or `sqlite`; both expose the identical CLL/get/verify/publish contract below, so the evaluation workflow does not depend on which is configured. A dataset backfilled into a local `sqlite` store is enumerated and verified exactly like any other profile.

## Enumerate

```sh
capsulectl cll list --profile NAME --after AFTER --through THROUGH --limit 1000
```

AFTER is exclusive, THROUGH inclusive. Omit through for discovery. Result fields: entries (sequence, capsule_id, appended_at), next_after, log_id, store_id. Default limit 100; maximum 1000. next_after is a cursor, not has_more. Preserve through across pages. Stop at through or an empty page; reject non-advancing cursors on nonempty pages. Account for every entry even when excluded from evaluation.

For "last week", freeze now in UTC and use [now minus seven days, now). Record the user's timezone and interpretation. Select by appended_at, not investigation time. Do not assume appended_at is monotonic with sequence: inspect every enumerated timestamp. Persist the candidate IDs/sequences before extraction. Never express a sparse time selection only as a contiguous min/max range: retain exact membership and apply the timestamp predicate. Establish a fixed upper sequence before scoring, then scan only through that boundary. If the CLI has no head operation, complete a bounded discovery scan, freeze its observed last sequence, and explain that this is an observed prefix, not an atomic time-of-start snapshot. Continuing appends must not extend an already frozen run.

Migration appends can make old investigations appear in a recent append-time window. Report that distinction; do not silently substitute business timestamps. Exclude evaluation reports and unsupported source profiles explicitly.

## Retrieve and verify

```sh
capsulectl get --profile NAME --capsule-id ID
capsulectl get --profile NAME --capsule-id ID --raw --output RECORD.json
capsulectl verify --profile NAME --capsule RECORD.json
```

Readable get exposes capsule_id, capsule, producer_envelope, artifacts at top level. JSON bytes become JSON values, text becomes strings, other bytes use {encoding:base64,data:...}. Artifacts are unordered: select by name, never index. Keep binding, state, content_sha256. An unbound artifact is not authenticated simply because it was stored beside a Capsule.

Raw --output is an exact SDK record usable by verify; readable JSON must not be used to reconstruct signed bytes. Verification reports identity/signature/trust/content separately and does not establish business truth or CLL inclusion. Missing original content is a limitation, not a match.

## Publish

```sh
capsulectl publish --profile NAME --request REQUEST.json
```

Requires writable profile, signing configuration, trusted producer keys and initialized artifact/CLL facilities. Do not initialize production storage during evaluation. Do not treat changing ReadOnly as granting SQL privileges or adding a signing key.

REQUEST uses capsule-seal-request/v1, a capsule object with ActionID, ActionType, Operator, Developer, Timestamp, and payload containing the complete evaluation report. Optional agent_output is unnecessary for this report-only payload mapping. Use ActionType=fyi. Resolve real operator/developer identities from authorized deployment configuration, never invent them. Persist the exact request, timestamp and action ID before the first publish. The CLI request field `payload` is committed at `model_attestation.compute_attestation.agent_input_digest` in verified records. Keep request field names and artifact binding paths distinct.

To link a Capsule to the one it derives from, add a `Chain` block to the request `capsule` (the request capsule uses the same field spelling as `ActionID`/`ActionType`/`Timestamp`): `"Chain": {"ParentCapsuleID": <parent capsule_id>, "Relation": <relation>}`. Do not set `assurance` or `ledger_mode` in the request; the request capsule rejects unknown fields, and supplying `Chain` derives `ledger_mode` to `chained` automatically. In the sealed and verified Capsule this renders as `assurance.ledger_mode: chained` and a `chain` block `{parent_capsule_id, relation}`, committed into `capsule_id` under format 4, so any later edit to the parent link fails verification. `Relation` states how this Capsule relates to its parent and comes from an extensible registry (seeded values `confirms`, `supersedes`, `epoch_opens`; namespaced extensions such as `io.evaluation.evaluates` are permitted and verify). `publish` runs a store-level check that the parent already exists in the target CLL, so append a Capsule only after its parent; a missing parent is a chain failure, not success. `seal` builds and signs the record to a file without a database and does not run that parent-existence check.

Publication returns capsule_id, sequence, state and target identifiers. Pending/conflict is not success. Retry only the identical request, signer and profile target and reconcile existing publication; never regenerate a timestamp or signer after an uncertain append. Checkpoint-service publication is a separate operation and is not needed to append an evaluation report.
