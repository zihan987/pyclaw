from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_USAGE_LOG = str((Path.home() / ".ember" / "usage.jsonl"))
DEFAULT_EXEC_TIMEOUT = 60

CONFIG_DIR = Path.home() / ".ember"
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_WORKSPACE = CONFIG_DIR / "workspace"
OLD_CONFIG_DIR = Path.home() / ".pyclaw"
OLD_CONFIG_PATH = OLD_CONFIG_DIR / "config.json"


@dataclass
class ProviderConfig:
    type: str = "openai"  # openai, anthropic, deepseek, minimax, custom
    apiKey: str = ""
    baseUrl: str = ""
    requestTimeout: int = DEFAULT_REQUEST_TIMEOUT


@dataclass
class AgentConfig:
    workspace: str = ""
    model: str = DEFAULT_MODEL
    maxTokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    maxConcurrency: int = DEFAULT_MAX_CONCURRENCY
    maxToolIterations: int = 8


@dataclass
class ToolsConfig:
    execTimeout: int = DEFAULT_EXEC_TIMEOUT
    restrictToWorkspace: bool = True


@dataclass
class AutoCompactConfig:
    enabled: bool = True
    threshold: float = 0.8
    preserveCount: int = 5


@dataclass
class HookEntry:
    command: str
    pattern: str = ""
    timeout: int = DEFAULT_EXEC_TIMEOUT


@dataclass
class HooksConfig:
    preToolUse: List[HookEntry] = field(default_factory=list)
    postToolUse: List[HookEntry] = field(default_factory=list)
    stop: List[HookEntry] = field(default_factory=list)


@dataclass
class SkillsConfig:
    enabled: bool = True
    dir: str = ""


@dataclass
class TelegramConfig:
    enabled: bool = False
    token: str = ""
    allowFrom: List[str] = field(default_factory=list)


@dataclass
class FeishuConfig:
    enabled: bool = False
    appId: str = ""
    appSecret: str = ""
    verificationToken: str = ""
    port: int = 9876
    allowFrom: List[str] = field(default_factory=list)


@dataclass
class SlackConfig:
    enabled: bool = False
    botToken: str = ""
    signingSecret: str = ""
    port: int = 3000
    allowFrom: List[str] = field(default_factory=list)


@dataclass
class WebUIConfig:
    enabled: bool = False
    port: int = 18790
    allowFrom: List[str] = field(default_factory=list)


@dataclass
class GatewayConfig:
    host: str = "0.0.0.0"
    port: int = 18790


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: str = ""


@dataclass
class MCPConfig:
    servers: List[MCPServerConfig] = field(default_factory=list)


@dataclass
class TokenTrackingConfig:
    enabled: bool = False
    path: str = DEFAULT_USAGE_LOG


@dataclass
class ChannelsConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    webui: WebUIConfig = field(default_factory=WebUIConfig)


