from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from getpass import getpass

from .config import CONFIG_PATH, DEFAULT_WORKSPACE, load_config
from .runtime import Runtime
from .agent import AgentRunner
from .tools.mcp import MCPManager


def main() -> None:
    parser = argparse.ArgumentParser(prog="ember", description="Ember assistant")
    sub = parser.add_subparsers(dest="command")

    agent = sub.add_parser("agent", help="Run agent (single message or REPL)")
    agent.add_argument("-m", "--message", dest="message", help="single message to send")

    sub.add_parser("gateway", help="Start gateway with channels")
    sub.add_parser("onboard", help="Initialize config and workspace")
    sub.add_parser("status", help="Show config status")

    args = parser.parse_args()

    if args.command == "onboard":
        run_onboard()
        return
    if args.command == "status":
        run_status()
        return
    if args.command == "gateway":
        asyncio.run(run_gateway())
        return

    asyncio.run(run_agent(args.message))


def run_onboard() -> None:
    cfg = load_config()
    workspace = PathLike.resolve(cfg.agent.workspace or str(DEFAULT_WORKSPACE))
    if sys.stdin.isatty():
        try:
            answer = input(f"Workspace path [{workspace}]: ").strip()
        except EOFError:
            answer = ""
        if answer:
            workspace = PathLike.resolve(answer)
            cfg.agent.workspace = workspace

        print("\n== Ember setup ==")
        cfg.provider.type = _prompt_choice(
            "Provider type", cfg.provider.type or "openai", ["openai", "anthropic", "deepseek", "minimax", "custom"]
        )
        api_key = _prompt_secret("API key (leave blank to keep current)", cfg.provider.apiKey)
        if api_key:
            cfg.provider.apiKey = api_key
        if cfg.provider.type in {"deepseek", "minimax", "custom"}:
            cfg.provider.baseUrl = _prompt_text("Base URL", cfg.provider.baseUrl)
        else:
            base_url = _prompt_text("Base URL (optional)", cfg.provider.baseUrl)
            if base_url:
                cfg.provider.baseUrl = base_url
        cfg.agent.model = _prompt_text("Model", cfg.agent.model)

        if _prompt_yes_no("Enable Telegram adapter?", cfg.channels.telegram.enabled):
            cfg.channels.telegram.enabled = True
            cfg.channels.telegram.token = _prompt_secret("Telegram bot token", cfg.channels.telegram.token)
            cfg.channels.telegram.allowFrom = _prompt_list("Telegram allowFrom (comma-separated, empty=all)")
        else:
            cfg.channels.telegram.enabled = False

        if _prompt_yes_no("Enable Feishu adapter?", cfg.channels.feishu.enabled):
            cfg.channels.feishu.enabled = True
            cfg.channels.feishu.appId = _prompt_text("Feishu App ID", cfg.channels.feishu.appId)
            cfg.channels.feishu.appSecret = _prompt_secret("Feishu App Secret", cfg.channels.feishu.appSecret)
            cfg.channels.feishu.verificationToken = _prompt_text(
                "Feishu Verification Token", cfg.channels.feishu.verificationToken
            )
            cfg.channels.feishu.port = _prompt_int("Feishu listen port", cfg.channels.feishu.port or 9876)
            cfg.channels.feishu.allowFrom = _prompt_list("Feishu allowFrom (comma-separated, empty=all)")
        else:
            cfg.channels.feishu.enabled = False

        if _prompt_yes_no("Enable Slack adapter?", cfg.channels.slack.enabled):
            cfg.channels.slack.enabled = True
            cfg.channels.slack.botToken = _prompt_secret("Slack Bot Token", cfg.channels.slack.botToken)
            cfg.channels.slack.signingSecret = _prompt_secret("Slack Signing Secret", cfg.channels.slack.signingSecret)
            cfg.channels.slack.port = _prompt_int("Slack listen port", cfg.channels.slack.port or 3000)
            cfg.channels.slack.allowFrom = _prompt_list("Slack allowFrom (comma-separated, empty=all)")
        else:
            cfg.channels.slack.enabled = False

        if _prompt_yes_no("Enable WebUI adapter?", cfg.channels.webui.enabled):
            cfg.channels.webui.enabled = True
            cfg.channels.webui.port = _prompt_int("WebUI port", cfg.channels.webui.port or 18790)
            cfg.channels.webui.allowFrom = _prompt_list("WebUI allow tokens (comma-separated, empty=all)")
        else:
            cfg.channels.webui.enabled = False
    PathLike.mkdir(workspace)
    PathLike.mkdir(f"{workspace}/journal")
    PathLike.mkdir(f"{workspace}/recipes")

    PathLike.write_if_missing(f"{workspace}/PROMPT.md", DEFAULT_PROMPT_MD)
    PathLike.write_if_missing(f"{workspace}/PERSONA.md", DEFAULT_PERSONA_MD)
    PathLike.write_if_missing(f"{workspace}/journal/LONGTERM.md", "")
    PathLike.write_if_missing(f"{workspace}/PULSE.md", "")

    save_config(cfg)
    print(f"Config: {CONFIG_PATH}")
    print(f"Workspace: {workspace}")
    print("Next steps:")
    print("  1. Edit config.json to set your API key")
    print("  2. Or set PYCLAW_API_KEY in your environment")
    print("  3. Run 'python -m pyclaw agent -m \"Hello\"'")


