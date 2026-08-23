# Title: [Feature] Support Cursor composer and chat session logs

## Description
Cursor stores workspace composer / chat session logs in SQLite and JSON workspace storage (`~/.config/Cursor/User/workspaceStorage/`).

## Goal
Extract turn counts, estimated or recorded token usage, model names, and context growth curves from local Cursor workspaces.

## How to Implement
1. Add `src/agent_cost/parsers/cursor.py`.
2. Handle both `.json` exports and workspace storage structures.
3. Wire into `detect.py` and add unit tests in `tests/test_cursor_parser.py`.

Please open a PR or comment here if you'd like to work on this!
