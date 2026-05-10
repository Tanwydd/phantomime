# Frequently Asked Questions

---

## General

**Does Phantomime work on Windows?**

Yes. All features work on Windows, macOS, and Linux. The only difference is the `executable_path` for system Chrome — on Windows it is typically `C:\Program Files\Google\Chrome\Application\chrome.exe`.

**Does Phantomime support Firefox or Safari?**

No. Phantomime is built specifically around Chromium/Chrome. The fingerprint patches, TLS impersonation, and hardware profiles are all Chrome-specific. Firefox and Safari have fundamentally different fingerprint surfaces and would require a separate implementation.

**Does it work in a Docker container?**

Yes, with some extra setup. Chromium in Docker requires either:

```dockerfile
# Option A — install dependencies
RUN apt-get install -y \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2

# Option B — use the official Playwright image
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy
```

Set `headless=True` — headed mode requires a display server. If you need headed mode in Docker, use `xvfb-run`.

**Does it work in a headless server without GPU?**

Yes. The `--headless=new` flag used internally preserves the GPU pipeline where available, but Chromium falls back to software rendering gracefully. Canvas and WebGL fingerprints will differ from a machine with a real GPU, but they remain consistent within a session.

**Is curl-cffi required?**

No. It is an optional dependency. All Playwright-based functionality works without it. Only `fetch()`, `sync_cookies_to_session()`, `sync_cookies_from_session()`, and `sync_cookies()` require `curl-cffi`. A warning is logged at import time if it is absent.

---

## Fingerprinting

**How is the canvas fingerprint stabilised across calls?**

Phantomime uses a Linear Congruential Generator (LCG) seeded from an MD5 hash of the `profile_dir` name. This produces a fixed noise sequence for the lifetime of the session. `toDataURL()`, `getImageData()`, and `toBlob()` all draw from a pre-rendered shadow canvas, so every call returns the same (noisy) output — exactly as a real browser would on fixed hardware.

**Will two browsers with different `profile_dir` names produce different fingerprints?**

Yes. The LCG seed is derived from the directory name, so `./profiles/worker_01` and `./profiles/worker_02` produce distinct canvas hashes, WebGL outputs, and timing signatures.

**Does Phantomime bypass Cloudflare?**

It depends on the Cloudflare configuration. Phantomime handles JS challenges (the spinning wheel) well — `idle()` with 8–10 seconds gives the challenge time to resolve. Cloudflare Turnstile (the interactive checkbox) requires a CAPTCHA solving service; Phantomime does not include one.

**Does it handle CAPTCHA?**

No. CAPTCHA solving is out of scope. For reCAPTCHA v2/v3 and hCaptcha, integrate a third-party solver (2captcha, CapMonster, etc.) and inject the token via `browser.evaluate()`.

**Why is `headless=False` passed to Playwright internally even when I set `headless=True`?**

Playwright's `headless=True` activates `--headless=old` (pipe mode), which disables the GPU pipeline. This makes WebGL and Canvas outputs trivially different from a real browser. Phantomime passes `headless=False` to Playwright and injects `--headless=new` as a launch argument, preserving full GPU rendering. The browser is still headless — there is no visible window.

---

## Performance

**How many concurrent browsers can I run?**

Each headless Chromium instance uses approximately 300–400 MB of RAM. Divide your available RAM by 400 MB to get a safe ceiling. On a machine with 8 GB free: ~20 workers maximum. In practice, 8–10 is a comfortable operating point with headroom for bursts.

**Is `run_swarm` or `run_swarm_multiprocess` faster?**

`run_swarm` (asyncio) is faster for I/O-bound workloads, which covers virtually all scraping scenarios. `run_swarm_multiprocess` is useful when you have heavy CPU post-processing per item (parsing, NLP, image processing) that would block the event loop. For pure scraping, use `run_swarm`.

**Should I open a new browser per URL or reuse one?**

Reuse. Each browser launch takes 1–2 seconds. For a list of 1000 URLs across 10 workers, that is 10 launches total, not 1000. `run_swarm` handles this automatically — each worker browser stays open for the duration of the swarm.

**When should I use `fetch()` instead of `browser.goto()`?**

Once you have an authenticated session, use `fetch()` for any endpoint that returns data (JSON APIs, paginated results, file downloads). Browser navigation is expensive — it parses HTML, executes JS, renders the page. `fetch()` skips all of that. For a typical authenticated scraping workflow, log in via the browser and then switch to `fetch()` for the data collection phase.

---

## Sessions & Profiles

**Can two workers share the same `profile_dir`?**

No. Concurrent Chromium instances on the same profile directory will corrupt it. Always use a distinct `profile_dir` per worker.

**How do I log in manually and save the session?**

Run once with `headless=False`, complete the login manually, then close the browser. The session is stored in the `profile_dir`. Subsequent runs with `headless=True` and the same `profile_dir` will reuse the saved cookies.

```python
# One-time manual login
async with HumanBrowser(profile_dir="./profiles/my_account", headless=False) as browser:
    await browser.goto("https://example.com/login")
    input("Log in manually, then press Enter...")  # wait for manual login

# All subsequent runs — already logged in
async with HumanBrowser(profile_dir="./profiles/my_account", headless=True) as browser:
    await browser.goto("https://example.com/dashboard")
```

**How long do saved sessions last?**

That depends entirely on the target site's session expiry policy. Phantomime does not manage session refresh — implement your own `ensure_logged_in()` check at the start of each run (see the User Manual).

---

## Proxies

**Does the proxy apply to both Playwright and curl-cffi?**

Yes. When `proxy` is set in the constructor, it is applied to both the Playwright browser context and the `curl-cffi` `AsyncSession`. There is no IP leak between the two layers.

**Should I match `locale` and `timezone` to my proxy?**

Yes, always. A mismatch between the IP geolocation and the browser locale/timezone is a reliable detection signal. If your proxy is in Germany, use `locale="de-DE"` and `timezone="Europe/Berlin"`.

---

## Errors & Troubleshooting

**`TimeoutError` on `wait_for()`**

The selector did not appear within the timeout. Common causes: the page loaded a different version (bot detection), the selector is wrong, or the timeout is too short. Use `browser.screenshot(full_page=True)` in the except block to see what the page actually looks like.

**`RuntimeError: curl-cffi is not installed`**

Install it: `pip install curl-cffi`. If you do not need the TLS HTTP layer, avoid calling `fetch()` and the `sync_cookies_*` methods.

**`RuntimeError: Profile directory is locked`**

Another Chromium process is using the same `profile_dir`. Either a previous run did not shut down cleanly or you have two workers sharing a directory. Kill any lingering `chromium` processes and ensure each worker has a unique `profile_dir`.

**The browser starts but immediately closes**

This usually means Playwright cannot find the Chromium binary. Run `playwright install chromium` and verify with `playwright --version`. If using `executable_path`, check the path is correct and the binary is executable.

**`creepjs` still shows a low trust score**

Check which specific tests are failing in the creepjs output. Common remaining signals on some systems: inconsistent screen resolution DPI, missing `speechSynthesis` voices, or `Intl` locale data that does not match the declared locale. Open an issue with the full creepjs JSON output.
