"""CUA (trycua/cua) computer-use agent bound to a sandbox, exposed over REST with SSE streaming.

Each sandbox has at most one run at a time. A run lives in a background task, so it keeps going when
the client that started it disconnects, and any number of clients (the dashboard, an API caller, a
Slack, Discord or WhatsApp relay) can attach to its event stream.
"""

import asyncio
import base64
import io
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

os.environ.setdefault("CUA_TELEMETRY_ENABLED", "false")

from cua_agent import ComputerAgent  # noqa: E402
from cua_agent.types import ToolError  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from PIL import Image  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from db.connection import db_manager  # noqa: E402
from integrations import discord, slack, whatsapp  # noqa: E402
from db.generated.models import Sandbox, User  # noqa: E402
from db.generated.query import CreateAgentChannelParams, CreateAgentMessageParams, Querier, UpsertAgentSettingsParams  # noqa: E402
from logger.logger import logger  # noqa: E402
from server.auth_api import AuthApi  # noqa: E402
from server.sandbox_api import SandboxApi  # noqa: E402
from server.security import decrypt, encrypt  # noqa: E402

MODEL = os.environ.get("ZOO_AGENT_MODEL", "anthropic/claude-sonnet-5-5")
MAX_STEPS = int(os.environ.get("ZOO_AGENT_MAX_STEPS", "100"))
HISTORY = 40
CHANNEL = "cua"
PLATFORMS = ("slack", "discord", "whatsapp")
SCREENS = {"desktop": "a Linux XFCE desktop", "browser": "a Linux desktop running Firefox", "macos": "a macOS desktop", "windows": "a Windows desktop"}
ENVIRONMENTS = {"macos": "mac", "windows": "windows"}
BUTTONS = {"left": "left", "right": "right", "middle": "middle", "wheel": "middle"}


@dataclass(frozen=True)
class Provider:
    label: str
    prefix: str  # prepended to the model name to get the cua/litellm model string
    default_model: str
    env_key: str | None  # read by the provider when the user has not saved a key of their own
    default_base: str | None = None


# Models must support computer use (or be a vision model cua has a loop for, like Qwen3-VL).
PROVIDERS = {
    "anthropic": Provider("Anthropic", "anthropic/", "claude-sonnet-5-5", "ANTHROPIC_API_KEY"),
    "openai": Provider("OpenAI", "openai/", "computer-use-preview", "OPENAI_API_KEY"),
    # cua's Gemini loop only matches bare model names and calls the Gemini API directly
    "gemini": Provider("Google Gemini", "", "gemini-2.5-computer-use-preview-10-2025", "GOOGLE_API_KEY"),
    "openrouter": Provider("OpenRouter", "openrouter/", "qwen/qwen3-vl-235b-a22b-instruct", "OPENROUTER_API_KEY"),
    "ollama": Provider("Ollama", "ollama_chat/", "qwen3-vl", None, "http://localhost:11434"),
}


@dataclass(frozen=True)
class ModelConfig:
    model: str
    api_key: str | None = None
    api_base: str | None = None


class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    model: str | None = Field(default=None, max_length=200)
    stream: bool = True


class AgentMessageResponse(BaseModel):
    id: str
    kind: str
    content: str
    source: str
    created_at: str


class AgentStateResponse(BaseModel):
    running: bool
    model: str
    messages: list[AgentMessageResponse]


class ProviderResponse(BaseModel):
    id: str
    label: str
    default_model: str
    default_base: str | None
    needs_key: bool
    server_key: bool


class AgentSettingsRequest(BaseModel):
    provider: Literal["anthropic", "openai", "gemini", "openrouter", "ollama"]
    model: str = Field(min_length=1, max_length=200)
    # None keeps the saved key, "" removes it
    api_key: str | None = Field(default=None, max_length=500)
    api_base: str | None = Field(default=None, max_length=500)


class AgentSettingsResponse(BaseModel):
    provider: str | None
    model: str
    has_api_key: bool
    api_base: str | None
    default_model: str
    providers: list[ProviderResponse]


class ChannelRequest(BaseModel):
    platform: Literal["slack", "discord", "whatsapp"]
    external_id: str = Field(min_length=1, max_length=100)


