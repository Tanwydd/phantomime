# Changelog

All notable changes to Phantomime are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-05-10

Initial public release on PyPI.

### Added
- `HumanBrowser` class with full async context manager support
- Six hardware profiles (Windows/macOS/Linux, covering most common real-world fingerprint combinations)
- Deterministic per-session LCG fingerprint noise for Canvas, WebGL, and AudioContext
- Shadow canvas technique: noise applied to off-screen canvas, original untouched
- WebGL1 and WebGL2 `readPixels` noise
- `AudioContext.getChannelData` float-level noise
- `getBoundingClientRect` sub-pixel noise (Element + Range) for font enumeration resistance
- `performance.now()` ±0.1ms LCG jitter to mask JS wrapper overhead
- `Function.prototype.toString` spoofing for all patched functions
- `Event.isTrusted` patched to `true` for synthetic events
- `navigator.webdriver` removal
- Full `window.chrome` object (`runtime`, `loadTimes`, `csi`, `app`)
- `navigator.plugins` populated with 5 real Chrome PDF viewer entries
- Battery Status API deterministic values per session
- `--headless=new` flag to preserve GPU pipeline in headless mode
- Cubic Bézier mouse trajectories with Fitts' Law velocity modulation
- 30% overshoot probability with correction micro-movement
- Log-normal inter-keystroke delay distribution
- QWERTY-neighbor typo simulation with autocorrection (`typo_rate`)
- Over-deletion frustration errors (`frustration_rate`)
- Inertial scroll with intermediate `mousemove` events
- `idle()` — human-like idle behavior (micro-movements, scroll pulses, random pauses)
- `warmup()` — session warmup before first navigation
- `wait_between_actions()` — 80/20 short/long inter-action pause distribution
- `run_swarm()` — async concurrent browser pool via `asyncio.Semaphore`
- `run_swarm_multiprocess()` — multi-process browser pool via `multiprocessing.Pool`
- TLS HTTP layer via `curl-cffi` (optional dependency)
- `fetch()` — direct HTTP with Chrome 124 TLS fingerprint
- `sync_cookies_to_session()` — Playwright → curl-cffi cookie sync
- `sync_cookies_from_session()` — curl-cffi → Playwright cookie sync
- `sync_cookies()` — bidirectional cookie sync
- `executable_path` parameter to use system Chrome binary
- `proxy` parameter applied to both Playwright and curl-cffi session
- Conditional `curl-cffi` import with warning if absent
- Full API: `goto`, `click`, `type_text`, `scroll_down`, `scroll_up`, `scroll_to_element`, `move_to`, `move_to_selector`, `get_text`, `get_attr`, `is_visible`, `wait_for`, `screenshot`, `evaluate`, `content`, `new_page`
