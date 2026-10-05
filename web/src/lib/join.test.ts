import { describe, expect, it } from "vitest"

import { parseJoinLine } from "./api_client"

describe("parseJoinLine", () => {
  it("reads the line the node installer prints", () => {
    const body = {
      platform: "macos",
      name: "mini",
      docker_url: "ssh://me@10.0.0.5",
      bind_address: "10.0.0.5",
      host_key: "ssh-ed25519 AAAA",
    }
    expect(parseJoinLine(`  zoo-join:${btoa(JSON.stringify(body))} `)).toEqual(
      body
    )
  })

  it("rejects anything else", () => {
    expect(() => parseJoinLine("ssh://me@host")).toThrow(/join line/)
  })
})
