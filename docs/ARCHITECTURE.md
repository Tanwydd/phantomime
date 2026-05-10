# Architecture

Internal component map for contributors and advanced users who want to understand or extend Phantomime's internals.

---

## Table of Contents

- [High-Level Overview](#high-level-overview)
- [Component Map](#component-map)
- [Initialization Flow](#initialization-flow)
- [Fingerprint Injection Pipeline](#fingerprint-injection-pipeline)
- [LCG Noise System](#lcg-noise-system)
- [Behavioral Layer](#behavioral-layer)
- [TLS Synchronization Layer](#tls-synchronization-layer)
- [Concurrency Model](#concurrency-model)
- [Data Flow: Full Scraping Session](#data-flow-full-scraping-session)
- [Extension Points](#extension-points)

---

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Your application                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                ┌───────────▼──────────┐
                │     HumanBrowser     │   Public API
                └──┬────────────────┬──┘
                   │                │
       ┌───────────▼──────┐  ┌──────▼──────────────┐
       │  Playwright Layer│  │   curl-cffi Layer    │
       │  (Browser + Page)│  │   (TLS HTTP fetch)   │
       └───────┬──────────┘  └──────────────────────┘
               │
       ┌───────▼────────────────────────────────────┐
       │           Fingerprint Injection             │
       │  (add_init_script — runs before page JS)   │
       └───────┬────────────────────────────────────┘
               │
       ┌───────▼──────────────────────────────────────────────────┐
       │                    JS Patches (injected)                  │
       │  Canvas │ WebGL │ Audio │ Navigator │ Chrome │ Events … │
       └──────────────────────────────────────────────────────────┘
```

---

## Component Map

```
phantomime/
└── browser.py
    │
    ├── _PROFILES : list[dict]
    │   Six hardware profile definitions. Each profile is a dict with keys:
    │   width, height, ua, ch_ua, ch_platform, platform_raw,
    │   webgl_vendor, renderer, memory, cores, dpr.
    │
    ├── _lcg_seed(profile_dir: str) -> int
    │   Computes MD5 of the directory name, returns first 8 bytes as int.
    │   Used as the LCG seed for all per-session noise.
    │
    ├── _lcg_next(state: int) -> tuple[int, float]
    │   Single LCG step. Returns (new_state, normalized_float ∈ [0, 1)).
    │   Parameters: a=1664525, c=1013904223, m=2^32 (Numerical Recipes).
    │
    ├── _build_init_script(profile: dict, seed: int) -> str
    │   Constructs the JS string injected via add_init_script().
    │   This is the largest internal function — ~500 lines of JS.
    │   Sections:
    │     1. LCG state initialization (seed embedded as JS literal)
    │     2. Canvas shadow + noise patches
    │     3. WebGL1/2 patches
    │     4. AudioContext patch
    │     5. getBoundingClientRect patch
    │     6. performance.now() patch
    │     7. navigator.* patches (webdriver, platform, plugins, etc.)
    │     8. screen.* patches
    │     9. window.chrome construction
    │     10. Function.prototype.toString spoofing
    │     11. Event.isTrusted patch
    │     12. Battery Status API
    │
    ├── class HumanBrowser
    │   │
    │   ├── __init__(...)
    │   │   Stores config, selects hardware profile, computes LCG seed.
    │   │   Does NOT launch the browser — that happens in launch().
    │   │
    │   ├── launch() -> None
    │   │   Starts Playwright, creates BrowserContext with:
    │   │     - persistent profile directory
    │   │     - locale, timezone, viewport, device_scale_factor
    │   │     - proxy (if set)
    │   │     - extra HTTP headers (Accept-Language, Sec-CH-UA, etc.)
    │   │     - launch args including --headless=new if headless=True
    │   │   Creates first Page, injects init script.
    │   │   Initializes curl-cffi AsyncSession if available.
    │   │
    │   ├── _setup_page(page: Page) -> None
    │   │   Injects the fingerprint init script into a Page.
    │   │   Called for the first page in launch() and for each new_page().
    │   │
    │   ├── _select_profile() -> dict
    │   │   Returns a profile from _PROFILES.
    │   │   fixed_profile=True → always index 0.
    │   │   fixed_profile=False → random.
    │   │
    │   ├── _resolve_browser_type() -> str
    │   │   Returns the curl-cffi BrowserType string matching the active profile's
    │   │   Chrome version. Keeps UA and TLS fingerprint in sync.
    │   │
    │   ├── _session_headers() -> dict
    │   │   Builds headers for curl-cffi requests coherent with the active profile.
    │   │   Includes UA, Accept-Language, Sec-CH-UA, etc.
    │   │
    │   ├── Behavioral methods
    │   │   move_to(), move_to_selector(), click(), type_text()
    │   │   scroll_down(), scroll_up(), scroll_to_element()
    │   │   idle(), warmup(), wait_between_actions()
    │   │
    │   ├── Navigation/DOM methods
    │   │   goto(), content(), get_text(), get_attr(), is_visible()
    │   │   wait_for(), screenshot(), evaluate(), new_page()
    │   │
    │   └── TLS sync methods
    │       sync_cookies_to_session(), sync_cookies_from_session()
    │       sync_cookies(), fetch()
    │
    ├── async run_swarm(task, items, max_concurrent, browser_kwargs, profile_base_dir)
    │   asyncio.Semaphore-based pool.
    │   Each item runs in its own HumanBrowser with profile_base_dir/worker_{n}.
    │   Returns list of task results in input order.
    │
    └── async run_swarm_multiprocess(task, items, max_concurrent, workers, ...)
        multiprocessing.Pool-based pool.
        Each OS process runs its own asyncio event loop with a sub-swarm.
        task must be picklable.
```

---

## Initialization Flow

```
HumanBrowser.__init__()
    │
    ├── _select_profile()        → self._profile
    ├── _lcg_seed(profile_dir)   → self._seed
    └── store config params

HumanBrowser.launch()  (called by __aenter__)
    │
    ├── async_playwright().start()
    ├── playwright.chromium.launch_persistent_context(
    │       user_data_dir = profile_dir,
    │       headless = False,                  ← always False to Playwright
    │       args = ["--headless=new", ...],    ← headless injected here
    │       locale, timezone, viewport,
    │       device_scale_factor, proxy,
    │       extra_http_headers,
    │       executable_path (if set),
    │   )
    ├── context.new_page()
    ├── _setup_page(page)
    │       └── page.add_init_script(_build_init_script(profile, seed))
    └── AsyncSession(browser_type=_resolve_browser_type(), proxies=...)
            (only if curl-cffi is available)
```

---

## Fingerprint Injection Pipeline

All patches are injected as a single JS string via `page.add_init_script()`. This API guarantees the script runs in a fresh JS context before any page script, including `<script>` tags and inline handlers.

The injection order within the script matters:

```
1. LCG state variables (seed → initial state)
         ↓
2. lcg_next() JS function (stateful, advances global LCG state)
         ↓
3. Shadow canvas creation + pre-render with LCG noise
         ↓
4. Canvas API patches (toDataURL, getImageData, toBlob)
   — draw from shadow canvas, not original
         ↓
5. WebGL context patches (getParameter, readPixels)
         ↓
6. AudioContext patch (getChannelData)
         ↓
7. getBoundingClientRect patch (Element + Range)
         ↓
8. performance.now() patch
         ↓
9. navigator patches (webdriver, platform, vendor, plugins,
   languages, deviceMemory, hardwareConcurrency, maxTouchPoints)
         ↓
10. screen patches (width, height, availWidth, availHeight,
    colorDepth, pixelDepth)
         ↓
11. window.outerWidth / outerHeight
         ↓
12. window.chrome construction
         ↓
13. Function.prototype.toString spoofing
    — wraps all patched functions so .toString() returns "native code"
         ↓
14. Event.isTrusted patch
         ↓
15. Battery Status API
```

Step 13 (toString spoofing) must come last — it wraps all previously defined functions. Adding a new patch after step 13 would leave that function's toString unpatched.

---

## LCG Noise System

The noise generator is a 32-bit Linear Congruential Generator using Numerical Recipes parameters:

```
state(n+1) = (1664525 × state(n) + 1013904223) mod 2^32
noise(n)   = state(n) / 2^32   ∈ [0, 1)
```

The same generator runs independently in Python (for future use) and as inlined JS constants inside the init script.

**Why LCG and not `Math.random()`:**

`Math.random()` is non-deterministic across calls and sessions. Real browsers produce the same canvas fingerprint on every call on the same hardware. Phantomime's LCG produces the same noise sequence for the same `profile_dir`, making the fingerprint stable within and across sessions.

**Seed derivation:**

```python
seed = int(hashlib.md5(Path(profile_dir).name.encode()).hexdigest()[:8], 16)
```

The MD5 of the directory *name* (not full path) is used so that moving the profiles directory does not change fingerprints. Only the worker identifier matters.

**Shadow canvas technique:**

Rather than patching `HTMLCanvasElement.prototype.getContext` (detectable via prototype chain inspection), Phantomime:

1. Creates an off-screen `OffscreenCanvas` at init time
2. Draws LCG noise onto it
3. Patches `toDataURL`, `getImageData`, and `toBlob` to delegate to this shadow canvas
4. The original canvas is never mutated

This means the noise is consistent across all three export methods and across repeated calls — exactly as a real browser would behave.

---

## Behavioral Layer

### Mouse movement

```
target selector
    │
    ├── page.query_selector(selector)
    ├── element.bounding_box()          → target center (tx, ty)
    ├── current position                → (cx, cy)
    │
    ├── distance = sqrt((tx-cx)² + (ty-cy)²)
    ├── Fitts' Law: duration ∝ log2(distance / target_size + 1)
    │
    ├── overshoot (30% probability):
    │       overshoot_x = tx + random.gauss(0, 8)
    │       overshoot_y = ty + random.gauss(0, 8)
    │       move to overshoot point first, then correct
    │
    ├── Cubic Bézier: P0=current, P3=target
    │       P1, P2 = random control points within ±30% of midpoint
    │
    ├── sample N points along Bézier (N ∝ distance)
    └── dispatch mouse_move events with velocity-modulated delays
```

### Keyboard input

```
type_text(selector, text)
    │
    ├── move_to_selector(selector)    (if move_first=True)
    ├── triple-click to select all    (if clear_first=True)
    ├── for each character in text:
    │       ├── typo check (typo_rate):
    │       │       pick QWERTY neighbor key
    │       │       type wrong key
    │       │       backspace
    │       ├── frustration check (frustration_rate):
    │       │       extra backspace (over-delete)
    │       │       retype deleted char
    │       ├── keydown + keypress + input + keyup events
    │       └── delay: random.lognormal(mean, sigma) ms
    └── blur event on element
```

### Scroll

```
scroll_down(pixels)
    │
    ├── divide pixels into N steps (easing curve)
    ├── for each step:
    │       ├── window.scrollBy(0, step_size)
    │       ├── dispatch mousemove at random position
    │       └── asyncio.sleep(variable delay)
    └── final position = start + pixels (approximately)
```

---

## TLS Synchronization Layer

```
Playwright BrowserContext
    cookies ──sync_cookies_to_session()──► curl-cffi AsyncSession
    cookies ◄─sync_cookies_from_session()── curl-cffi AsyncSession

HumanBrowser.fetch(url, ...)
    │
    ├── _session_headers()    → headers dict from active profile
    ├── AsyncSession.request(method, url, headers, ...)
    │       TLS: Chrome 124 ClientHello (impersonated)
    │       Cookies: curl-cffi internal cookie jar
    └── return Response
```

**Proxy application:**

```python
# In launch():
self._session = AsyncSession(
    browser_type=self._resolve_browser_type(),
    proxies={"https": proxy_server, "http": proxy_server},  # if proxy set
)
```

Both Playwright and curl-cffi receive the same proxy, so there is no IP mismatch.

---

## Concurrency Model

### run_swarm

```
run_swarm(task, items, max_concurrent=5)
    │
    ├── sem = asyncio.Semaphore(max_concurrent)
    ├── for i, item in enumerate(items):
    │       create coroutine: _swarm_worker(sem, task, item, profile_dir=f"worker_{i}")
    └── asyncio.gather(*coroutines)

_swarm_worker(sem, task, item, profile_dir)
    async with sem:                          ← blocks if max_concurrent reached
        async with HumanBrowser(profile_dir, **browser_kwargs) as browser:
            return await task(browser, item)
```

All workers share the same event loop. The semaphore ensures at most `max_concurrent` browsers are active simultaneously.

### run_swarm_multiprocess

```
run_swarm_multiprocess(task, items, max_concurrent=10, workers=4)
    │
    ├── split items into `workers` chunks
    ├── multiprocessing.Pool(workers)
    ├── each process: asyncio.run(_sub_swarm(task, chunk, max_concurrent // workers))
    └── collect and flatten results
```

Each OS process runs its own asyncio event loop with a proportional concurrency limit. IPC is handled by `multiprocessing` — results are returned via the pool's result queue.

---

## Data Flow: Full Scraping Session

```
1. HumanBrowser.__init__()
       profile selected, LCG seed computed

2. HumanBrowser.launch()
       Playwright starts, persistent context created
       init script injected into page JS context
       curl-cffi session initialized (same proxy)

3. browser.warmup(4.0)
       idle behavior: micro-movements, scroll pulses, pauses
       builds realistic session age

4. browser.goto("https://target.com/login")
       Playwright navigates
       Chromium sends real HTTP/2 request with Chrome headers
       init script already active — all fingerprint patches in place

5. browser.type_text() + browser.click()
       Bézier mouse movement to element
       log-normal keystroke delays, QWERTY typos
       form submitted

6. browser.wait_for(".dashboard")
       Playwright polls DOM

7. browser.sync_cookies_to_session("https://target.com")
       Playwright cookies → curl-cffi cookie jar

8. browser.fetch("https://target.com/api/data")
       curl-cffi sends request
       TLS: Chrome 124 ClientHello
       Cookies: synced from Playwright session
       Response returned

9. HumanBrowser.close()   (via __aexit__)
       Playwright context closed, profile saved to disk
       curl-cffi session closed
```

---

## Extension Points

### Custom hardware profile

Add a new entry to `_PROFILES` in `browser.py`:

```python
_PROFILES.append({
    "width": 2560, "height": 1440,
    "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "ch_platform": "Windows", "platform_raw": "Win32",
    "webgl_vendor": "Google Inc.",
    "renderer": "ANGLE (NVIDIA, NVIDIA RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "memory": 32, "cores": 16, "dpr": 1.5,
})
```

### Custom init script patch

To add a new fingerprint patch without modifying the core:

```python
class PatchedBrowser(HumanBrowser):
    async def _setup_page(self, page):
        await super()._setup_page(page)
        await page.add_init_script("""
            // Your additional patch here
            Object.defineProperty(navigator, 'connection', {
                get: () => ({ effectiveType: '4g', downlink: 10, rtt: 50 }),
            });
        """)
```

Note: custom patches added after the base init script are NOT covered by `Function.prototype.toString` spoofing. Add `toString` spoofing manually if needed.

### Custom behavioral timing

Override `wait_between_actions` for a different delay distribution:

```python
class SlowerBrowser(HumanBrowser):
    async def wait_between_actions(self) -> None:
        import random
        delay = random.uniform(2.0, 6.0)
        await asyncio.sleep(delay)
```
