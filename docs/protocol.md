# Contract and generic harness protocol

## Contract

```json
{
  "root": ".",
  "objective": "Produce the report and pass its data validation",
  "checks": [
    {"id":"report", "kind":"file", "path":"report.md", "changed":true,
     "min_bytes":120, "contains":["Findings", "Sources"]},
    {"id":"validation", "kind":"command", "argv":["python", "validate.py"], "timeout":10}
  ],
  "limits":{"continuations":6,"stalls":3,"minutes":90}
}
```

Resolve `root` relative to the directory where `arm` runs. Set it to the agent's working directory. File paths stay inside it, including after symlink resolution. `changed` defaults to true and compares against the arm-time SHA-256. Optional `contains` checks UTF-8 text literally; pair it with stronger validation when correctness matters.

Command checks use an argv array and `shell=False`. They run on every stop, before a continuation decision. The user/integrator must review these explicit local commands; arbitrary downloaded contracts should be treated as executable configuration. Exit zero passes. Output is discarded; timeouts, unavailable commands and nonzero exit codes remain unmet checks. Command-only tasks may use a validator as their sole completion criterion. Avoid validators that spawn detached children.

Limits: 1–64 checks; 8 MiB per artifact; 1–60 seconds per command; 90 seconds combined command timeout; 1–30 continuations; 1–10 stalls; 1–240 minutes. These are stop-boundary checks, not a process watchdog. On check errors, the CLI releases control with error status.

## Events

Pipe one UTF-8 JSON object to `go-work event`. Use a stable session ID and the same store for `arm` and subsequent events.

```json
{"event":"stop","session_id":"example-session","cwd":".","message":"Everything is complete."}
```

Other events: `tool` counts observed tool calls; `interrupt` pauses the contract; `blocked` pauses for input; `user_prompt` with `prompt` pauses for new instructions. If a host emits the exact Go Work-generated continuation as a user prompt, it is consumed once and preserves the current contract. Call `arm` after the real user prompt event has been processed.

On a stop, optional `mode:"plan"` pauses enforcement. Empty messages are supported: evidence checks still run while language signals remain unavailable.

## Responses

```json
{
  "action":"continue",
  "status":"active",
  "checks":[{"id":"report","passed":false,"reasons":["artifact_missing"]}],
  "signals":["acceptance_gap","completion_claim_with_gaps"],
  "reason":"...concrete continuation instruction..."
}
```

- `continue`: the host may send `reason` to its normal continuation/steering interface, subject to original authorization and user cancellation.
- `allow`: release the gate. Inspect `status`; only `checks_passed` reports successful acceptance. `unregistered` and `error` are also allow outcomes.
- `pause`: budget/stall limit reached; return control to the user with remaining check results.

Never translate every `allow` into task success. The host must honor interrupted/failed states before applying any continuation. A custom host should send `interrupt` or `blocked` events and support immediate user cancellation while validators are running.

## Storage and privacy

Default store: `~/.go-work`; override with `--store PATH` before the subcommand, or `GO_WORK_STORE`. All hooks and task-management commands must use the same store. A SHA-256 of the session ID names each state file. State contains the task objective, paths, validator arguments, file baselines, hashed text fragments for repetition detection (computed from up to 12000 response characters), current continuation prompt, and up to 100 stop summaries. It is local plaintext: apply normal local access controls and avoid putting secrets into contracts. Go Work never sends these files to a service.

Atomic replacement protects writes; a per-session lock avoids concurrent updates. OS-backed locks release when the process exits. Lock files can remain on disk as stable lock identities. Cancellation is persisted separately and checked while validators run and again before continuing. Errors release the gate, so a broken checker cannot create an uncontrolled retry loop.
