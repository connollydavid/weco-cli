# Bug: `weco login` initiates the cloud device-auth flow in local mode and coaches agents to surface it

- Reported: 2026-09-08
- Component: `weco login`
- Version: 0.4.0 (connollydavid/weco-cli @ 0111f27e0e37)
- Severity: medium (privacy-posture violation; no data loss)
- Reproducible: always, with `WECO_MODE` unset

## Steps to reproduce

1. Install the forked CLI (default configuration, `WECO_MODE` unset, so
   local mode per `references/local-mode.md`).
2. Run `weco login` on a headless host.
3. Observe: the command immediately initiates the cloud device-auth
   flow against `dashboard.weco.ai/device-login/<code>`, prints
   "If you are an agent: surface the authentication link to the user
   so they can click it", and polls for nine minutes.

## Expected behavior (per the fork's own doctrine)

`references/local-mode.md` states: local mode is the DEFAULT, the CLI
never talks to Weco's cloud, and the cloud is opt-in only
("Opt into the cloud explicitly with `WECO_MODE=weco` (plus
`weco login`)"). A bare `weco login` under the default therefore
should refuse - print the local-mode posture message ("local mode is
the default; set `WECO_MODE=weco` to use the cloud, then login") and
exit non-zero - or require an explicit confirmation/flag. The
agent-surfacing instruction must never print outside cloud mode: it
invites automation agents to relay a cloud authentication URL to a
human who never asked for cloud access.

## Actual behavior

No mode check, no confirmation: the external auth flow starts, and the
CLI coaches agents to surface it. On a headless host the auto-open
fails (harmless X errors) and the flow lapses.

## Incident (why this matters)

On a local-only deployment (the agentic-vllm host, which adopts this
fork precisely because it runs without cloud machinery), an automation
agent following the bundled SKILL.md's hard instruction ("run
`weco login` yourself... Do NOT tell the user to run it manually")
executed `weco login` and relayed the dashboard URL to the operator -
an unauthorized external-service authentication initiation that the
tool itself suggested. No credentials were entered or saved (both
attempts lapsed; `~/.weco` was never created), but the default posture
was contradicted by the tool, and only the operator's intervention
stopped a third attempt.

## Suggested fix

Gate the login command on the mode: if `mode != weco`, print the
posture message and exit 2, unless an explicit `--cloud` flag (or
`WECO_MODE=weco`) is set. Move the agent-surfacing line behind the
same gate. Companion issue for `weco-skill`: the bundled SKILL.md's
login instruction is cloud-edition text and should carry the
local-mode caveat so agents on local-only hosts are not instructed to
authenticate at all.
