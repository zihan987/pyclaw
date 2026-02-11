# Ember

[中文说明](README.zh-CN.md)

## Features

- CLI agent (single message + REPL)
- Gateway with Telegram / Feishu / Slack / WebUI adapters
- Multi-provider: OpenAI, Anthropic, DeepSeek, MiniMax, custom base_url
- Skills loading from workspace (`SKILL.md` YAML frontmatter)
- Memory context (`MEMORY.md` + daily notes)
- Multi-modal image/document handling (where supported)
- OpenAI document blocks are uploaded and summarized into context for tool runs
- Cron jobs + heartbeat loop
- Token usage tracking (optional)
- MCP tool integration over stdio
- Hooks + local tools (`exec`, `read_file`, `write_file`, `list_dir`)
- Non-blocking message processing with concurrency limits
- Improved auth checks (Slack signature, Feishu verification token)

## Quick Start

```bash
# Create venv and install deps
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Initialize config + workspace
python -m pyclaw onboard

# Set API key
export PYCLAW_API_KEY=your-api-key

# Run agent (single message)
python -m pyclaw agent -m "Hello"

# Run agent (REPL)
python -m pyclaw agent

# Start gateway (Telegram + Feishu + Slack + WebUI)
python -m pyclaw gateway
```

## Data Directory (.ember)

Ember stores runtime data under `~/.ember/` by default:
- `config.json` — runtime configuration
- `workspace/` — prompt, persona, journal, and skills
- `data/cron/jobs.json` — scheduled jobs

You can change the workspace path by setting `core.workspace` or the `PYCLAW_WORKSPACE` env var.  
When you run `python -m pyclaw onboard` in an interactive terminal, it will prompt for workspace path and walk you through a quick configuration wizard (provider + adapters).

## Config

Config path: `~/.ember/config.json`

Copy `config.example.json` and edit (top-level keys: `runtime`, `core`, `adapters`, `actions`, `callbacks`, `trim`, `usage`, `server`, `mcp`):

```bash
cp config.example.json ~/.ember/config.json
```

### Example Configuration

```json
{
  "runtime": {
    "type": "openai",
    "apiKey": "",
    "baseUrl": "",
    "requestTimeout": 30
  },
  "core": {
    "workspace": "",
    "model": "gpt-4o-mini",
    "maxTokens": 1024,
    "temperature": 0.7,
    "maxConcurrency": 4,
    "maxToolIterations": 8
  },
  "actions": {
    "execTimeout": 60,
    "restrictToWorkspace": true
  },
  "callbacks": {
    "preToolUse": [],
    "postToolUse": [],
    "stop": []
  },
  "skills": {
    "enabled": true,
    "dir": ""
  },
  "adapters": {
    "telegram": {
      "enabled": false,
      "token": "",
      "allowFrom": []
    },
    "feishu": {
      "enabled": false,
      "appId": "",
      "appSecret": "",
      "verificationToken": "",
      "port": 9876,
      "allowFrom": []
    },
    "slack": {
      "enabled": false,
      "botToken": "",
      "signingSecret": "",
      "port": 3000,
      "allowFrom": []
    },
    "webui": {
      "enabled": false,
      "port": 18790,
      "allowFrom": []
    }
  },
  "server": {
    "host": "0.0.0.0",
    "port": 18790
  },
  "mcp": {
    "servers": [
      {
        "name": "example",
        "command": "node",
        "args": ["/path/to/mcp-server.js"],
        "env": {},
        "cwd": ""
      }
    ]
  },
  "trim": {
    "enabled": true,
    "threshold": 0.8,
    "preserveCount": 5
  },
  "usage": {
    "enabled": false,
    "path": "~/.ember/usage.jsonl"
  }
}
```

### Field Reference

- `runtime`: model provider settings
  - `type`: `openai` | `anthropic` | `deepseek` | `minimax` | `custom`
  - `apiKey`: provider API key
  - `baseUrl`: override API base URL (required for deepseek/minimax/custom)
  - `requestTimeout`: HTTP timeout in seconds
- `core`: agent runtime options
  - `workspace`: path for prompt/persona/journal/skills
  - `model`: model name
  - `maxTokens`: max output tokens per turn
  - `temperature`: sampling temperature
  - `maxConcurrency`: concurrent inbound processing limit
  - `maxToolIterations`: tool-call loop limit per turn
- `actions`: local tools runtime
  - `execTimeout`: max seconds for shell commands
  - `restrictToWorkspace`: forbid file/exec outside workspace
- `callbacks`: hook commands
  - `preToolUse`: run before tool call
  - `postToolUse`: run after tool call
  - `stop`: run after model finishes
  - each hook: `{ "command": "...", "pattern": "regex", "timeout": 60 }`
- `skills`: skills loader
  - `enabled`: enable/disable skills
  - `dir`: override skills directory (default `workspace/recipes`)
- `adapters`: channel config
  - `telegram`: bot token + allowlist
  - `feishu`: appId/appSecret/verificationToken + port
  - `slack`: botToken/signingSecret + port
  - `webui`: port + allowlist token(s)
- `server`: gateway listen host/port
- `mcp.servers`: MCP server processes (JSON-RPC over stdio)
- `trim`: auto-compact rules
  - `threshold`: compaction trigger ratio
  - `preserveCount`: keep last N messages when compacting
- `usage`: token usage log
  - `enabled`: write usage logs
  - `path`: JSONL output path

## Workspace

Default workspace: `~/.ember/workspace`

Files:
- `PROMPT.md` - system prompt
- `PERSONA.md` - personality
- `journal/LONGTERM.md` - long-term memory
- `journal/YYYY-MM-DD.md` - daily journal
- `recipes/<skill>/SKILL.md` - skills
- `PULSE.md` - heartbeat prompt (runs every 30 min)

Cron jobs are stored in `~/.ember/data/cron/jobs.json`.

## Notes

- For Slack, configure Events API and set the request URL to:
  `https://your-domain/slack/events`
- For Feishu, set the webhook URL to:
  `https://your-domain/feishu/webhook`
- Telegram uses long polling; no public URL needed.
- WebUI runs on `http://localhost:18790` by default.
- WebUI allowlist: if `webui.allowFrom` is set, open `http://host:port/?token=YOUR_TOKEN`.

### MCP Servers

Configure MCP servers under `mcp.servers` in config (JSON-RPC over stdio). Each entry can be a command string or an object:

```json
{
  "name": "example",
  "command": "node",
  "args": ["/path/to/mcp-server.js"],
  "env": {},
  "cwd": ""
}
```