class ChannelResponse(BaseModel):
    id: str
    platform: str
    external_id: str
    created_at: str


class IntegrationResponse(BaseModel):
    platform: str
    configured: bool
    webhook_path: str | None


def normalize(platform: str, external_id: str) -> str:
    value = external_id.strip()
    if platform == "whatsapp":
        return "".join(c for c in value if c.isdigit())
    if platform == "slack":
        return value.upper()
    return value


def summarize(action: dict) -> str:
    kind = action.get("type", "action")
    if kind in ("click", "double_click", "move"):
        button = action.get("button", "left")
        prefix = f"{button} click" if kind == "click" and button != "left" else kind.replace("_", " ")
        return f"{prefix} {action.get('x')}, {action.get('y')}"
    if kind == "type":
        text = action.get("text", "")
        return f'type "{text[:80]}{"…" if len(text) > 80 else ""}"'
    if kind == "keypress":
        keys = action.get("keys", [])
        return "press " + ("+".join(keys) if isinstance(keys, list) else str(keys))
    if kind == "scroll":
        return f"scroll {action.get('scroll_x', 0)}, {action.get('scroll_y', 0)} at {action.get('x')}, {action.get('y')}"
    if kind == "drag":
        path = action.get("path") or [{}]
        return f"drag {path[0].get('x')}, {path[0].get('y')} → {path[-1].get('x')}, {path[-1].get('y')}"
    if kind == "wait":
        return "wait"
    return kind.replace("_", " ")


def events_of(item: dict) -> list[tuple[str, str, dict]]:
    """Turns one CUA response item into (kind, content, extra) events. Tool outputs carry screenshots and are dropped."""
    kind = item.get("type")
    if kind == "message" and item.get("role") == "assistant":
        content = item.get("content")
        text = content if isinstance(content, str) else "".join(c.get("text", "") for c in content or [] if isinstance(c, dict))
        return [("text", text, {})] if text.strip() else []
    if kind == "reasoning":
        text = "\n".join(s.get("text", "") for s in item.get("summary") or [] if isinstance(s, dict))
        return [("reasoning", text, {})] if text.strip() else []
    if kind == "computer_call":
        action = item.get("action") or {}
        return [("action", summarize(action), {"action": action})]
    if kind == "function_call":
        return [("action", f"{item.get('name')}({item.get('arguments', '')})", {})]
    return []


class ZooComputer:
    """Implements cua_agent's AsyncComputerHandler protocol on top of the sandbox tool registry, so agent actions
    go through the same permission checks and Activity log as API and MCP calls, on Linux, macOS and Windows."""

    def __init__(self, sandboxes: SandboxApi, user: User, sandbox: Sandbox):
        self.sandboxes = sandboxes
        self.user = user
        self.sandbox = sandbox
        self.size: tuple[int, int] | None = None

    async def call(self, name: str, **args) -> Any:
        try:
            return await self.sandboxes.run_tool(self.user, self.sandbox.id, name, args, CHANNEL)
        except HTTPException as e:
            raise ToolError(str(e.detail))

    async def get_environment(self) -> str:
        return ENVIRONMENTS.get(self.sandbox.kind, "linux")

    async def get_dimensions(self) -> tuple[int, int]:
        if self.size is None:
            await self.screenshot()
        return self.size

    async def screenshot(self, text: str | None = None) -> str:
        data = await self.call("screenshot")
        if self.size is None:
            self.size = Image.open(io.BytesIO(base64.b64decode(data))).size
        return data

    async def click(self, x: int, y: int, button: str = "left") -> None:
        await self.call("click", x=x, y=y, button=BUTTONS.get(button, "left"))

    async def double_click(self, x: int, y: int) -> None:
        await self.call("double_click", x=x, y=y)

    async def scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
        # cua's convention: positive scroll_y scrolls up, positive scroll_x scrolls left
        if scroll_y:
            await self.call("scroll", direction="up" if scroll_y > 0 else "down", amount=abs(scroll_y), x=x, y=y)
        if scroll_x:
            await self.call("scroll", direction="left" if scroll_x > 0 else "right", amount=abs(scroll_x), x=x, y=y)

    async def type(self, text: str) -> None:
        await self.call("type_text", text=text)

    async def wait(self, ms: int = 1000) -> None:
        await asyncio.sleep(min(ms, 30000) / 1000)

    async def move(self, x: int, y: int) -> None:
        await self.call("move_mouse", x=x, y=y)

    async def keypress(self, keys: list[str] | str) -> None:
        keys = [keys] if isinstance(keys, str) else [k for k in keys if k]
        if len(keys) == 1:
            await self.call("press_key", key=keys[0])
        else:
            await self.call("hotkey", keys=keys)

    async def drag(self, path: list[dict[str, int]]) -> None:
        start, end = path[0], path[-1]
        await self.call("drag", start_x=start["x"], start_y=start["y"], end_x=end["x"], end_y=end["y"])

    async def get_current_url(self) -> str:
        return ""

    async def left_mouse_down(self, x: int | None = None, y: int | None = None) -> None:
        raise ToolError("left_mouse_down is not supported; use drag")

    async def left_mouse_up(self, x: int | None = None, y: int | None = None) -> None:
        raise ToolError("left_mouse_up is not supported; use drag")


