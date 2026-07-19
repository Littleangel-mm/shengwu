import argparse
import asyncio
import statistics
import time

import httpx


async def execute(
    base_url: str, endpoint: str, requests: int, concurrency: int, token: str | None
) -> tuple[list[float], int]:
    semaphore = asyncio.Semaphore(concurrency)
    durations: list[float] = []
    errors = 0
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=20) as client:

        async def request_once() -> None:
            nonlocal errors
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(endpoint)
                    if response.status_code >= 400:
                        errors += 1
                except httpx.HTTPError:
                    errors += 1
                durations.append((time.perf_counter() - started) * 1000)

        await asyncio.gather(*(request_once() for _ in range(requests)))
    return durations, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrent API acceptance smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--endpoint", default="/api/v1/health/ready")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--p95-ms", type=float, default=800)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--token")
    args = parser.parse_args()
    durations, errors = asyncio.run(
        execute(args.base_url, args.endpoint, args.requests, args.concurrency, args.token)
    )
    ordered = sorted(durations)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    error_rate = errors / max(args.requests, 1)
    result = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "mean_ms": round(statistics.fmean(durations), 2),
        "p95_ms": round(p95, 2),
        "errors": errors,
        "error_rate": round(error_rate, 4),
    }
    print(result)
    if p95 > args.p95_ms or error_rate > args.max_error_rate:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
