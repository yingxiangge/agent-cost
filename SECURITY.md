# Security

`agent-cost` is a read-only parser. It never executes code from session files,
never sends data over the network, and never modifies the files it reads.

## Reporting a vulnerability

Please open a private advisory on GitHub (Security -> Report a vulnerability)
instead of a public issue. Do not include session files or API keys in reports.

## Input handling

Session files are parsed as untrusted input:

- Content is only counted, never evaluated or rendered as HTML.
- Token and cost figures from files are treated as data, not instructions.
- We recommend scanning session files for secrets (for example `gitleaks`)
  before sharing them publicly.
