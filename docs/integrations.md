# Integrations and verified boundaries

Go Work integrates with the **agent harness**, not the model API. A DeepSeek or Qwen model can run inside many different hosts; each host owns its lifecycle, approvals and cancellation. This release verifies adapters with local fixtures and subprocess tests. Live interactive activation remains a separate smoke-test step.

## Common setup

1. Install Go Work into a persistent Python environment with `python -m pip install .`.
2. Print configuration with `go-work config --adapter PROFILE`.
3. Merge the generated event groups into your host's settings, preserving existing hooks.
4. Review and trust hooks using the host's own UI/CLI.
5. After the user's task prompt has arrived, the assistant prepares a contract and calls `go-work arm --session REAL_ID --contract contract.json`.
6. Before changing tasks or when input is required, call `go-work pause --session REAL_ID --reason "specific reason"`.

The generated command includes an absolute Python interpreter path. Regenerate it after moving your environment. Use the same `GO_WORK_STORE` for configuration execution, arm, pause and status. A session ID is an explicit host identifier; use a documented context or hook event field rather than a made-up ID.

## Codex

```sh
go-work config --adapter codex
```

Merge into the workspace `.codex/hooks.json` (or the user-level hooks file). Review through `/hooks` in the CLI or the desktop Hooks settings. This configuration registers Stop, UserPromptSubmit, PostToolUse and Interrupt.

Stop consumes `session_id`, `cwd`, `last_assistant_message`, and `permission_mode`. `decision:"block"` with a `reason` requests another continuation. A new user message pauses the previous contract; the exact generated continuation is accepted once. Interrupt persists a cancellation signal even when a validator is holding the main state lock.

Source: [official Codex Hooks documentation](https://learn.chatgpt.com/docs/hooks), inspected 2026-11-08. Platform errors and unexpected tool failures remain host-owned. Current desktop behavior must be smoke tested after trust; the CLI feature flag alone does not establish desktop activation.

## Qwen Code

```sh
go-work config --adapter qwen
```

Merge the `hooks` groups into project `.qwen/settings.json` or your user settings, then use Qwen's trust mechanism. Stop uses the same `decision:"block"` + `reason` shape. Qwen has its own retry/loop limits and modes that disable hooks.

**Input provenance limitation:** Qwen's `UserPromptSubmit` also fires for tool results and Hook sends. Go Work only treats a string `submitted_prompt` as an explicit new user message; events with only `prompt` are left unclassified. Some ACP, remote, restored or mid-turn steering paths can omit this field or event. Use `go-work pause` before changing task scope in these paths. The adapter does not claim universal automatic detection of user corrections.

Qwen skips normal Stop when the current run is cancelled and checks cancellation after hook execution. Go Work does not register a made-up Qwen Interrupt hook. The host handles immediate cancellation; pause the stored contract explicitly before a later, different task. StopFailure is observational, so this tool cannot force continuation after every runtime failure.

Sources: [official hook guide](https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/), [input schema](https://github.com/QwenLM/qwen-code/blob/88e509480059c699ef0d85c7963690eda17ce9b3/packages/core/src/hooks/types.ts), [provenance issue #9511](https://github.com/QwenLM/qwen-code/issues/9511), [cancellation handling](https://github.com/QwenLM/qwen-code/blob/dfc37dffa403f788c6a0f2b4e9e2f87331628710/packages/core/src/core/client.ts).

## DeepSeek Harness — experimental Codex-hook bridge

```sh
go-work config --adapter deepseek-codex
```

This profile targets DeepSeek Harness's **upstream experimental Codex-hook bridge**, rather than claiming that every DSH installation automatically loads Codex hooks. Install and register the bridge according to the matching upstream version, then point it to the reviewed generated hook configuration. Preserve your existing DSH plugin setup.

The upstream plugin entry is `@deepseek-ai/dsh-hooks-codex`, with required `configPath`. Merge this entry into the plugin list in your matching-version DSH configuration:

```yaml
- name: '@deepseek-ai/dsh-hooks-codex'
  config:
    configPath: './.codex/hooks.json'
```

The bridge resolves that path from the directory where DSH starts and reads it at startup. `dsh plugin --profile web add <package>` is the inspected CLI's installation entry; select a package version compatible with your harness before using it. At inspection time, npm's `latest` pointed to `0.0.1-rc.1` while `next` pointed to `0.2.2-rc.1`; an unversioned install therefore differed from the inspected source. This release does not automatically modify or upgrade DSH.

Inspected upstream revision: `fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159`; experimental bridge version `0.2.2-rc.1`. An inspected older DSH `0.1.0-rc.6` installation lacked that bridge. Upstream paths and packaging have changed; follow the version you actually install.

The published bridge also has a matching `0.1.0-rc.6` package with DSH peer ranges `^0.1.0-rc.6`. Its npm package code was inspected: it exposes the same five events and also supplies a null last-assistant message. Its transcript path can be present, unlike the newer bridge's constant null; Go Work does not consume either transcript format. Matching package metadata is evidence of intended compatibility, while actual installation and a live smoke test remain required. [Versioned package](https://www.npmjs.com/package/@deepseek-ai/dsh-hooks-codex/v/0.1.0-rc.6).

The inspected bridge translates Stop blocking into `agent.steer(...)`, but supplies null `last_assistant_message`, null `transcript_path`, and constant false `stop_hook_active`. This adapter uses persistent local counters instead of that boolean. Artifact and validator checks remain usable; text diagnosis is unavailable with the bridge's null message. Plan-mode metadata, immediate cancellation persistence and hook notice display have limited coverage. The generated profile therefore registers only Stop and UserPromptSubmit. Use explicit `go-work pause` at task changes and before requesting user input.

Source: [pinned upstream bridge README](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/experimental/hooks-codex/README.md), [bridge implementation](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/experimental/hooks-codex/src/index.ts).

For a native adapter, the inspected DSH API exposes `agent/turn-stopping` and `agent.steer(...)`. A proper integration must forward the final assistant text, cancellation signal and session ID, supervise the Python child, and apply continuation only while the host turn is still active. This is a documented extension route, not a shipped native plugin.

## Other agents: generic protocol

Any harness can call `go-work event` with the [normalized JSON event](protocol.md) and handle `continue`, `allow` or `pause`. Kimi, GLM, MiniMax and other models are candidates when used in such a harness; dedicated native adapters are open contributions.

Required host behavior:

- Bind the contract to the real session and original task authorization.
- Call before normal completion, with actual final text when available.
- Forward user cancellation and task changes; cancellation wins over a pending continue response.
- Surface `pause` and error status to the user, including remaining checks.
- Preserve the original model, permissions and task scope.

## Live smoke test

Use a disposable report task. Arm a file check, let the agent try to stop before creating the file, confirm a real continuation, then create a passing artifact and confirm release. Repeat with a user cancellation and two concurrent sessions. Record host version, adapter, event fields, result and cancellation behavior. Share sanitized results in an issue or pull request; protocol fixtures and live activation should always be reported separately.
