from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Dict, List, Tuple

import httpx

from .config import ProviderConfig
from .models import ContentBlock

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com"


@dataclass
class RuntimeRequest:
    prompt: str
    system_prompt: str
    model: str
    max_tokens: int
    temperature: float
    content_blocks: List[ContentBlock] | None = None


class RuntimeError(Exception):
    pass


class OpenAICompatClient:
    def __init__(self, api_key: str, base_url: str, timeout: int) -> None:
        self.api_key = api_key
        self.base_url = _normalize_openai_base(base_url)
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def chat(self, messages: List[Dict], model: str, max_tokens: int, temperature: float) -> Tuple[str, Dict]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = await self.client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"openai-compatible error: {resp.status_code} {resp.text}")
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {}) or {}
            return content, usage
        except Exception as exc:
            raise RuntimeError(f"openai-compatible parse error: {exc}") from exc

    async def chat_with_tools(
        self, messages: List[Dict], tools: List[Dict], model: str, max_tokens: int, temperature: float
    ) -> Tuple[str, List[Dict], Dict]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "tools": tools,
            "tool_choice": "auto",
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = await self.client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"openai-compatible error: {resp.status_code} {resp.text}")
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []
        usage = data.get("usage", {}) or {}
        return content, tool_calls, usage

    async def respond_with_files(
        self,
        system_prompt: str,
        prompt: str,
        blocks: List[ContentBlock],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, Dict]:
        file_ids = []
        for idx, block in enumerate(blocks):
            if block.type != "document" or not block.data:
                continue
            file_id = await self._upload_file(block, idx)
            if file_id:
                file_ids.append(file_id)

        if not file_ids:
            return "", {}

        input_items = [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        ]
        for file_id in file_ids:
            input_items[1]["content"].append({"type": "input_file", "file_id": file_id})

        payload = {
            "model": model,
            "input": input_items,
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = await self.client.post(f"{self.base_url}/responses", json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"openai responses error: {resp.status_code} {resp.text}")
        data = resp.json()
        text = _extract_response_text(data)
        usage = data.get("usage", {}) or {}
        return text, usage

    async def _upload_file(self, block: ContentBlock, idx: int) -> str:
        url = f"{self.base_url}/files"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        filename = f"upload_{idx}"
        if block.media_type and "/" in block.media_type:
            ext = block.media_type.split("/")[-1]
            filename += f".{ext}"
        data = base64.b64decode(block.data)
        files = {"file": (filename, data), "purpose": (None, "assistants")}
        resp = await self.client.post(url, files=files, headers=headers)
        if resp.status_code >= 400:
            return ""
        result = resp.json()
        return result.get("id", "")


class AnthropicClient:
    def __init__(self, api_key: str, base_url: str, timeout: int) -> None:
        self.api_key = api_key
        self.base_url = base_url or DEFAULT_ANTHROPIC_BASE
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
        content_blocks: List[ContentBlock] | None = None,
    ) -> Tuple[str, Dict]:
        url = f"{self.base_url}/v1/messages"
        if content_blocks:
            blocks = _anthropic_blocks(user_prompt, content_blocks)
            messages = [{"role": "user", "content": blocks}]
        else:
            messages = [{"role": "user", "content": user_prompt}]

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": messages,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        resp = await self.client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"anthropic error: {resp.status_code} {resp.text}")
        data = resp.json()
        try:
            content = "".join(block.get("text", "") for block in data.get("content", [])).strip()
            usage = data.get("usage", {}) or {}
            return content, _normalize_anthropic_usage(usage)
        except Exception as exc:
            raise RuntimeError(f"anthropic parse error: {exc}") from exc

    async def chat_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict],
        tools: List[Dict],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, List[Dict], Dict]:
        url = f"{self.base_url}/v1/messages"
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": messages,
            "tools": tools,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        resp = await self.client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"anthropic error: {resp.status_code} {resp.text}")
        data = resp.json()
        content_blocks = data.get("content", [])
        tool_calls = [block for block in content_blocks if block.get("type") == "tool_use"]
        text = "".join(block.get("text", "") for block in content_blocks if block.get("type") == "text").strip()
        usage = data.get("usage", {}) or {}
        return text, tool_calls, _normalize_anthropic_usage(usage)


