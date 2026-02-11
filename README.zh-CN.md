# Ember

中文说明（与英文版同步维护）。

## 功能概览

- CLI 智能体（单条消息 + REPL）
- Gateway：Telegram / 飞书 / Slack / WebUI
- 多模型：OpenAI / Anthropic / DeepSeek / MiniMax / 自定义 base_url
- 技能加载（`recipes/<skill>/SKILL.md`）
- 记忆上下文（`journal/LONGTERM.md` + 日记）
- 多模态图片/文档（视提供商支持）
- Cron 定时 + 心跳
- Token 使用量记录（可选）
- MCP 工具（JSON-RPC over stdio）
- Hooks + 本地工具（exec/read/write/list）
- 并发处理避免阻塞

## 数据目录（.ember）

默认数据目录：`~/.ember/`
- `config.json`：运行配置
- `workspace/`：提示词、人格、记忆、技能
- `data/cron/jobs.json`：定时任务

可通过 `core.workspace` 或 `PYCLAW_WORKSPACE` 修改路径。  
在交互终端运行 `python -m pyclaw onboard` 会提示你输入 workspace 并启动配置向导。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m pyclaw onboard
python -m pyclaw agent -m "你好"
python -m pyclaw gateway
```

## 配置

配置路径：`~/.ember/config.json`

```bash
cp config.example.json ~/.ember/config.json
```

### 配置示例

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

### 字段说明

- `runtime`：模型提供商设置
- `core`：智能体运行参数
- `actions`：本地工具参数
- `callbacks`：Hook 事件
- `skills`：技能加载
- `adapters`：接入通道
- `server`：网关监听
- `mcp`：MCP 服务
- `trim`：自动压缩
- `usage`：token 记录

## 通道说明

- Slack：配置 Events API，回调 `https://your-domain/slack/events`
- 飞书：配置回调 `https://your-domain/feishu/webhook`
- Telegram：长轮询，无需公网地址
- WebUI：默认 `http://localhost:18790`

## MCP

`mcp.servers` 配置 MCP 进程（JSON-RPC over stdio）。

