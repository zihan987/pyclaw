from __future__ import annotations

import json
from typing import Any, Dict, List

from .config import Config
from .conversation import ConversationStore
from .hooks import HookManager
from .memory import MemoryStore
from .models import ContentBlock
from .runtime import Runtime, RuntimeRequest
from .skills import Skill, load_skills, match_skills
from .token_tracking import TokenTracker, build_usage
from .tools.mcp import MCPManager
from .tools.registry import ToolRegistry


class AgentRunner:
    def __init__(self, cfg: Config, runtime: Runtime, mcp: MCPManager | None = None) -> None:
        self.cfg = cfg
        self.runtime = runtime
        self.memory = MemoryStore(cfg.agent.workspace)
        self.skills: List[Skill] = []
        if cfg.skills.enabled:
            skill_dir = cfg.skills.dir or _pick_skill_dir(cfg.agent.workspace)
            self.skills = load_skills(skill_dir)
        self._base_prompt = self._read_prompt_files()
        self._store = ConversationStore(cfg.autoCompact, cfg.agent.maxTokens)
        self._hooks = HookManager(cfg.hooks)
        self._tools = ToolRegistry(cfg.tools, cfg.agent.workspace, self._hooks, mcp)
        self._tracker = TokenTracker(cfg.tokenTracking.path) if cfg.tokenTracking.enabled else None

    def _read_prompt_files(self) -> str:
        parts = []
        agents = f"{self.cfg.agent.workspace}/PROMPT.md"
        soul = f"{self.cfg.agent.workspace}/PERSONA.md"
        if agents and PathLike.exists(agents):
            parts.append(PathLike.read(agents).strip())
        if soul and PathLike.exists(soul):
            parts.append(PathLike.read(soul).strip())
        if not parts:
            legacy_agents = f"{self.cfg.agent.workspace}/AGENTS.md"
            legacy_soul = f"{self.cfg.agent.workspace}/SOUL.md"
            if PathLike.exists(legacy_agents):
                parts.append(PathLike.read(legacy_agents).strip())
            if PathLike.exists(legacy_soul):
                parts.append(PathLike.read(legacy_soul).strip())
        return "\n\n".join(p for p in parts if p)

    def _build_system_prompt(self, message: str, summary: str) -> str:
        parts = [self._base_prompt] if self._base_prompt else []

        mem = self.memory.get_memory_context()
        if mem:
            parts.append(mem)

        if self.cfg.mcp.servers:
            parts.append("# MCP Servers\n" + "\n".join([srv.name for srv in self.cfg.mcp.servers]))

        matched = match_skills(self.skills, message)
        if matched:
            skill_blocks = []
            for skill in matched:
                if skill.body:
                    skill_blocks.append(f"# Skill: {skill.name}\n{skill.body}")
            if skill_blocks:
                parts.append("\n\n".join(skill_blocks))

        if summary:
            parts.append(f"# Summary\n{summary}")

        return "\n\n".join(p for p in parts if p)

    async def run(self, session_id: str, prompt: str, content_blocks: List[ContentBlock] | None = None) -> str:
        conv = self._store.get(session_id)
        doc_context = ""
        doc_blocks: List[ContentBlock] = []
        if content_blocks:
            doc_blocks = [b for b in content_blocks if b.type == "document"]
        if content_blocks:
            if self.cfg.provider.type.lower().strip() == "anthropic":
                blocks = [{"type": "text", "text": prompt}]
                for block in content_blocks:
                    if block.type == "image" and block.data and block.media_type:
                        blocks.append(
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": block.media_type, "data": block.data},
                            }
                        )
                    elif block.type == "document" and block.data and block.media_type:
                        blocks.append(
                            {
                                "type": "document",
                                "source": {"type": "base64", "media_type": block.media_type, "data": block.data},
                            }
                        )
                conv.add_user(blocks)
            else:
                user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
                for block in content_blocks:
                    if block.type == "image" and block.data and block.media_type:
                        url = f"data:{block.media_type};base64,{block.data}"
                        user_content.append({"type": "image_url", "image_url": {"url": url}})
                    elif block.type == "document":
                        user_content.append({"type": "text", "text": "[document]"})
                conv.add_user(user_content)
        else:
            conv.add_user(prompt)

        if doc_blocks and self.cfg.provider.type.lower().strip() == "openai":
            try:
                doc_prompt = (
                    "Read the attached documents and extract the key factual details needed to answer the user's request. "
                    "Return concise notes without analysis.\n\nUser request:\n"
                    + prompt
                )
                doc_context, usage = await self.runtime.openai_doc_context(
                    system_prompt="You are a precise document reader.",
                    prompt=doc_prompt,
                    documents=doc_blocks,
                    model=self.cfg.agent.model,
                    max_tokens=min(1024, self.cfg.agent.maxTokens),
                    temperature=0.2,
                )
                if self._tracker:
                    usage_obj = build_usage(self.cfg.provider.type, self.cfg.agent.model, usage)
                    if usage_obj:
                        self._tracker.record(usage_obj)
                if doc_context:
                    last = conv.messages[-1]
                    if isinstance(last.get("content"), list):
                        last["content"].append(
                            {"type": "text", "text": f"[Document context]\\n{doc_context.strip()}"}
                        )
                    else:
                        last["content"] = f"{last.get('content', '')}\\n\\n[Document context]\\n{doc_context.strip()}"
            except Exception:
                pass

        await self._maybe_compact(conv)

        for _ in range(max(1, self.cfg.agent.maxToolIterations)):
            system_prompt = self._build_system_prompt(prompt, conv.summary)
            defs = self._tools.list_definitions()
            if not defs:
                req = RuntimeRequest(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=self.cfg.agent.model,
                    max_tokens=self.cfg.agent.maxTokens,
                    temperature=self.cfg.agent.temperature,
                    content_blocks=content_blocks,
                )
                text, usage = await self.runtime.run(req)
                if self._tracker:
                    usage_obj = build_usage(self.cfg.provider.type, self.cfg.agent.model, usage)
                    if usage_obj:
                        self._tracker.record(usage_obj)
                if text:
                    conv.add_assistant(text)
                    await self._hooks.run_stop({"final": text})
                    return text
                break
            if self.cfg.provider.type.lower().strip() == "anthropic":
                text, tool_calls, usage = await self.runtime.anthropic_with_tools(
                    system_prompt=system_prompt,
                    messages=conv.to_anthropic_messages(),
                    tools=self._tools.anthropic_tools(defs),
                    model=self.cfg.agent.model,
                    max_tokens=self.cfg.agent.maxTokens,
                    temperature=self.cfg.agent.temperature,
                )
                if self._tracker:
                    usage_obj = build_usage(self.cfg.provider.type, self.cfg.agent.model, usage)
                    if usage_obj:
                        self._tracker.record(usage_obj)

                if tool_calls:
                    content_blocks = []
                    if text:
                        content_blocks.append({"type": "text", "text": text})
                    content_blocks.extend(tool_calls)
                    conv.add_anthropic_tool_use(content_blocks)
                    for tool_use in tool_calls:
                        name = tool_use.get("name")
                        tool_id = tool_use.get("id")
                        args = tool_use.get("input") or {}
                        if not name or not tool_id:
                            continue
                        result = await self._tools.execute(name, args)
                        conv.add_anthropic_tool_result(tool_id, result)
                    continue

                if text:
                    conv.add_assistant(text)
                    await self._hooks.run_stop({"final": text})
                    return text
            else:
                text, tool_calls, usage = await self.runtime.openai_with_tools(
                    messages=conv.to_openai_messages(system_prompt),
                    tools=self._tools.openai_tools(defs),
                    model=self.cfg.agent.model,
                    max_tokens=self.cfg.agent.maxTokens,
                    temperature=self.cfg.agent.temperature,
                )
                if self._tracker:
                    usage_obj = build_usage(self.cfg.provider.type, self.cfg.agent.model, usage)
                    if usage_obj:
                        self._tracker.record(usage_obj)

                if tool_calls:
                    conv.add_assistant_tool_calls(text, tool_calls)
                    for call in tool_calls:
                        fn = call.get("function") or {}
                        name = fn.get("name")
                        raw_args = fn.get("arguments", "{}")
                        try:
                            args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            args = {}
                        tool_id = call.get("id", "")
                        if not name:
                            continue
                        result = await self._tools.execute(name, args)
                        conv.add_tool(tool_id, name, result)
                    continue

                if text:
                    conv.add_assistant(text)
                    await self._hooks.run_stop({"final": text})
                    return text

        fallback = "Sorry, I reached the maximum tool iterations."
        await self._hooks.run_stop({"final": fallback})
        return fallback

    async def _maybe_compact(self, conv) -> None:
        if not self._store.should_compact(conv):
            return
        old = self._store.compact_messages(conv)
        if not old:
            return
        summary_input = _messages_to_text(old)
        req = RuntimeRequest(
            prompt=f"Summarize the following conversation succinctly, keep important facts and decisions:\n{summary_input}",
            system_prompt="You are a concise summarizer.",
            model=self.cfg.agent.model,
            max_tokens=min(512, self.cfg.agent.maxTokens),
            temperature=0.2,
        )
        summary, _ = await self.runtime.run(req)
        conv.summary = summary.strip()


class PathLike:
    @staticmethod
    def exists(path: str) -> bool:
        return Path(path).exists()

    @staticmethod
    def read(path: str) -> str:
        return Path(path).read_text(encoding="utf-8")


from pathlib import Path


def _messages_to_text(messages: List[Dict[str, Any]]) -> str:
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _pick_skill_dir(workspace: str) -> str:
    recipes = Path(f"{workspace}/recipes")
    skills = Path(f"{workspace}/skills")
    if recipes.exists():
        return str(recipes)
    return str(skills)
