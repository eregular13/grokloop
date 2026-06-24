# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| `main`  | Yes       |

## Reporting a vulnerability

Please **do not** open public issues for security vulnerabilities.

Report via [GitHub Security Advisories](https://github.com/eregular13/grokloop/security/advisories/new)
or contact the maintainer privately.

## Threat model

GrokLoop executes **model-proposed actions** against your local machine. Model output is
**untrusted input**. Every tool call must pass policy checks before execution.

### Built-in controls

- **Workspace sandbox** — file tools restricted to `/workspace` by default
- **Path validation** — rejects paths outside allowed roots
- **Command blocklist** — dangerous shell patterns blocked
- **Git/docker guards** — destructive operations blocked without human approval
- **Human-in-the-loop** — `ask_human` pauses the loop for approval
- **Iteration caps** — `MAX_ITERATIONS_PER_GOAL` enforced
- **Tool timeouts** — `TOOL_TIMEOUT_SECONDS` on shell/python
- **Non-root container** — agent runs as `agentuser` (UID 1000)

### High-risk settings

| Setting | Risk |
|---------|------|
| `SELF_EDIT_MODE=true` | Agent can modify project source |
| Docker socket mount | Agent can control containers |
| Removing tool blocklists | Arbitrary command execution |

### Recommendations

1. Keep `SELF_EDIT_MODE=false` unless actively supervising
2. Remove `/var/run/docker.sock` mount if docker control is not needed
3. Never commit `.env` or API keys
4. Review `human_outbox/` before approving actions
5. Run on a dedicated machine or VM for untrusted goals

## Dependency scanning

CI runs `pip audit` on pull requests. Keep dependencies updated via Dependabot.

## Logs and secrets

Full prompts and responses are **not** logged by default. Cycle logs contain event metadata only.
Do not enable verbose prompt logging in production without redaction.