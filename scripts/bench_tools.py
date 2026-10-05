"""Measures tool-call latency against a running sandbox, the baseline for the guest agent's <30 ms target.

ZOO_URL=http://localhost:8000 ZOO_TOKEN=... python scripts/bench_tools.py <sandbox_id> [rounds]
"""

import os
import statistics
import sys
import time

import httpx

CALLS = {
    "execute_command": {"command": "true"},
    "screenshot": {},
    "screenshot_webp_half": {"format": "webp", "scale": 0.5},
    "click": {"x": 5, "y": 5},
    "read_file": {"path": "/etc/hostname"},
}


def main():
    sandbox_id = sys.argv[1]
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    client = httpx.Client(
        base_url=os.environ.get("ZOO_URL", "http://localhost:8000"),
        headers={"Authorization": f"Bearer {os.environ['ZOO_TOKEN']}"},
        timeout=60,
    )
    print(f"{'tool':<24}{'p50 ms':>10}{'p95 ms':>10}{'bytes':>10}")
    for label, args in CALLS.items():
        name = label.split("_webp")[0]
        times, size = [], 0
        for _ in range(rounds):
            start = time.perf_counter()
            res = client.post(f"/sandboxes/{sandbox_id}/tools/{name}", json=args)
            times.append((time.perf_counter() - start) * 1000)
            if res.status_code != 200:
                print(f"{label:<24}failed: {res.status_code} {res.text[:80]}")
                break
            size = len(res.content)
        else:
            p95 = statistics.quantiles(times, n=20)[-1] if len(times) > 1 else times[0]
            print(f"{label:<24}{statistics.median(times):>10.1f}{p95:>10.1f}{size:>10}")


if __name__ == "__main__":
    main()