class Runtime:
    def __init__(self, provider: ProviderConfig) -> None:
        if not provider.apiKey:
            raise RuntimeError("API key not set")

        self.provider = provider
        self._client_openai: OpenAICompatClient | None = None
        self._client_anthropic: AnthropicClient | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._client_openai:
            await self._client_openai.close()
        if self._client_anthropic:
            await self._client_anthropic.close()

    async def run(self, req: RuntimeRequest) -> Tuple[str, Dict]:
        client_type = self.provider.type.lower().strip()
        if client_type == "anthropic":
            if not self._client_anthropic:
                async with self._lock:
                    if not self._client_anthropic:
                        self._client_anthropic = AnthropicClient(
                            api_key=self.provider.apiKey,
                            base_url=self.provider.baseUrl,
                            timeout=self.provider.requestTimeout,
                        )
            return await self._client_anthropic.chat(
                system_prompt=req.system_prompt,
                user_prompt=req.prompt,
                model=req.model,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                content_blocks=req.content_blocks,
            )

        base_url = self.provider.baseUrl
        if client_type in {"deepseek", "minimax"} and not base_url:
            raise RuntimeError("baseUrl is required for deepseek/minimax")

        if not self._client_openai:
            async with self._lock:
                if not self._client_openai:
                    self._client_openai = OpenAICompatClient(
                        api_key=self.provider.apiKey,
                        base_url=base_url or DEFAULT_OPENAI_BASE,
                        timeout=self.provider.requestTimeout,
                    )

        if client_type == "openai" and req.content_blocks:
            docs = [block for block in req.content_blocks if block.type == "document"]
            if docs:
                try:
                    text, usage = await self._client_openai.respond_with_files(
                        req.system_prompt,
                        req.prompt,
                        docs,
                        req.model,
                        req.max_tokens,
                        req.temperature,
                    )
                    if text:
                        return text, usage
                except Exception:
                    pass

        messages = _openai_messages(req)
        return await self._client_openai.chat(
            messages=messages,
            model=req.model,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )

    async def openai_with_tools(
        self, messages: List[Dict], tools: List[Dict], model: str, max_tokens: int, temperature: float
    ) -> Tuple[str, List[Dict], Dict]:
        if not self._client_openai:
            async with self._lock:
                if not self._client_openai:
                    base_url = self.provider.baseUrl or DEFAULT_OPENAI_BASE
                    self._client_openai = OpenAICompatClient(
                        api_key=self.provider.apiKey,
                        base_url=base_url,
                        timeout=self.provider.requestTimeout,
                    )
        return await self._client_openai.chat_with_tools(messages, tools, model, max_tokens, temperature)

    async def openai_doc_context(
        self,
        system_prompt: str,
        prompt: str,
        documents: List[ContentBlock],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, Dict]:
        if not documents:
            return "", {}
        if not self._client_openai:
            async with self._lock:
                if not self._client_openai:
                    base_url = self.provider.baseUrl or DEFAULT_OPENAI_BASE
                    self._client_openai = OpenAICompatClient(
                        api_key=self.provider.apiKey,
                        base_url=base_url,
                        timeout=self.provider.requestTimeout,
                    )
        return await self._client_openai.respond_with_files(
            system_prompt=system_prompt,
            prompt=prompt,
            blocks=documents,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def anthropic_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict],
        tools: List[Dict],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, List[Dict], Dict]:
        if not self._client_anthropic:
            async with self._lock:
                if not self._client_anthropic:
                    self._client_anthropic = AnthropicClient(
                        api_key=self.provider.apiKey,
                        base_url=self.provider.baseUrl,
                        timeout=self.provider.requestTimeout,
                    )
        return await self._client_anthropic.chat_with_tools(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )


def _normalize_openai_base(base_url: str) -> str:
    if not base_url:
        return DEFAULT_OPENAI_BASE
    if base_url.endswith("/"):
        base_url = base_url[:-1]
    if base_url.endswith("/v1"):
        return base_url
    return base_url + "/v1"


def _openai_messages(req: RuntimeRequest) -> List[Dict]:
    if not req.content_blocks:
        return [
            {"role": "system", "content": req.system_prompt},
            {"role": "user", "content": req.prompt},
        ]

    user_content: List[Dict] = [{"type": "text", "text": req.prompt}]
    for block in req.content_blocks:
        if block.type == "image" and block.data and block.media_type:
            url = f"data:{block.media_type};base64,{block.data}"
            user_content.append({"type": "image_url", "image_url": {"url": url}})
        elif block.type == "document":
            label = block.media_type or "document"
            user_content.append({"type": "text", "text": f"[document: {label}]"})

    return [
        {"role": "system", "content": req.system_prompt},
        {"role": "user", "content": user_content},
    ]


def _anthropic_blocks(prompt: str, blocks: List[ContentBlock]) -> List[Dict]:
    items: List[Dict] = []
    if prompt.strip():
        items.append({"type": "text", "text": prompt})
    for block in blocks:
        if block.type == "image" and block.data and block.media_type:
            items.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": block.media_type, "data": block.data},
                }
            )
        elif block.type == "document" and block.data and block.media_type:
            items.append(
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": block.media_type, "data": block.data},
                }
            )
    return items


def _normalize_anthropic_usage(usage: Dict) -> Dict:
    if not usage:
        return {}
    prompt = usage.get("input_tokens", 0)
    completion = usage.get("output_tokens", 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _extract_response_text(data: Dict) -> str:
    output = data.get("output", [])
    parts = []
    for item in output:
        if item.get("type") == "output_text":
            parts.append(item.get("text", ""))
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
    return "\n".join(parts).strip()
