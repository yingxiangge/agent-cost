# Title: [Feature] Support Cline / Roo Code conversation history and token usage

## Description
Cline (formerly Claude Dev) and Roo Code store task execution history and token statistics locally in VS Code's global storage. We'd love to support parsing Cline / Roo Code sessions directly in `agent-cost`.

## Storage Locations
- **Cline**: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/tasks/<task_id>/api_conversation_history.json`
- **Roo Code**: `~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/tasks/<task_id>/api_conversation_history.json`

## Expected Log Format
The `api_conversation_history.json` file contains an array of message turns with Anthropic-style usage:
```json
[
  {
    "role": "user",
    "content": "..."
  },
  {
    "role": "assistant",
    "content": "...",
    "usage": {
      "input_tokens": 1250,
      "output_tokens": 420,
      "cache_read_input_tokens": 8500,
      "cache_creation_input_tokens": 300
    }
  }
]
```

## How to Implement
1. Add `src/agent_cost/parsers/cline.py` with `parse_cline_session(path: Path) -> SessionStats`.
2. Map `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` into `SessionStats`.
3. Add signature sniffing and routing in `src/agent_cost/parsers/detect.py`.
4. Add unit tests in `tests/test_cline_parser.py`.

PRs welcome!
