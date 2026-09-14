# Security policy

## Reporting a vulnerability

Use the repository's private **Security → Report a vulnerability** flow. Do not
open a public issue containing credentials, private keys, source code, personal
data or exploit details.

Please include the affected version, operating system, a minimal reproduction and
the security boundary you expected. We will acknowledge a usable report and
coordinate disclosure after a fix is available.

## Product boundary

APatch Studio serves its UI on loopback and protects non-health API calls with a
process-scoped secret and same-origin checks. It does not make an unrestricted
local account safe: a process already running as the same operating-system user may
be able to read that user's files or inspect processes.

The supported browser API is fixed-purpose. Source code, full diffs, prompts,
credentials, private keys and raw agent output are not valid Cowork payloads.