@dataclass
class Config:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    channels: ChannelsConfig = field(default_factory=ChannelsConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    autoCompact: AutoCompactConfig = field(default_factory=AutoCompactConfig)
    tokenTracking: TokenTrackingConfig = field(default_factory=TokenTrackingConfig)


def _apply_dict(obj: Any, data: Dict[str, Any]) -> Any:
    for key, value in data.items():
        if hasattr(obj, key):
            current = getattr(obj, key)
            if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
                _apply_dict(current, value)
            else:
                setattr(obj, key, value)
    return obj


def _normalize_mcp_servers(raw: List[Any]) -> List[MCPServerConfig]:
    servers: List[MCPServerConfig] = []
    for item in raw:
        if isinstance(item, MCPServerConfig):
            servers.append(item)
            continue
        if isinstance(item, str):
            parts = shlex.split(item)
            if not parts:
                continue
            name = Path(parts[0]).name
            servers.append(MCPServerConfig(name=name, command=parts[0], args=parts[1:]))
            continue
        if isinstance(item, dict):
            name = item.get("name") or "mcp"
            command = item.get("command") or ""
            args = item.get("args") or []
            env = item.get("env") or {}
            cwd = item.get("cwd") or ""
            if command:
                servers.append(MCPServerConfig(name=name, command=command, args=list(args), env=dict(env), cwd=cwd))
    return servers


def _normalize_hooks(raw: List[Any]) -> List[HookEntry]:
    hooks: List[HookEntry] = []
    for item in raw:
        if isinstance(item, HookEntry):
            hooks.append(item)
            continue
        if isinstance(item, dict) and item.get("command"):
            hooks.append(
                HookEntry(
                    command=item.get("command"),
                    pattern=item.get("pattern", ""),
                    timeout=int(item.get("timeout", DEFAULT_EXEC_TIMEOUT)),
                )
            )
    return hooks


def load_config() -> Config:
    cfg = Config()

    config_path = CONFIG_PATH if CONFIG_PATH.exists() else OLD_CONFIG_PATH
    if config_path.exists():
        raw = config_path.read_text(encoding="utf-8")
        if raw.strip():
            data = json.loads(raw)
            # New schema key mapping for de-similarization
            if "runtime" in data and "provider" not in data:
                data["provider"] = data.get("runtime", {})
            if "core" in data and "agent" not in data:
                data["agent"] = data.get("core", {})
            if "adapters" in data and "channels" not in data:
                data["channels"] = data.get("adapters", {})
            if "actions" in data and "tools" not in data:
                data["tools"] = data.get("actions", {})
            if "callbacks" in data and "hooks" not in data:
                data["hooks"] = data.get("callbacks", {})
            if "trim" in data and "autoCompact" not in data:
                data["autoCompact"] = data.get("trim", {})
            if "usage" in data and "tokenTracking" not in data:
                data["tokenTracking"] = data.get("usage", {})
            if "server" in data and "gateway" not in data:
                data["gateway"] = data.get("server", {})
            _apply_dict(cfg, data)

            if isinstance(data.get("mcp", {}).get("servers"), list):
                cfg.mcp.servers = _normalize_mcp_servers(data["mcp"]["servers"])

            if isinstance(data.get("hooks", {}).get("preToolUse"), list):
                cfg.hooks.preToolUse = _normalize_hooks(data["hooks"]["preToolUse"])
            if isinstance(data.get("hooks", {}).get("postToolUse"), list):
                cfg.hooks.postToolUse = _normalize_hooks(data["hooks"]["postToolUse"])
            if isinstance(data.get("hooks", {}).get("stop"), list):
                cfg.hooks.stop = _normalize_hooks(data["hooks"]["stop"])

    # Env overrides
    env_key = (
        os.getenv("PYCLAW_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("MINIMAX_API_KEY")
    )
    if env_key:
        cfg.provider.apiKey = env_key

    env_type = os.getenv("PYCLAW_PROVIDER_TYPE")
    if env_type:
        cfg.provider.type = env_type

    env_base = os.getenv("PYCLAW_BASE_URL")
    if env_base:
        cfg.provider.baseUrl = env_base

    env_model = os.getenv("PYCLAW_MODEL")
    if env_model:
        cfg.agent.model = env_model

    env_workspace = os.getenv("PYCLAW_WORKSPACE")
    if env_workspace:
        cfg.agent.workspace = env_workspace

    # Channel env overrides
    if token := os.getenv("PYCLAW_TELEGRAM_TOKEN"):
        cfg.channels.telegram.token = token
    if app_id := os.getenv("PYCLAW_FEISHU_APP_ID"):
        cfg.channels.feishu.appId = app_id
    if app_secret := os.getenv("PYCLAW_FEISHU_APP_SECRET"):
        cfg.channels.feishu.appSecret = app_secret
    if verif := os.getenv("PYCLAW_FEISHU_VERIFICATION_TOKEN"):
        cfg.channels.feishu.verificationToken = verif
    if bot_token := os.getenv("PYCLAW_SLACK_BOT_TOKEN"):
        cfg.channels.slack.botToken = bot_token
    if signing := os.getenv("PYCLAW_SLACK_SIGNING_SECRET"):
        cfg.channels.slack.signingSecret = signing
    if not cfg.agent.workspace:
        cfg.agent.workspace = str(DEFAULT_WORKSPACE)
    if not cfg.tokenTracking.path:
        cfg.tokenTracking.path = DEFAULT_USAGE_LOG

    return cfg


def save_config(cfg: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "runtime": cfg.provider.__dict__,
        "core": cfg.agent.__dict__,
        "actions": cfg.tools.__dict__,
        "callbacks": {
            "preToolUse": [hook.__dict__ for hook in cfg.hooks.preToolUse],
            "postToolUse": [hook.__dict__ for hook in cfg.hooks.postToolUse],
            "stop": [hook.__dict__ for hook in cfg.hooks.stop],
        },
        "skills": cfg.skills.__dict__,
        "adapters": {
            "telegram": cfg.channels.telegram.__dict__,
            "feishu": cfg.channels.feishu.__dict__,
            "slack": cfg.channels.slack.__dict__,
            "webui": cfg.channels.webui.__dict__,
        },
        "server": cfg.gateway.__dict__,
        "mcp": {
            "servers": [server.__dict__ for server in cfg.mcp.servers],
        },
        "trim": cfg.autoCompact.__dict__,
        "usage": cfg.tokenTracking.__dict__,
    }

    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except PermissionError:
        pass
