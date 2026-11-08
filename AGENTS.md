# Contributor guidance

Go Work is a local completion gate. Preserve user cancellation, scope and host approval behavior. Completion decisions must depend on configured evidence; text patterns are diagnostic signals only.

Keep runtime dependencies in the Python standard library. Add regression tests for behavior changes. Run `python -m unittest discover -s tests -v`. Distinguish protocol fixtures from real-host validation in documentation. Use synthetic examples and keep local user data out of this repository.
