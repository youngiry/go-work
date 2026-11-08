# Contributing

Start with a reproducible synthetic case and the intended acceptance criteria. Run:

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

For a harness adapter, include an official source link and version/commit, the event fields, cancellation semantics, fixtures, and a clear distinction between protocol tests and a live smoke test. Preserve task scope, permission requests and user control. Keep the runtime dependency-free.

New language patterns should have both a missed-work case and a genuine-completion counterexample. Acceptance evidence, rather than a phrase alone, must decide the gate. Use synthetic tasks in tests and issues; keep private transcripts, credentials and real research materials local.
