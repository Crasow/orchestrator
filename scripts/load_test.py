"""
Load-test script: sends N concurrent requests through the orchestrator proxy
and reports per-status-code counts, latencies, and rate-limit hits.

Usage:
    python scripts/load_test.py --url http://localhost:8000 --concurrent 100 --model gemini-2.5-flash
"""

import argparse
import asyncio
import time

import httpx


BODY = {
    "contents": [{"parts": [{"text": "Say hi in one word"}]}],
    "generationConfig": {"maxOutputTokens": 5},
}


async def send_request(
    client: httpx.AsyncClient,
    url: str,
    idx: int,
    timeout: float,
) -> dict:
    start = time.perf_counter()
    try:
        print(f"  [#{idx:03d}] sending...")
        resp = await client.post(url, json=BODY, timeout=timeout)
        elapsed = time.perf_counter() - start
        status_icon = "OK" if resp.status_code == 200 else f"ERR {resp.status_code}"
        print(f"  [#{idx:03d}] {status_icon} in {elapsed:.2f}s")
        return {
            "idx": idx,
            "status": resp.status_code,
            "elapsed": elapsed,
            "body": resp.text[:300],
        }
    except Exception as e:
        elapsed = time.perf_counter() - start
        print(f"  [#{idx:03d}] FAIL in {elapsed:.2f}s — {type(e).__name__}")
        return {
            "idx": idx,
            "status": 0,
            "elapsed": elapsed,
            "body": str(e)[:300],
        }


async def main():
    parser = argparse.ArgumentParser(description="Orchestrator load test")
    parser.add_argument("--url", default="http://localhost:8001", help="Base URL")
    parser.add_argument("--concurrent", type=int, default=100, help="Number of concurrent requests")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Model name")
    parser.add_argument("--action", default="generateContent",
                        help="Action (generateContent / streamGenerateContent)")
    parser.add_argument("--timeout", type=float, default=30, help="Per-request timeout in seconds")
    args = parser.parse_args()

    endpoint = f"{args.url}/v1/models/{args.model}:{args.action}"

    print("=" * 60)
    print(f"  Target:      {endpoint}")
    print(f"  Concurrent:  {args.concurrent}")
    print(f"  Timeout:     {args.timeout}s per request")
    print("=" * 60)
    print()
    print(f"Launching {args.concurrent} requests...\n")

    async with httpx.AsyncClient() as client:
        t0 = time.perf_counter()
        tasks = [
            send_request(client, endpoint, i, args.timeout)
            for i in range(args.concurrent)
        ]
        results = await asyncio.gather(*tasks)
        wall = time.perf_counter() - t0

    # --- Report ---
    status_counts: dict[int, int] = {}
    latencies: list[float] = []
    errors: list[dict] = []

    for r in results:
        code = r["status"]
        status_counts[code] = status_counts.get(code, 0) + 1
        latencies.append(r["elapsed"])
        if code != 200:
            errors.append(r)

    latencies.sort()
    ok = status_counts.get(200, 0)
    fail = len(results) - ok

    print()
    print("=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Wall time:   {wall:.2f}s")
    print(f"  Total:       {len(results)} requests")
    print(f"  Success:     {ok}   Failed: {fail}")
    print()
    print("  Status codes:")
    for code, count in sorted(status_counts.items()):
        label = {0: "timeout/conn error", 200: "ok", 429: "RATE LIMITED", 503: "service unavail"}.get(code, "")
        bar = "#" * count
        print(f"    {code:>4d}: {count:>4d}  {bar}  {label}")
    print()
    print(f"  Latency (s): min={latencies[0]:.3f}  p50={latencies[len(latencies)//2]:.3f}  "
          f"p95={latencies[int(len(latencies)*0.95)]:.3f}  max={latencies[-1]:.3f}")

    if errors:
        print(f"\n  First 5 errors:")
        for e in errors[:5]:
            print(f"    [#{e['idx']:03d}] status={e['status']}  {e['body'][:150]}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
