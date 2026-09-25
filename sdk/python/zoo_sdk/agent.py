import base64
import time
from dataclasses import dataclass, field

import anthropic

from zoo_sdk import Sandbox

WIDTH, HEIGHT = 1280, 720


@dataclass
class Agent:
    sandbox: Sandbox
    model: str = "claude-sonnet-5"
    tool_version: str = "computer_20251124"
    beta: str = "computer-use-2025-11-24"
    max_steps: int = 50
    max_tokens: int = 4096
    system: str = "You control a Linux XFCE desktop. Take a screenshot first, act step by step, verify with screenshots."
    client: anthropic.Anthropic = field(default_factory=anthropic.Anthropic)
    on_step: object = None

    def tools(self) -> list[dict]:
        return [
            {"type": self.tool_version, "name": "computer", "display_width_px": WIDTH, "display_height_px": HEIGHT},
            {"type": "bash_20250124", "name": "bash"},
        ]

    def screenshot(self) -> dict:
        data = base64.b64encode(self.sandbox.screenshot()).decode()
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}

    def xdotool(self, args: str):
        self.sandbox.exec(f"DISPLAY=:1 xdotool {args}")

    def computer(self, action: str, coordinate=None, text=None, **kw) -> list[dict]:
        sb = self.sandbox
        x, y = coordinate or (None, None)
        if action in ("left_click", "right_click", "middle_click"):
            if text:
                self.xdotool(f"keydown {text}")
            sb.click(x=x, y=y, button=action.split("_")[0])
            if text:
                self.xdotool(f"keyup {text}")
        elif action == "double_click":
            sb.double_click(x=x, y=y)
        elif action == "triple_click":
            self.xdotool(f"mousemove {x} {y} click --repeat 3 1")
        elif action == "mouse_move":
            self.xdotool(f"mousemove {x} {y}")
        elif action == "left_click_drag":
            sx, sy = kw["start_coordinate"]
            sb.drag(start_x=sx, start_y=sy, end_x=x, end_y=y)
        elif action == "left_mouse_down":
            self.xdotool("mousedown 1")
        elif action == "left_mouse_up":
            self.xdotool("mouseup 1")
        elif action == "type":
            sb.type_text(text=text)
        elif action == "key":
            sb.press_key(key=text)
        elif action == "hold_key":
            self.xdotool(f"keydown {text} sleep {kw.get('duration', 1)} keyup {text}")
        elif action == "scroll":
            sb.scroll(direction=kw["scroll_direction"], amount=kw.get("scroll_amount", 3), x=x, y=y)
        elif action == "wait":
            time.sleep(kw.get("duration", 1))
        elif action == "cursor_position":
            out = sb.exec("DISPLAY=:1 xdotool getmouselocation")["stdout"]
            return [{"type": "text", "text": out}]
        elif action != "screenshot" and action != "zoom":
            return [{"type": "text", "text": f"unsupported action {action}"}]
        time.sleep(0.3)
        return [self.screenshot()]

    def bash(self, command: str | None = None, restart: bool = False, **_) -> list[dict]:
        if restart or not command:
            return [{"type": "text", "text": "ok"}]
        r = self.sandbox.exec(command, timeout=120)
        return [{"type": "text", "text": f"exit {r['exit_code']}\n{r['stdout']}\n{r['stderr']}"[-20000:]}]

    def run(self, task: str) -> str:
        messages = [{"role": "user", "content": task}]
        for _ in range(self.max_steps):
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                tools=self.tools(),
                messages=messages,
                betas=[self.beta],
            )
            messages.append({"role": "assistant", "content": response.content})
            if self.on_step:
                self.on_step(response)
            calls = [b for b in response.content if b.type == "tool_use"]
            if not calls:
                return "".join(b.text for b in response.content if b.type == "text")
            results = []
            for call in calls:
                try:
                    content, error = getattr(self, call.name)(**call.input), False
                except Exception as e:
                    content, error = [{"type": "text", "text": str(e)}], True
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": error})
            messages.append({"role": "user", "content": results})
        raise RuntimeError(f"agent did not finish in {self.max_steps} steps")


def run(sandbox: Sandbox, task: str, **kwargs) -> str:
    return Agent(sandbox, **kwargs).run(task)
