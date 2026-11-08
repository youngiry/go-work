# Security and local data

Go Work executes user-configured validators locally. Review contracts as executable configuration. State contains local task details and hashed response fragments used for repetition detection. The package makes no network requests and performs no automatic uploads.

The agent and checker share filesystem permissions. This is a workflow gate, not a hostile-agent containment boundary. User cancellation and permission enforcement remain responsibilities of the host runtime.

Please report vulnerabilities through GitHub private vulnerability reporting when available. Otherwise open an issue containing only a high-level description and request a private contact route; omit secrets and exploit-sensitive private data.