def run_status() -> None:
    cfg = load_config()
    print(f"Config: {CONFIG_PATH}")
    print(f"Workspace: {cfg.agent.workspace}")
    print(f"Model: {cfg.agent.model}")
    print(f"Provider: {cfg.provider.type}")
    if cfg.provider.apiKey:
        masked = cfg.provider.apiKey[:4] + "..." + cfg.provider.apiKey[-4:]
        print(f"API Key: {masked}")
    else:
        print("API Key: not set")
    print(f"Telegram: enabled={cfg.channels.telegram.enabled}")
    print(f"Feishu: enabled={cfg.channels.feishu.enabled}")
    print(f"Slack: enabled={cfg.channels.slack.enabled}")
    print(f"WebUI: enabled={cfg.channels.webui.enabled}")


async def run_gateway() -> None:
    cfg = load_config()
    from .gateway import Gateway
    gateway = Gateway(cfg)

    loop = asyncio.get_running_loop()
    for sig in ("SIGINT", "SIGTERM"):
        if hasattr(signal, sig):
            loop.add_signal_handler(getattr(signal, sig), gateway.request_stop)

    await gateway.run()


async def run_agent(message: str | None) -> None:
    cfg = load_config()
    runtime = Runtime(cfg.provider)
    mcp = MCPManager(cfg.mcp.servers) if cfg.mcp.servers else None
    if mcp:
        await mcp.start()
    agent = AgentRunner(cfg, runtime, mcp)

    async def ask(prompt: str) -> None:
        out = await agent.run("cli", prompt, None)
        print(out)

    if message:
        await ask(message)
        await runtime.close()
        if mcp:
            await mcp.stop()
        return

    print("ember agent (type 'exit' to quit)")
    while True:
        try:
            line = input("\n> ").strip()
        except EOFError:
            break
        if not line:
            continue
        if line in {"exit", "quit"}:
            break
        await ask(line)

    await runtime.close()
    if mcp:
        await mcp.stop()


from .config import save_config
from pathlib import Path


class PathLike:
    @staticmethod
    def resolve(path: str) -> str:
        return str(Path(path).expanduser())

    @staticmethod
    def mkdir(path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def write_if_missing(path: str, content: str) -> None:
        p = Path(path)
        if not p.exists():
            p.write_text(content, encoding="utf-8")


DEFAULT_PROMPT_MD = """# Ember Assistant

You are Ember, a focused personal assistant.

You can use tools for files, commands, and web research when helpful.

## Style
- Clear and concise
- Ask only when necessary
- Prefer concrete next actions
"""

DEFAULT_PERSONA_MD = """# Persona

You are calm, practical, and technical when needed.
You help with work, research, and engineering tasks.
"""


def _prompt_text(label: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        val = input(f"{label}{hint}: ").strip()
    except EOFError:
        return default
    return val or default


def _prompt_secret(label: str, default: str = "") -> str:
    hint = " [set]" if default else ""
    try:
        val = getpass(f"{label}{hint}: ").strip()
    except EOFError:
        return default
    return val or default


def _prompt_yes_no(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        val = input(f"{label} ({hint}): ").strip().lower()
    except EOFError:
        return default
    if not val:
        return default
    return val in {"y", "yes"}


def _prompt_list(label: str) -> list[str]:
    try:
        val = input(f"{label}: ").strip()
    except EOFError:
        return []
    if not val:
        return []
    return [item.strip() for item in val.split(",") if item.strip()]


def _prompt_int(label: str, default: int) -> int:
    hint = f" [{default}]"
    try:
        val = input(f"{label}{hint}: ").strip()
    except EOFError:
        return default
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _prompt_choice(label: str, default: str, options: list[str]) -> str:
    opts = "/".join(options)
    hint = f" [{default}]"
    try:
        val = input(f"{label} ({opts}){hint}: ").strip().lower()
    except EOFError:
        return default
    if not val:
        return default
    if val in options:
        return val
    return default
