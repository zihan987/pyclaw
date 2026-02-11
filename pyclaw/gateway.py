from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict, List

from .agent import AgentRunner
from .bus import InboundMessage, MessageBus, OutboundMessage
from .config import Config
from .cron import CronService, CronJob
from .heartbeat import HeartbeatService
from .runtime import Runtime
from .tools.mcp import MCPManager
from .channels import (
    TelegramChannel,
    FeishuChannel,
    SlackChannel,
    WebUIChannel,
    BaseChannel,
)


class ChannelManager:
    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus
        self._channels: Dict[str, BaseChannel] = {}

    def add_channel(self, channel: BaseChannel) -> None:
        self._channels[channel.name] = channel

        def handler(msg: OutboundMessage) -> None:
            asyncio.create_task(channel.send(msg))

        self._bus.subscribe_outbound(channel.name, handler)

    async def start_all(self) -> None:
        await asyncio.gather(*(ch.start() for ch in self._channels.values()))

    async def stop_all(self) -> None:
        await asyncio.gather(*(ch.stop() for ch in self._channels.values()))

    def enabled_channels(self) -> List[str]:
        return list(self._channels.keys())


class Gateway:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.bus = MessageBus()
        self._stop_event = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._sem = asyncio.Semaphore(max(1, cfg.agent.maxConcurrency))
        self._mcp: MCPManager | None = None

        if cfg.mcp.servers:
            self._mcp = MCPManager(cfg.mcp.servers)

        self.runtime = Runtime(cfg.provider)
        self.agent = AgentRunner(cfg, self.runtime, self._mcp)

        self.channels = ChannelManager(self.bus)
        if cfg.channels.telegram.enabled:
            self.channels.add_channel(TelegramChannel(cfg.channels.telegram, self.bus))
        if cfg.channels.feishu.enabled:
            self.channels.add_channel(FeishuChannel(cfg.channels.feishu, self.bus))
        if cfg.channels.slack.enabled:
            self.channels.add_channel(SlackChannel(cfg.channels.slack, self.bus))
        if cfg.channels.webui.enabled:
            self.channels.add_channel(WebUIChannel(cfg.channels.webui, cfg.gateway, self.bus))

        store_path = Path.home() / ".ember" / "data" / "cron" / "jobs.json"
        self.cron = CronService(str(store_path))
        self.cron.on_job = self._run_cron_job

        self.heartbeat = HeartbeatService(cfg.agent.workspace, self._run_heartbeat)

    async def run(self) -> None:
        if self._mcp:
            await self._mcp.start()
        await self.channels.start_all()

        bus_task = asyncio.create_task(self.bus.dispatch_outbound(self._stop_event))
        self._tasks.add(bus_task)

        loop_task = asyncio.create_task(self._process_loop())
        self._tasks.add(loop_task)

        await self.cron.start(self._stop_event)
        await self.heartbeat.start(self._stop_event)

        await self._stop_event.wait()
        await self.shutdown()

    def request_stop(self) -> None:
        self._stop_event.set()

    async def shutdown(self) -> None:
        self._stop_event.set()
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.cron.stop()
        await self.heartbeat.stop()
        await self.channels.stop_all()
        if self._mcp:
            await self._mcp.stop()
        await self.runtime.close()

    async def _process_loop(self) -> None:
        while not self._stop_event.is_set():
            msg = await self.bus.inbound.get()
            task = asyncio.create_task(self._handle_message(msg))
            self._tasks.add(task)
            task.add_done_callback(lambda t: self._tasks.discard(t))

    async def _handle_message(self, msg: InboundMessage) -> None:
        async with self._sem:
            try:
                result = await self.agent.run(msg.session_key(), msg.content, msg.content_blocks)
            except Exception:
                result = "Sorry, I encountered an error processing your message."

            if result:
                await self.bus.outbound.put(
                    OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=result)
                )

    async def _run_cron_job(self, job: CronJob) -> str:
        result = await self.agent.run("system", job.payload.message, None)
        if job.payload.deliver and job.payload.channel:
            await self.bus.outbound.put(
                OutboundMessage(
                    channel=job.payload.channel,
                    chat_id=job.payload.to,
                    content=result,
                )
            )
        return result

    async def _run_heartbeat(self, prompt: str) -> str:
        return await self.agent.run("system", prompt, None)
