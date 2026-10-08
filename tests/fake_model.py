"""A scripted model for the computer-use agent, registered with cua like a real provider's loop. The real
ComputerAgent drives it: it runs the scripted actions on the sandbox through ZooComputer and the tool registry, so
a test covers everything but the model call. Use a model name starting with `zoo-fake/`."""

import asyncio
from typing import Any

from cua_agent.decorators import register_agent

MODEL = "zoo-fake/scripted"
# each step is the output of one model call; a step may be a number of seconds to hang instead
script: list[list[dict] | float] = []
# what each model call was given
seen: list[list[dict]] = []
usage = {"prompt_tokens": 500, "completion_tokens": 100, "total_tokens": 600, "response_cost": 0.002}


def click(x: int, y: int, call_id: str = "") -> dict:
    return {
        "type": "computer_call",
        "call_id": call_id or f"call_{x}_{y}",
        "status": "completed",
        "action": {"type": "click", "x": x, "y": y, "button": "left"},
    }


def say(text: str) -> dict:
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


def reset(*steps: list[dict] | float):
    script[:] = list(steps)
    seen.clear()


@register_agent(models=r"^zoo-fake/.*", priority=1000)
class ScriptedLoop:
    async def predict_step(self, messages: list[dict], model: str, tools: Any = None, **kwargs) -> dict:
        seen.append(list(messages))
        step = script.pop(0) if script else [say("Nothing left to do.")]
        if isinstance(step, (int, float)):
            await asyncio.sleep(step)
            step = [say("Done waiting.")]
        return {"output": step, "usage": dict(usage)}

    async def predict_click(self, model: str, image_b64: str, instruction: str, **kwargs):
        return None

    def get_capabilities(self) -> list[str]:
        return ["step"]
