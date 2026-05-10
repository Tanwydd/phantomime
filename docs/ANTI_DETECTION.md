# Anti-Detection Guide

A practical reference for understanding what Phantomime covers, how to test your sessions, and what to do when a site blocks you anyway.

---

## Table of Contents

- [How Modern Bot Detection Works](#how-modern-bot-detection-works)
- [What Phantomime Covers](#what-phantomime-covers)
- [Testing Your Session](#testing-your-session)
- [Reading Detection Tool Output](#reading-detection-tool-output)
- [Common Failure Scenarios](#common-failure-scenarios)
- [Hardening Checklist](#hardening-checklist)

---

## How Modern Bot Detection Works

Bot detection systems operate across four independent layers. A good system catches bots at multiple layers simultaneously — defeating one is not enough.

### Layer 1 — TLS Fingerprint

The TLS ClientHello is sent before any HTTP data. It contains cipher suites, extensions, and elliptic curves in a specific order that identifies the underlying TLS library. Python's `requests`, `httpx`, and even Playwright's internal fetch all produce recognisable TLS fingerprints that differ from Chrome.

Systems like Akamai Bot Manager and Cloudflare check the JA3/JA4 hash of the ClientHello against a known-browser database before serving any content.

**Phantomime's response:** `curl-cffi` impersonates Chrome 124's TLS stack at the socket level. The ClientHello is byte-for-byte identical to a real Chrome browser.

### Layer 2 — Browser Fingerprint

Once the TLS handshake passes, the page runs JavaScript probes against dozens of browser properties:

- `navigator.webdriver` — the most obvious signal; `true` in unpatched Playwright
- Canvas fingerprint — `toDataURL()` hash differs per hardware
- WebGL vendor/renderer — must match a real GPU
- `window.chrome` — absent in unpatched Playwright
- `navigator.plugins` — empty in headless Chromium
- `AudioContext` fingerprint — hardware-bound in real browsers
- Font enumeration via `getBoundingClientRect`
- `navigator.hardwareConcurrency`, `deviceMemory`
- Screen dimensions and device pixel ratio coherence

**Phantomime's response:** all of the above are patched via `page.add_init_script()` before any page code runs, with deterministic per-session noise and full internal coherence.

### Layer 3 — Behavioral Signals

Even with a perfect static fingerprint, automated sessions are detectable through behavior:

- Mouse trajectories — linear paths, teleportation, machine-precision timing
- Keyboard input — uniform inter-keystroke delays, no typos
- Scroll — instant jumps, no inertia
- Event timing — actions happening too fast after page load
- Idle periods — no micro-movements, no random pauses
- `Event.isTrusted` — `false` for synthetic events in unpatched Playwright

**Phantomime's response:** cubic Bézier mouse trajectories, log-normal keystroke timing, QWERTY typos, inertial scroll, idle behavior simulation, and `Event.isTrusted` patching.

### Layer 4 — Network & IP Reputation

No fingerprint patching helps if the IP is listed in:

- Datacenter IP ranges (AWS, GCP, Azure, DigitalOcean, Hetzner)
- Known proxy/VPN exit nodes
- Tor exit nodes
- IP ranges with a history of abusive traffic

This layer is entirely outside Phantomime's scope. Use residential proxies for sites that actively maintain IP reputation lists.

---

## What Phantomime Covers

| Vector | Layer | Covered | Technique |
|--------|-------|---------|-----------|
| TLS ClientHello (JA3/JA4) | Network | ✅ | curl-cffi Chrome 124 impersonation |
| `navigator.webdriver` | Browser | ✅ | Removed via init script |
| Canvas fingerprint | Browser | ✅ | LCG deterministic noise, shadow canvas |
| WebGL vendor/renderer | Browser | ✅ | Profile-bound strings, WebGL1+2 |
| WebGL `readPixels` | Browser | ✅ | LCG pixel noise |
| AudioContext fingerprint | Browser | ✅ | `getChannelData` float noise |
| Font enumeration | Browser | ✅ | `getBoundingClientRect` sub-pixel noise |
| `window.chrome` | Browser | ✅ | Full object with runtime, loadTimes, csi |
| `navigator.plugins` | Browser | ✅ | 5 real Chrome PDF viewer entries |
| `navigator.webdriver` | Browser | ✅ | Removed |
| `navigator.platform` | Browser | ✅ | Coherent with profile OS |
| `navigator.hardwareConcurrency` | Browser | ✅ | Profile value (4/8 cores) |
| `navigator.deviceMemory` | Browser | ✅ | Profile value (4/8/16 GB) |
| Screen dimensions | Browser | ✅ | Profile resolution + toolbar offset |
| `devicePixelRatio` | Browser | ✅ | Profile DPR (1.0/2.0) |
| Client Hints (`Sec-CH-UA`) | Browser | ✅ | Derived from profile UA |
| `Event.isTrusted` | Browser | ✅ | Patched to `true` for synthetic events |
| `Function.prototype.toString` | Browser | ✅ | Spoofed for all patched functions |
| `performance.now()` jitter | Browser | ✅ | LCG ±0.1ms |
| Battery Status API | Browser | ✅ | Deterministic per-session values |
| Headless GPU pipeline | Browser | ✅ | `--headless=new` flag |
| Mouse trajectory | Behavioral | ✅ | Cubic Bézier + Fitts' Law + overshoot |
| Keystroke timing | Behavioral | ✅ | Log-normal distribution |
| Typo simulation | Behavioral | ✅ | QWERTY-neighbor errors + autocorrect |
| Scroll inertia | Behavioral | ✅ | Easing + intermediate mousemove |
| Idle behavior | Behavioral | ✅ | Micro-movements, scroll pulses, pauses |
| Session warmup | Behavioral | ✅ | Pre-navigation idle cycle |
| IP reputation | Network | ❌ | Use residential proxies |
| CAPTCHA solving | Network | ❌ | Use a third-party solver |
| Cloudflare Turnstile | Network | ❌ | Use a third-party solver |

---

## Testing Your Session

### Quick check — bot.sannysoft.com

The fastest way to verify the most common signals:

```python
import asyncio
from phantomime import HumanBrowser

async def test_sannysoft(profile_dir: str = "./profiles/test"):
    async with HumanBrowser(profile_dir=profile_dir, headless=False) as browser:
        await browser.goto("https://bot.sannysoft.com")
        await browser.idle(duration_s=5.0)
        await browser.screenshot(path="./debug/sannysoft.png", full_page=True)
        print("Screenshot saved to ./debug/sannysoft.png")

asyncio.run(test_sannysoft())
```

All rows should be green. Red rows indicate a failed signal — check the vector name against the coverage table above.

### Deep check — creepjs

creepjs runs a comprehensive fingerprint analysis including consistency checks across multiple APIs:

```python
async def test_creepjs(profile_dir: str = "./profiles/test"):
    async with HumanBrowser(profile_dir=profile_dir, headless=False) as browser:
        await browser.goto("https://abrahamjuliot.github.io/creepjs/")
        await browser.idle(duration_s=10.0)  # creepjs takes time to run all probes
        await browser.screenshot(path="./debug/creepjs.png", full_page=True)

        # Extract the trust score
        score = await browser.get_text(".score-value")
        print(f"Trust score: {score}")

asyncio.run(test_creepjs())
```

A trust score above 80% is solid. Below 60% means a consistency issue — usually locale/timezone mismatch or a WebGL coherence problem.

### TLS check — browserleaks.com/tls

```python
async def test_tls(profile_dir: str = "./profiles/test"):
    async with HumanBrowser(profile_dir=profile_dir, headless=False) as browser:
        # Browser-level TLS (Chromium)
        await browser.goto("https://browserleaks.com/tls")
        await browser.idle(duration_s=3.0)
        await browser.screenshot(path="./debug/tls_browser.png", full_page=True)

        # curl-cffi TLS (should match Chrome 124)
        await browser.sync_cookies_to_session("https://browserleaks.com")
        resp = await browser.fetch("https://browserleaks.com/tls?json")
        print("TLS via curl-cffi:", resp.json().get("ja3_hash"))

asyncio.run(test_tls())
```

The JA3 hash from `fetch()` should match the known Chrome 124 JA3 hash.

### IP leak check

```python
async def test_ip_leak(profile_dir: str = "./profiles/test"):
    async with HumanBrowser(profile_dir=profile_dir, headless=True) as browser:
        # Browser IP
        await browser.goto("https://api.ipify.org?format=json")
        browser_ip = await browser.evaluate("JSON.parse(document.body.innerText).ip")

        # curl-cffi IP (should match if proxy is configured correctly)
        await browser.sync_cookies_to_session("https://api.ipify.org")
        resp = await browser.fetch("https://api.ipify.org?format=json")
        fetch_ip = resp.json()["ip"]

        print(f"Browser IP : {browser_ip}")
        print(f"fetch() IP : {fetch_ip}")

        if browser_ip != fetch_ip:
            print("⚠️  IP MISMATCH — curl-cffi session is leaking your real IP")
        else:
            print("✅  IPs match — no leak")

asyncio.run(test_ip_leak())
```

---

## Reading Detection Tool Output

### bot.sannysoft.com

| Row | What it tests | Expected |
|-----|---------------|----------|
| WebDriver | `navigator.webdriver` | `false` |
| Chrome | `window.chrome` presence | `present` |
| Permissions | `navigator.permissions` | not overridden |
| Plugins Length | `navigator.plugins.length` | `> 0` |
| Languages | `navigator.languages` | non-empty array |
| WebGL Vendor | `WEBGL_debug_renderer_info` | real vendor string |
| WebGL Renderer | `WEBGL_debug_renderer_info` | real renderer string |
| Broken Image | phantom image detection | no broken image |
| User Agent | UA string check | valid Chrome UA |
| User Agent OS | UA vs platform coherence | consistent |

### creepjs

creepjs cross-checks dozens of APIs for internal consistency. The most relevant sections:

**Canvas** — should show a valid fingerprint hash, not `blocked` or `undefined`.

**WebGL** — renderer and vendor should match a known GPU. `SwiftShader` or `llvmpipe` indicates software rendering and will lower the score.

**Fonts** — the detected font set should match the declared OS. A Windows UA with Linux fonts is a consistency failure.

**Lies** — creepjs specifically counts "lie detections" — cases where two APIs give contradictory information. Any lie count above 0 needs investigation.

**Trash** — APIs returning `null`, `undefined`, or empty where a real browser would return a value.

---

## Common Failure Scenarios

### "Your trust score is below 60%"

**Most likely cause:** WebGL renderer is `SwiftShader ANGLE` or `llvmpipe` — software rendering. This happens on machines without a GPU or with GPU passthrough issues in VMs.

**Fix:** Run on a machine with a real GPU. In cloud environments, use an instance type with GPU access (e.g. AWS G4, GCP N1 with GPU). Alternatively, accept the lower score and test whether your specific target blocks on this signal.

### "Cloudflare challenge does not resolve"

Cloudflare's JS challenge needs 5–10 seconds to complete its probes.

```python
await browser.goto("https://target.com")
if await browser.is_visible("#challenge-running"):
    await browser.idle(duration_s=10.0, activity=0.1)
    # Challenge should have resolved by now
    if await browser.is_visible("#challenge-running"):
        raise RuntimeError("Cloudflare challenge did not resolve")
```

If it still does not resolve, the IP is likely flagged. Switch proxy.

### "IP mismatch between browser and fetch()"

The proxy is not being applied to the `curl-cffi` session. Check that `proxy` is set in the `HumanBrowser` constructor — it applies to both layers automatically. If you are managing the session manually, pass the proxy explicitly.

### "Page loads but content is missing / shows an alternative version"

The site is returning a simplified bot-safe response. This often happens when:

- The IP is in a datacenter range
- The session has no cookies or browsing history
- The `Accept-Language` header does not match the locale

**Fix:** use `warmup()`, check locale/timezone coherence, and consider pre-warming the profile with a few real page visits before the scraping session.

### "site works in headed mode but fails in headless"

Some sites specifically detect `--headless=new` via timing differences in rendering. Try:

```python
# Use a real system Chrome binary — it has better headless rendering
HumanBrowser(
    profile_dir="./profiles/test",
    headless=True,
    executable_path="/usr/bin/google-chrome",
)
```

---

## Hardening Checklist

Use this checklist before running production workloads against a high-security target.

- [ ] Verify fingerprint passes bot.sannysoft.com (all green)
- [ ] Verify creepjs trust score > 80%
- [ ] Confirm no IP leak between browser and `fetch()` (run `test_ip_leak()`)
- [ ] `locale` and `timezone` match proxy geolocation
- [ ] `profile_dir` has been pre-warmed with real page visits
- [ ] `warmup()` called before first navigation in each session
- [ ] `wait_between_actions()` used between major page interactions
- [ ] Proxy is residential (not datacenter) for high-security targets
- [ ] Each worker has a unique `profile_dir`
- [ ] Screenshots-on-failure configured for debugging
- [ ] Session validity checked at start of each run
