---
name: Feature request
about: Suggest a capability or a new session format to support
title: ''
labels: enhancement
assignees: ''
---

**What problem are you trying to answer**

The question you wanted your session data to answer but couldn't. For example:
"which tool call is eating my context" or "am I paying for cache writes I never
read back".

**Proposed behaviour**

What the command should do or print.

**Session format** (if requesting new format support)

- Agent / tool name:
- Where the files live:
- Does the format carry real token counters, or would they have to be estimated?

**Scope note**

agent-cost is deliberately read-only and offline: it opens session files, counts
things, and prints. Features that require executing session content, writing
back to session files, or sending data anywhere are out of scope by design.
