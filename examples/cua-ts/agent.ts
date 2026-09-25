import Anthropic from "@anthropic-ai/sdk"

const ZOO_URL = process.env.ZOO_URL ?? "http://localhost:8000"
const ZOO_API_KEY = process.env.ZOO_API_KEY!
const MODEL = process.env.MODEL ?? "claude-sonnet-5"
const TOOL_VERSION = process.env.TOOL_VERSION ?? "computer_20251124"
const BETA = process.env.BETA ?? "computer-use-2025-11-24"
const [WIDTH, HEIGHT] = [1280, 720]

type Content = Anthropic.Beta.BetaToolResultBlockParam["content"]

async function zoo(path: string, body?: unknown, raw = false) {
  const res = await fetch(`${ZOO_URL}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Authorization: `Bearer ${ZOO_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return raw ? res : res.json()
}

async function createSandbox(name: string) {
  const sandbox = await zoo("/sandboxes", { name, kind: "desktop" })
  for (;;) {
    const s = await zoo(`/sandboxes/${sandbox.id}`)
    if (s.status === "running") return s.id as string
    if (s.status !== "provisioning") throw new Error(`sandbox ${s.status}: ${s.error_message}`)
    await Bun.sleep(1000)
  }
}

function tool(id: string, name: string, args: Record<string, unknown> = {}) {
  return zoo(`/sandboxes/${id}/tools/${name}`, args)
}

async function screenshot(id: string): Promise<Content> {
  const res = (await zoo(`/sandboxes/${id}/screenshot`, {}, true)) as Response
  const data = Buffer.from(await res.arrayBuffer()).toString("base64")
  return [{ type: "image", source: { type: "base64", media_type: "image/png", data } }]
}

const xdotool = (id: string, args: string) =>
  tool(id, "execute_command", { command: `DISPLAY=:1 xdotool ${args}` })

async function computer(id: string, input: Record<string, any>): Promise<Content> {
  const [x, y] = input.coordinate ?? []
  switch (input.action) {
    case "left_click":
    case "right_click":
    case "middle_click":
      await tool(id, "click", { x, y, button: input.action.split("_")[0] })
      break
    case "double_click":
      await tool(id, "double_click", { x, y })
      break
    case "triple_click":
      await xdotool(id, `mousemove ${x} ${y} click --repeat 3 1`)
      break
    case "mouse_move":
      await xdotool(id, `mousemove ${x} ${y}`)
      break
    case "left_click_drag": {
      const [sx, sy] = input.start_coordinate
      await tool(id, "drag", { start_x: sx, start_y: sy, end_x: x, end_y: y })
      break
    }
    case "type":
      await tool(id, "type_text", { text: input.text })
      break
    case "key":
      await tool(id, "press_key", { key: input.text })
      break
    case "scroll":
      await tool(id, "scroll", {
        direction: input.scroll_direction,
        amount: input.scroll_amount ?? 3,
        x,
        y,
      })
      break
    case "wait":
      await Bun.sleep((input.duration ?? 1) * 1000)
      break
    case "screenshot":
      break
    default:
      return [{ type: "text", text: `unsupported action ${input.action}` }]
  }
  await Bun.sleep(300)
  return screenshot(id)
}

async function bash(id: string, input: Record<string, any>): Promise<Content> {
  if (!input.command) return [{ type: "text", text: "ok" }]
  const r = await tool(id, "execute_command", { command: input.command, timeout: 120 })
  return [{ type: "text", text: `exit ${r.exit_code}\n${r.stdout}\n${r.stderr}`.slice(-20000) }]
}

async function run(id: string, task: string) {
  const client = new Anthropic()
  const messages: Anthropic.Beta.BetaMessageParam[] = [{ role: "user", content: task }]
  for (let step = 0; step < 50; step++) {
    const response = await client.beta.messages.create({
      model: MODEL,
      max_tokens: 4096,
      betas: [BETA],
      system: "You control a Linux XFCE desktop. Take a screenshot first, act step by step, verify with screenshots.",
      tools: [
        { type: TOOL_VERSION, name: "computer", display_width_px: WIDTH, display_height_px: HEIGHT } as any,
        { type: "bash_20250124", name: "bash" },
      ],
      messages,
    })
    messages.push({ role: "assistant", content: response.content })
    const calls = response.content.filter((b) => b.type === "tool_use")
    for (const b of response.content) if (b.type === "text") console.log(b.text)
    if (calls.length === 0) return
    const results: Anthropic.Beta.BetaToolResultBlockParam[] = []
    for (const call of calls) {
      console.log(`→ ${call.name}`, JSON.stringify(call.input))
      try {
        const handler = call.name === "computer" ? computer : bash
        results.push({ type: "tool_result", tool_use_id: call.id, content: await handler(id, call.input as any) })
      } catch (e) {
        results.push({ type: "tool_result", tool_use_id: call.id, content: String(e), is_error: true })
      }
    }
    messages.push({ role: "user", content: results })
  }
  throw new Error("agent did not finish in 50 steps")
}

const task = process.argv.slice(2).join(" ") || "Open Firefox and search for the weather in Paris"
const id = process.env.SANDBOX_ID ?? (await createSandbox("cua-ts"))
console.log(`sandbox ${id}`)
await run(id, task)