@dataclass
class Run:
    sandbox_id: str
    source: str
    events: list[dict] = field(default_factory=list)
    listeners: set[asyncio.Queue] = field(default_factory=set)
    task: asyncio.Task | None = None

    @property
    def done(self) -> bool:
        return bool(self.events) and self.events[-1]["type"] == "done"

    def emit(self, event: dict):
        self.events.append(event)
        for queue in self.listeners:
            queue.put_nowait(event)

    async def stream(self) -> AsyncIterator[dict]:
        """Replays this run's events so far, then follows it until it finishes."""
        queue: asyncio.Queue = asyncio.Queue()
        backlog = list(self.events)
        self.listeners.add(queue)
        try:
            for event in backlog:
                yield event
            if backlog and backlog[-1]["type"] == "done":
                return
            while True:
                event = await queue.get()
                yield event
                if event["type"] == "done":
                    return
        finally:
            self.listeners.discard(queue)


def sse(events: AsyncIterator[dict]) -> StreamingResponse:
    async def body():
        async for event in events:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class AgentApi:
    def __init__(self, app: FastAPI, auth: AuthApi, sandboxes: SandboxApi):
        self.logger = logger
        self.app = app
        self.auth = auth
        self.sandboxes = sandboxes
        self.runs: dict[str, Run] = {}
        self._register_routes()

    def _register_routes(self):
        current_user = self.auth.current_user

        @self.app.get("/sandboxes/{sandbox_id}/agent", response_model=AgentStateResponse)
        def state(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> AgentStateResponse:
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            return AgentStateResponse(
                running=sandbox.id in self.runs,
                model=self.config(user.id, db).model,
                messages=[AgentMessageResponse(**m.model_dump(include=set(AgentMessageResponse.model_fields))) for m in db.list_agent_messages(sandbox_id=sandbox.id)],
            )

        @self.app.post("/sandboxes/{sandbox_id}/agent")
        async def chat(sandbox_id: str, payload: AgentRequest, user: User = Depends(current_user)):
            run = self.start(user, sandbox_id, payload.message, "api", payload.model)
            if payload.stream:
                return sse(run.stream())
            return {"events": [e async for e in run.stream()]}

        @self.app.get("/sandboxes/{sandbox_id}/agent/stream")
        def attach(sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)):
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            run = self.runs.get(sandbox.id)
            if run is None:
                raise HTTPException(status_code=404, detail="the agent is not running")
            return sse(run.stream())

        @self.app.post("/sandboxes/{sandbox_id}/agent/stop", status_code=204)
        def stop(sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)):
            self.stop(self.sandboxes.owned(sandbox_id, user, db).id)

        @self.app.delete("/sandboxes/{sandbox_id}/agent", status_code=204)
        def reset(sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)):
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            if sandbox.id in self.runs:
                raise HTTPException(status_code=409, detail="stop the agent before clearing the conversation")
            db.delete_agent_messages(sandbox_id=sandbox.id)

        @self.app.get("/agent/settings", response_model=AgentSettingsResponse)
        def get_settings(user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)) -> AgentSettingsResponse:
            return self.settings_response(db.get_agent_settings(user_id=user.id))

        @self.app.put("/agent/settings", response_model=AgentSettingsResponse)
        def put_settings(
            payload: AgentSettingsRequest, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> AgentSettingsResponse:
            saved = db.get_agent_settings(user_id=user.id)
            if payload.api_key is None:
                key_ref = saved.api_key_ref if saved and saved.provider == payload.provider else None
            else:
                key_ref = encrypt(payload.api_key.strip()) if payload.api_key.strip() else None
            settings = db.upsert_agent_settings(
                UpsertAgentSettingsParams(
                    user_id=user.id,
                    provider=payload.provider,
                    model=payload.model.strip(),
                    api_key_ref=key_ref,
                    api_base=(payload.api_base or "").strip() or None,
                )
            )
            return self.settings_response(settings)

        @self.app.delete("/agent/settings", response_model=AgentSettingsResponse)
        def reset_settings(user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)) -> AgentSettingsResponse:
            db.delete_agent_settings(user_id=user.id)
            return self.settings_response(None)

        @self.app.get("/agent/integrations", response_model=list[IntegrationResponse])
        def integrations(user: User = Depends(current_user)) -> list[IntegrationResponse]:
            return [
                IntegrationResponse(platform="slack", configured=slack.configured(), webhook_path=slack.WEBHOOK_PATH),
                IntegrationResponse(platform="discord", configured=discord.configured(), webhook_path=None),
                IntegrationResponse(platform="whatsapp", configured=whatsapp.configured(), webhook_path=whatsapp.WEBHOOK_PATH),
            ]

        @self.app.get("/sandboxes/{sandbox_id}/agent/channels", response_model=list[ChannelResponse])
        def list_channels(
            sandbox_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> list[ChannelResponse]:
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            return [ChannelResponse(**c.model_dump(include=set(ChannelResponse.model_fields))) for c in db.list_agent_channels_by_sandbox(sandbox_id=sandbox.id)]

        @self.app.post("/sandboxes/{sandbox_id}/agent/channels", response_model=ChannelResponse, status_code=201)
        def add_channel(
            sandbox_id: str, payload: ChannelRequest, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ) -> ChannelResponse:
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            external_id = normalize(payload.platform, payload.external_id)
            if not external_id:
                raise HTTPException(status_code=422, detail="enter a channel ID or phone number")
            if db.get_agent_channel(platform=payload.platform, external_id=external_id) is not None:
                raise HTTPException(status_code=409, detail=f"that {payload.platform} channel is already linked to a sandbox")
            channel = db.create_agent_channel(
                CreateAgentChannelParams(
                    id=str(uuid.uuid4()), sandbox_id=sandbox.id, platform=payload.platform, external_id=external_id, created_by=user.id
                )
            )
            return ChannelResponse(**channel.model_dump(include=set(ChannelResponse.model_fields)))

        @self.app.delete("/sandboxes/{sandbox_id}/agent/channels/{channel_id}", status_code=204)
        def remove_channel(
            sandbox_id: str, channel_id: str, user: User = Depends(current_user), db: Querier = Depends(db_manager.get_client)
        ):
            sandbox = self.sandboxes.owned(sandbox_id, user, db)
            channel = db.get_agent_channel_by_id(id=channel_id)
            if channel is None or channel.sandbox_id != sandbox.id:
                raise HTTPException(status_code=404, detail="channel not found")
            db.delete_agent_channel(id=channel.id)

    def config(self, user_id: str, db: Querier) -> ModelConfig:
        """The user's saved provider and model, or the server default (ZOO_AGENT_MODEL with keys from the environment)."""
        settings = db.get_agent_settings(user_id=user_id)
        if settings is None:
            return ModelConfig(model=MODEL)
        provider = PROVIDERS[settings.provider]
        return ModelConfig(
            model=provider.prefix + settings.model,
            api_key=decrypt(settings.api_key_ref) if settings.api_key_ref else None,
            api_base=settings.api_base or provider.default_base,
        )

    def settings_response(self, settings) -> AgentSettingsResponse:
        return AgentSettingsResponse(
            provider=settings.provider if settings else None,
            model=settings.model if settings else MODEL,
            has_api_key=bool(settings and settings.api_key_ref),
            api_base=settings.api_base if settings else None,
            default_model=MODEL,
            providers=[
                ProviderResponse(
                    id=id,
                    label=p.label,
                    default_model=p.default_model,
                    default_base=p.default_base,
                    needs_key=p.env_key is not None,
                    server_key=bool(p.env_key and os.environ.get(p.env_key)),
                )
                for id, p in PROVIDERS.items()
            ],
        )

    def start(self, user: User, sandbox_id: str, text: str, source: str, model: str | None = None) -> Run:
        """Records the user's message and starts a run in the background. Must be called on the event loop."""
        with db_manager.session() as db:
            sandbox = self.sandboxes.running(sandbox_id, user, db)
            if sandbox.kind == "code":
                raise HTTPException(status_code=400, detail="the computer-use agent needs a desktop; code sandboxes have no screen")
            if sandbox.id in self.runs:
                raise HTTPException(status_code=409, detail="the agent is already working in this sandbox")
            history = self.history(sandbox.id, db)
            config = self.config(user.id, db)
            if model:
                config = ModelConfig(model=model, api_key=config.api_key, api_base=config.api_base)
            self.record(db, sandbox.id, "user", text, source)
        run = Run(sandbox_id=sandbox.id, source=source)
        run.emit({"type": "user", "text": text, "source": source})
        self.runs[sandbox.id] = run
        run.task = asyncio.create_task(self.execute(run, user, sandbox, [*history, {"role": "user", "content": text}], config))
        return run

    def stop(self, sandbox_id: str) -> bool:
        run = self.runs.get(sandbox_id)
        if run is None or run.task is None:
            return False
        run.task.cancel()
        return True

    def clear(self, sandbox_id: str) -> bool:
        if sandbox_id in self.runs:
            return False
        with db_manager.session() as db:
            db.delete_agent_messages(sandbox_id=sandbox_id)
        return True

    def history(self, sandbox_id: str, db: Querier) -> list[dict]:
        """Earlier turns as plain user/assistant text. Actions and screenshots stay out; the agent takes a fresh screenshot."""
        turns = [m for m in db.list_agent_messages(sandbox_id=sandbox_id) if m.kind in ("user", "text")]
        return [{"role": "user" if m.kind == "user" else "assistant", "content": m.content} for m in turns[-HISTORY:]]

    def record(self, db: Querier, sandbox_id: str, kind: str, content: str, source: str):
        db.create_agent_message(
            CreateAgentMessageParams(id=str(uuid.uuid4()), sandbox_id=sandbox_id, kind=kind, content=content, source=source)
        )

    def emit(self, run: Run, kind: str, content: str, extra: dict | None = None):
        with db_manager.session() as db:
            self.record(db, run.sandbox_id, kind, content, run.source)
        run.emit({"type": kind, "text": content, **(extra or {})})

    async def execute(self, run: Run, user: User, sandbox: Sandbox, messages: list[dict], config: ModelConfig):
        computer = ZooComputer(self.sandboxes, user, sandbox)
        steps = 0
        try:
            agent = ComputerAgent(
                model=config.model,
                api_key=config.api_key,
                api_base=config.api_base,
                tools=[computer],
                instructions=f"You are operating {SCREENS.get(sandbox.kind, 'a desktop')} inside a Zoo sandbox. "
                "Take a screenshot before acting, work step by step and check the result of each action. "
                "When the task is done, reply with a short summary of what you did.",
                only_n_most_recent_images=3,
                telemetry_enabled=False,
            )
            async for result in agent.run(messages):
                for item in result.get("output", []):
                    for kind, content, extra in events_of(item):
                        self.emit(run, kind, content, extra)
                        steps += kind == "action"
                if steps >= MAX_STEPS:
                    self.emit(run, "error", f"stopped after {MAX_STEPS} actions")
                    break
        except asyncio.CancelledError:
            self.emit(run, "error", "stopped")
        except Exception as e:
            self.logger.error("agent run failed", extra={"sandbox_id": sandbox.id, "error": repr(e)})
            self.emit(run, "error", str(e) or e.__class__.__name__)
        finally:
            self.runs.pop(sandbox.id, None)
            run.emit({"type": "done"})
