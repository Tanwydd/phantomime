# Performance Tuning

Practical guidance for squeezing maximum throughput out of Phantomime while keeping sessions stable and undetected.

---

## Table of Contents

- [Baseline Numbers](#baseline-numbers)
- [RAM Planning](#ram-planning)
- [Concurrency Strategy](#concurrency-strategy)
- [Browser Reuse vs Per-URL Launch](#browser-reuse-vs-per-url-launch)
- [fetch() vs Browser Navigation](#fetch-vs-browser-navigation)
- [Profile Warmup Cost](#profile-warmup-cost)
- [Headless vs Headed](#headless-vs-headed)
- [System Chrome vs Playwright Chromium](#system-chrome-vs-playwright-chromium)
- [Profiling Your Workload](#profiling-your-workload)
- [Tuning Reference Table](#tuning-reference-table)

---

## Baseline Numbers

Measured on a mid-range Linux machine (8-core, 16 GB RAM, SSD, 100 Mbps connection). Your numbers will vary based on target site complexity, network latency, and hardware.

| Operation | Typical duration |
|-----------|-----------------|
| Browser launch (cold, Playwright Chromium) | 1.5 – 2.5 s |
| Browser launch (warm profile, system Chrome) | 0.8 – 1.5 s |
| `goto()` — simple static page | 0.5 – 1.5 s |
| `goto()` — SPA with API calls | 1.5 – 4.0 s |
| `goto()` — heavy JS (React/Vue, many requests) | 3.0 – 8.0 s |
| `type_text()` — 20 chars, default typo rate | 1.5 – 3.0 s |
| `click()` + wait | 0.3 – 0.8 s |
| `fetch()` — simple JSON endpoint | 0.05 – 0.3 s |
| `warmup()` — 4 seconds | 4.0 s (fixed) |
| `idle()` — 2 seconds | 2.0 s (fixed) |

**Key ratio:** `fetch()` is 10–50x faster than `browser.goto()` for data endpoints. Always use `fetch()` for the data collection phase after authentication.

---

## RAM Planning

Each headless Chromium instance uses approximately **300–400 MB** of RAM at steady state. Pages with heavy JS or many iframes can push this to 500–600 MB.

| Workers | RAM needed | Recommended system RAM |
|---------|------------|----------------------|
| 5       | ~2 GB      | 4 GB                 |
| 10      | ~4 GB      | 8 GB                 |
| 20      | ~8 GB      | 16 GB                |
| 40      | ~16 GB     | 32 GB                |

**HAL-9000 safe ceiling:** with 16 GB total RAM and typical system + OS usage (~2–3 GB), keep `max_concurrent` at or below **10–12** for comfortable operation.

Monitor actual RAM usage during your first run:

```bash
# Watch Chromium processes
watch -n 2 'ps aux | grep chromium | grep -v grep | awk "{sum += \$6} END {print sum/1024 \" MB total\"}"'
```

---

## Concurrency Strategy

### run_swarm (asyncio) — for I/O-bound workloads

All scraping is I/O-bound: the CPU waits for network, DNS, rendering. `run_swarm` runs all workers on the same event loop — zero overhead from process spawning or IPC.

```python
results = await run_swarm(
    task=my_task,
    items=my_list,
    max_concurrent=10,   # tune to RAM
    browser_kwargs={"headless": True},
    profile_base_dir="./profiles",
)
```

### run_swarm_multiprocess — for CPU-bound post-processing

If each scraped item requires heavy CPU work (ML inference, image processing, complex parsing), the GIL will bottleneck `run_swarm`. Use `run_swarm_multiprocess` to distribute across OS processes.

```python
results = await run_swarm_multiprocess(
    task=my_task,        # must be picklable — no closures over unpicklable objects
    items=my_list,
    max_concurrent=20,   # total concurrent browsers across all processes
    workers=4,           # number of OS processes
    browser_kwargs={"headless": True},
    profile_base_dir="./profiles",
)
```

### Manual asyncio.gather — for heterogeneous workloads

When different items need different browser configurations (different proxies, locales, or targets), bypass `run_swarm` and manage the semaphore manually:

```python
sem = asyncio.Semaphore(8)

async def worker(item: dict) -> dict:
    async with sem:
        async with HumanBrowser(
            profile_dir=f"./profiles/{item['region']}",
            locale=item["locale"],
            proxy={"server": item["proxy"]},
            headless=True,
        ) as browser:
            return await scrape(browser, item)

results = await asyncio.gather(*[worker(item) for item in items])
```

---

## Browser Reuse vs Per-URL Launch

This is the single biggest performance lever for batch workloads.

```python
# ❌ Slow — 1.5–2.5s overhead per URL
for url in urls:
    async with HumanBrowser(profile_dir="./profiles/test") as browser:
        await browser.goto(url)
        data = await extract(browser)

# ✅ Fast — launch cost paid once per worker
async with HumanBrowser(profile_dir="./profiles/test") as browser:
    for url in urls:
        await browser.goto(url)
        data = await extract(browser)
        await browser.wait_between_actions()
```

`run_swarm` handles this automatically — each worker browser stays open for the lifetime of the swarm.

**When to open a new browser mid-session:**

- The session has been blocked and you need a fresh fingerprint
- The profile has accumulated enough state that pages load differently
- You are rotating proxies and need a fresh network context

---

## fetch() vs Browser Navigation

After authentication, switch to `fetch()` for all data endpoints:

```python
async with HumanBrowser(profile_dir="./profiles/api") as browser:
    # Phase 1 — authenticate via browser (required once)
    await browser.goto("https://target.com/login")
    await browser.type_text("#email", EMAIL)
    await browser.type_text("#password", PASSWORD)
    await browser.click("#submit")
    await browser.wait_for(".dashboard")

    # Export session
    await browser.sync_cookies_to_session("https://target.com")

    # Phase 2 — data collection via fetch() — 10–50x faster
    results = []
    for item_id in item_ids:
        resp = await browser.fetch(f"https://target.com/api/items/{item_id}")
        results.append(resp.json())
```

**When you must use `browser.goto()` for data:**

- The page renders data client-side via JS (no API endpoint)
- The endpoint checks the `Referer` or `Origin` header against a navigation context
- The data is inside an iframe that requires navigation

---

## Profile Warmup Cost

| Method | Duration | When to use |
|--------|----------|-------------|
| `warmup(duration_s=3)` | 3 s | Sites with basic behavioral analysis |
| `warmup(duration_s=6)` | 6 s | Sites with strict behavioral analysis |
| No warmup | 0 s | Internal APIs, low-security targets |

For high-volume swarms, warmup adds `duration_s` seconds per worker to the startup time. With 10 workers and `warmup(3)`, that is 30 seconds of warmup total — but all 10 run in parallel, so wall time is still just 3 seconds.

To skip warmup for trusted targets and only use it for high-security ones:

```python
async def task(browser: HumanBrowser, item: dict) -> dict:
    if item.get("high_security"):
        await browser.warmup(duration_s=4.0)
    await browser.goto(item["url"])
    return await extract(browser, item)
```

---

## Headless vs Headed

| Mode | RAM per instance | Launch time | GPU rendering | Use case |
|------|-----------------|-------------|---------------|----------|
| `headless=True` (`--headless=new`) | ~350 MB | ~1.5 s | Yes (software fallback) | Production |
| `headless=False` | ~400 MB | ~2.0 s | Yes (full) | Debugging, manual sessions |

Always use `headless=True` in production. The difference in GPU rendering quality between `--headless=new` and headed mode is negligible for fingerprinting purposes on machines with a real GPU.

---

## System Chrome vs Playwright Chromium

| | Playwright Chromium | System Chrome |
|--|--------------------|--------------------|
| TLS fingerprint | Chromium build | Chrome build (closer to real) |
| Launch time | ~2.0 s | ~1.5 s (warm profile) |
| GPU support | Bundled | System GPU drivers |
| Maintenance | Auto with `playwright install` | Manual system updates |
| Recommended for | Development, CI | Production, high-security targets |

```python
# Use system Chrome
HumanBrowser(
    profile_dir="./profiles/prod",
    executable_path="/usr/bin/google-chrome",
    headless=True,
)
```

---

## Profiling Your Workload

Add timing instrumentation to identify bottlenecks:

```python
import time
import asyncio
from phantomime import HumanBrowser

async def timed_task(browser: HumanBrowser, item: dict) -> dict:
    t0 = time.perf_counter()

    await browser.goto(item["url"])
    t1 = time.perf_counter()

    await browser.wait_for(".content")
    t2 = time.perf_counter()

    data = await browser.evaluate("/* extraction JS */")
    t3 = time.perf_counter()

    print(
        f"{item['url'][:50]:50s} | "
        f"goto={t1-t0:.2f}s | "
        f"wait={t2-t1:.2f}s | "
        f"extract={t3-t2:.2f}s | "
        f"total={t3-t0:.2f}s"
    )
    return data
```

Common findings:

- **`goto()` is slow** — target site is heavy. Consider using `wait_until="domcontentloaded"` instead of the default.
- **`wait_for()` is slow** — selector appears late; the page may be making slow API calls before rendering.
- **`evaluate()` is slow** — your JS extraction query is traversing a large DOM. Optimise the selector.

---

## Tuning Reference Table

| Parameter / Decision | Conservative | Balanced | Aggressive |
|---------------------|-------------|----------|------------|
| `max_concurrent` (8 GB RAM) | 5 | 8 | 12 |
| `max_concurrent` (16 GB RAM) | 8 | 12 | 20 |
| `warmup(duration_s)` | 6.0 | 4.0 | 0.0 |
| `typo_rate` | 0.08 | 0.04 | 0.01 |
| `slow_mo` | 100 | 0 | 0 |
| `wait_until` | `"networkidle"` | `"domcontentloaded"` | `"commit"` |
| Browser reuse | Yes | Yes | Yes |
| `fetch()` for APIs | Yes | Yes | Yes |
| Warmup skipped | Never | Low-security only | Always |
| Proxy type | Residential | Residential | Datacenter (risky) |
