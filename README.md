# Phantomime

[![PyPI version](https://img.shields.io/pypi/v/phantomime.svg)](https://pypi.org/project/phantomime/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python >=3.10](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](https://www.python.org/)

**Phantomime** is a humanized Playwright browser with full anti-fingerprinting and real Chrome TLS impersonation via `curl-cffi`. It mimics human behavior at every layer — mouse movement, typing, scrolling, idle activity — while spoofing the browser's hardware and software fingerprint so that automated sessions are indistinguishable from real users.

---

## Features

- **Canvas / WebGL fingerprint noise** — deterministic per-session LCG, no canvas mutation
- **TLS fingerprint** — Chrome 124+ via `curl-cffi`, bidirectional cookie sync with Playwright
- **Human mouse movement** — cubic Bézier paths, overshooting, micro-tremor, Gaussian jitter
- **Human typing** — QWERTY typos with autocorrect, frustration errors, log-normal delays
- **Scroll with inertia** — progressive acceleration, matches browser physics
- **Idle behavior** — random moves, scrolls, hover clusters, micro-tremor
- **6 hardware profiles** — Windows / macOS / Linux, OS-aware selection
- **navigator / screen coherence** — `platform`, `languages`, `plugins`, Client Hints, battery, fonts
- **Network jitter** — simulated via context-level route interception (covers Service Workers)
- **Session warmup & history** — visit referrer sites before the target
- **Swarm execution** — `run_swarm` (asyncio) and `run_swarm_multiprocess` (multiprocessing)

---

## Installation

```bash
pip install phantomime
playwright install chromium
```

To use your system Chrome instead of Playwright's Chromium (better TLS):

```bash
pip install phantomime
# No playwright install needed
```

---

## Quick start

```python
import asyncio
from phantomime import HumanBrowser

async def main():
    async with HumanBrowser(profile_dir="./my_profile", headless=True) as browser:
        await browser.goto("https://example.com")
        title = await browser.get_title()
        print(title)

asyncio.run(main())
```

---

## HumanBrowser parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `profile_dir` | `str \| Path` | `"./hb_profile"` | Persistent profile directory. Its name seeds the fingerprint. |
| `headless` | `bool` | `False` | Headless mode via `--headless=new` (preserves GPU pipeline). |
| `locale` | `str` | `"es-ES"` | Browser locale — affects `navigator.languages` and `Accept-Language`. |
| `timezone` | `str` | `"Europe/Madrid"` | Timezone ID. Match with your proxy IP. |
| `proxy` | `dict` | `None` | `{"server": "http://host:port", "username": "u", "password": "p"}` |
| `slow_mo` | `float` | `0.0` | Extra delay (ms) between Playwright actions. |
| `fixed_profile` | `bool` | `False` | Always use profile 0 (reproducible fingerprint). |
| `os_aware_profile` | `bool` | `True` | Pick a hardware profile matching the host OS. |
| `disable_service_workers` | `bool` | `False` | Disable Service Workers in Chromium. |
| `typo_rate` | `float` | `0.04` | QWERTY typo probability per character. |
| `frustration_rate` | `float` | `0.01` | Frustration-error probability per character. |
| `executable_path` | `str` | `None` | Path to system Chrome binary. `None` = Playwright's Chromium. |

---

## Available methods

| Category | Methods |
|---|---|
| Lifecycle | `launch`, `close`, `new_page` |
| Navigation | `goto`, `get_url`, `get_title`, `wait_for_url`, `go_back`, `go_forward` |
| Interaction | `click`, `type_text`, `select_option`, `press_key`, `hover`, `focus` |
| Mouse | `move_to`, `move_to_selector`, `micro_tremor`, `pre_drift_to` |
| Scroll | `scroll_down`, `scroll_up`, `scroll_to_element` |
| HTTP (TLS) | `fetch`, `sync_cookies_to_session`, `sync_cookies_from_session`, `sync_cookies` |
| Extraction | `get_text`, `get_all_text`, `get_attribute`, `is_visible`, `evaluate` |
| Utilities | `screenshot`, `wait_for`, `wait_between_actions`, `idle`, `warmup`, `enable_network_jitter`, `warm_history` |

---

## Direct HTTP with TLS fingerprint

Use `fetch()` when you need clean TLS without JS rendering (API calls, simple scraping). Cookies are synced automatically between Playwright and `curl-cffi`.

```python
async with HumanBrowser(profile_dir="./profile") as browser:
    await browser.goto("https://example.com")          # log in via browser
    response = await browser.fetch(                    # call API with same session
        "https://api.example.com/data",
        method="GET",
        mode="xhr",
    )
    print(response.json())
```

`mode` controls `Sec-Fetch-*` headers — use `"xhr"`, `"cors"`, `"navigate"`, or `"no-cors"` to match what a real browser would send.

---

## Swarm execution

### asyncio swarm (< 20 instances, same process)

```python
from phantomime import HumanBrowser, run_swarm

async def scrape(browser: HumanBrowser, url: str) -> str:
    await browser.goto(url)
    return await browser.get_text("h1")

results = await run_swarm(
    task=scrape,
    items=["https://a.com", "https://b.com", "https://c.com"],
    max_concurrent=3,
    browser_kwargs={"headless": True},
)
```

### Multiprocess swarm (large farms, full isolation)

```python
import asyncio
from phantomime import HumanBrowser, run_swarm_multiprocess

def worker(url, profile_dir, browser_kwargs):
    async def _inner():
        async with HumanBrowser(profile_dir=profile_dir, **browser_kwargs) as browser:
            await browser.goto(url)
            return await browser.get_text("h1")
    return asyncio.run(_inner())

if __name__ == "__main__":
    results = run_swarm_multiprocess(
        task_fn=worker,
        items=["https://a.com", "https://b.com"],
        max_workers=2,
        browser_kwargs={"headless": True},
    )
```

---

## License

[MIT](LICENSE)
