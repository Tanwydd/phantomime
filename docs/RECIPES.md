# Recipes

Short, focused snippets for specific scenarios. Copy, adapt, ship.

---

## Table of Contents

- [Navigation](#navigation)
- [Authentication](#authentication)
- [Data Extraction](#data-extraction)
- [Iframes](#iframes)
- [File Handling](#file-handling)
- [Request Interception](#request-interception)
- [Cloudflare & Challenges](#cloudflare--challenges)
- [Pagination Patterns](#pagination-patterns)
- [Dynamic Content](#dynamic-content)
- [Screenshots & Diffing](#screenshots--diffing)
- [Cookie Management](#cookie-management)
- [Utilities](#utilities)

---

## Navigation

### Wait for navigation after click

```python
async with browser.page.expect_navigation():
    await browser.click("#submit-btn")
```

### Navigate and extract in one step

```python
async def goto_and_extract(browser: HumanBrowser, url: str, selector: str) -> str:
    await browser.goto(url)
    await browser.wait_for(selector)
    return await browser.get_text(selector)
```

### Open a new tab and switch to it

```python
new_page = await browser.new_page()
await new_page.goto("https://example.com/new-tab")
text = await new_page.locator("h1").text_content()
await new_page.close()
```

### Handle popup windows

```python
async with browser.page.context.expect_page() as popup_info:
    await browser.click("a[target=_blank]")
popup = await popup_info.value
await popup.wait_for_load_state("domcontentloaded")
text = await popup.locator("h1").text_content()
await popup.close()
```

---

## Authentication

### Login with session check

```python
async def login_if_needed(browser: HumanBrowser, email: str, password: str) -> None:
    await browser.goto("https://example.com/dashboard")
    if not await browser.is_visible(".user-menu"):
        await browser.goto("https://example.com/login")
        await browser.type_text("#email", email)
        await browser.type_text("#password", password)
        await browser.click("#login-btn")
        await browser.wait_for(".user-menu", timeout=15.0)
```

### Extract CSRF token before POST

```python
await browser.goto("https://example.com/form")
csrf = await browser.get_attr('meta[name="csrf-token"]', "content")

response = await browser.fetch(
    "https://example.com/api/submit",
    method="POST",
    headers={"X-CSRF-Token": csrf},
    json={"field": "value"},
)
```

### Handle Two-Factor Authentication (manual)

```python
await browser.goto("https://example.com/login")
await browser.type_text("#email", EMAIL)
await browser.type_text("#password", PASSWORD)
await browser.click("#login-btn")

# Wait for 2FA page
if await browser.is_visible("#totp-input"):
    code = input("Enter your 2FA code: ")
    await browser.type_text("#totp-input", code)
    await browser.click("#verify-btn")

await browser.wait_for(".dashboard")
```

### Bearer token extraction

```python
# Intercept API responses to capture auth token
token_holder = {}

async def capture_token(response):
    if "/api/auth/token" in response.url:
        data = await response.json()
        token_holder["token"] = data.get("access_token")

browser.page.on("response", capture_token)
await browser.goto("https://example.com/login")
await browser.type_text("#email", EMAIL)
await browser.type_text("#password", PASSWORD)
await browser.click("#submit")
await browser.wait_for(".dashboard")

token = token_holder.get("token")
# Use token directly in fetch() headers
response = await browser.fetch(
    "https://example.com/api/data",
    headers={"Authorization": f"Bearer {token}"},
)
```

---

## Data Extraction

### Extract table as list of dicts

```python
data = await browser.evaluate("""
    const headers = Array.from(document.querySelectorAll('table thead th'))
        .map(th => th.textContent.trim());
    return Array.from(document.querySelectorAll('table tbody tr')).map(row => {
        const cells = Array.from(row.querySelectorAll('td'))
            .map(td => td.textContent.trim());
        return Object.fromEntries(headers.map((h, i) => [h, cells[i]]));
    });
""")
```

### Extract JSON-LD structured data

```python
json_ld = await browser.evaluate("""
    const el = document.querySelector('script[type="application/ld+json"]');
    return el ? JSON.parse(el.textContent) : null;
""")
```

### Extract all meta tags

```python
meta = await browser.evaluate("""
    Object.fromEntries(
        Array.from(document.querySelectorAll('meta[name], meta[property]'))
            .map(m => [m.getAttribute('name') || m.getAttribute('property'), m.content])
    )
""")
```

### Extract data from a lazy-loaded image

```python
await browser.scroll_to_element("img.lazy[data-src]")
await browser.idle(duration_s=1.0)  # wait for lazy load
src = await browser.get_attr("img.lazy", "src")
```

### Extract text from shadow DOM

```python
text = await browser.evaluate("""
    document.querySelector('my-component').shadowRoot
        .querySelector('.inner-text').textContent.trim()
""")
```

---

## Iframes

### Switch context to iframe

```python
# Get the iframe element
frame = browser.page.frame_locator("iframe#target-frame")

# Interact inside it
await frame.locator("#inner-button").click()
text = await frame.locator(".inner-content").text_content()
```

### Extract data from all iframes

```python
results = []
for frame in browser.page.frames:
    if frame.url and "target.com" in frame.url:
        content = await frame.evaluate("document.body.innerText")
        results.append({"url": frame.url, "content": content})
```

### Wait for iframe to load

```python
await browser.goto("https://example.com/page-with-iframe")
frame = browser.page.frame_locator("iframe#data-frame")
await frame.locator(".frame-content").wait_for(timeout=10_000)
data = await frame.locator(".frame-content").text_content()
```

---

## File Handling

### Download a file

```python
async with browser.page.expect_download() as download_info:
    await browser.click("#download-btn")
download = await download_info.value
await download.save_as("./downloads/report.csv")
```

### Upload a file

```python
await browser.page.locator("input[type=file]").set_input_files("./data/document.pdf")
await browser.click("#upload-btn")
await browser.wait_for(".upload-complete", timeout=60.0)
```

### Download via fetch() with authentication

```python
await browser.sync_cookies_to_session("https://example.com")
resp = await browser.fetch("https://example.com/export/report.csv")
with open("./downloads/report.csv", "wb") as f:
    f.write(resp.content)
```

---

## Request Interception

### Log all API calls

```python
def log_request(request):
    if "/api/" in request.url:
        print(f"{request.method} {request.url}")

browser.page.on("request", log_request)
await browser.goto("https://example.com/dashboard")
```

### Intercept and capture API responses

```python
captured = []

async def capture_response(response):
    if "/api/products" in response.url and response.status == 200:
        captured.append(await response.json())

browser.page.on("response", capture_response)
await browser.goto("https://example.com/products")
await browser.idle(duration_s=3.0)  # wait for all XHR to complete
print(f"Captured {len(captured)} API responses")
```

### Block images and fonts to speed up loading

```python
async def block_resources(route):
    if route.request.resource_type in ("image", "font", "media"):
        await route.abort()
    else:
        await route.continue_()

await browser.page.route("**/*", block_resources)
await browser.goto("https://example.com/heavy-page")
```

---

## Cloudflare & Challenges

### Wait out a JS challenge

```python
async def goto_through_cloudflare(browser: HumanBrowser, url: str, timeout: float = 15.0) -> bool:
    await browser.goto(url)
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if not await browser.is_visible("#challenge-running"):
            return True
        await browser.idle(duration_s=2.0, activity=0.05)
    return False
```

### Detect and handle different block pages

```python
async def check_blocked(browser: HumanBrowser) -> str | None:
    signals = {
        "#challenge-running":       "cloudflare_challenge",
        ".cf-error-details":        "cloudflare_error",
        "#px-captcha":              "perimeterx",
        ".datadome-captcha":        "datadome",
        '[class*="captcha"]':       "generic_captcha",
    }
    for selector, name in signals.items():
        if await browser.is_visible(selector, timeout=1.0):
            return name
    return None
```

---

## Pagination Patterns

### Click-based pagination

```python
async def paginate_click(browser: HumanBrowser, url: str) -> list[dict]:
    await browser.goto(url)
    all_items = []
    while True:
        await browser.wait_for(".items-list")
        items = await browser.evaluate("""
            Array.from(document.querySelectorAll('.item')).map(el => ({
                title: el.querySelector('h3')?.textContent.trim(),
                link:  el.querySelector('a')?.href,
            }))
        """)
        all_items.extend(items)
        if not await browser.is_visible(".pagination .next:not([disabled])"):
            break
        await browser.click(".pagination .next")
        await browser.wait_between_actions()
    return all_items
```

### URL-based pagination

```python
async def paginate_url(browser: HumanBrowser, base_url: str, param: str = "page") -> list[dict]:
    all_items = []
    page = 1
    while True:
        await browser.goto(f"{base_url}?{param}={page}")
        items = await browser.evaluate("/* extraction JS */")
        if not items:
            break
        all_items.extend(items)
        page += 1
        await browser.wait_between_actions()
    return all_items
```

### Infinite scroll with content deduplication

```python
async def paginate_infinite_scroll(browser: HumanBrowser, url: str) -> list[dict]:
    await browser.goto(url)
    seen_ids = set()
    all_items = []
    max_rounds = 30

    for _ in range(max_rounds):
        items = await browser.evaluate("""
            Array.from(document.querySelectorAll('[data-id]')).map(el => ({
                id:    el.dataset.id,
                title: el.querySelector('.title')?.textContent.trim(),
            }))
        """)
        new_items = [i for i in items if i["id"] not in seen_ids]
        if not new_items:
            break
        for item in new_items:
            seen_ids.add(item["id"])
        all_items.extend(new_items)
        await browser.scroll_down(pixels=1000)
        await browser.idle(duration_s=1.5, activity=0.1)

    return all_items
```

---

## Dynamic Content

### Wait for a specific text to appear

```python
await browser.page.wait_for_function(
    "document.querySelector('.status')?.textContent.includes('Complete')",
    timeout=30_000,
)
```

### Wait for an element count to reach N

```python
await browser.page.wait_for_function(
    "document.querySelectorAll('.result-item').length >= 20",
    timeout=15_000,
)
```

### Trigger lazy-loaded sections

```python
# Scroll through the page in steps to trigger all lazy observers
page_height = await browser.evaluate("document.body.scrollHeight")
step = 600
position = 0
while position < page_height:
    await browser.evaluate(f"window.scrollTo(0, {position})")
    await asyncio.sleep(0.3)
    position += step
    page_height = await browser.evaluate("document.body.scrollHeight")
```

### Select from a custom dropdown (non-native)

```python
# Click the dropdown trigger
await browser.click(".custom-select .trigger")
await browser.wait_for(".custom-select .options")

# Click the desired option by text
await browser.page.locator(".custom-select .option", has_text="Option Label").click()
```

---

## Screenshots & Diffing

### Screenshot a specific element

```python
element = browser.page.locator(".chart-container")
png_bytes = await element.screenshot()
with open("./debug/chart.png", "wb") as f:
    f.write(png_bytes)
```

### Visual diff between two screenshots

```python
from PIL import Image, ImageChops
import io

async def visual_diff(before: bytes, after: bytes, output_path: str) -> float:
    img_before = Image.open(io.BytesIO(before)).convert("RGB")
    img_after  = Image.open(io.BytesIO(after)).convert("RGB")
    diff = ImageChops.difference(img_before, img_after)
    pixels = list(diff.getdata())
    changed = sum(1 for p in pixels if max(p) > 10)
    pct = changed / len(pixels) * 100
    if pct > 0.5:
        diff.save(output_path)
    return pct
```

---

## Cookie Management

### Export cookies to a JSON file

```python
cookies = await browser.page.context.cookies()
import json
with open("./profiles/cookies_backup.json", "w") as f:
    json.dump(cookies, f, indent=2)
```

### Import cookies from a JSON file

```python
import json
with open("./profiles/cookies_backup.json") as f:
    cookies = json.load(f)
await browser.page.context.add_cookies(cookies)
```

### Clear cookies for a specific domain

```python
cookies = await browser.page.context.cookies()
keep = [c for c in cookies if "example.com" not in c["domain"]]
await browser.page.context.clear_cookies()
await browser.page.context.add_cookies(keep)
```

---

## Utilities

### Retry wrapper with exponential backoff

```python
import asyncio
import functools

def retry(max_attempts: int = 3, base_delay: float = 1.0):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    await asyncio.sleep(base_delay * (2 ** attempt))
        return wrapper
    return decorator
```

### Throttle requests to a target rate

```python
import asyncio
import time

class RateLimiter:
    def __init__(self, calls_per_second: float):
        self.interval = 1.0 / calls_per_second
        self._last = 0.0

    async def wait(self):
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self.interval:
            await asyncio.sleep(self.interval - elapsed)
        self._last = time.monotonic()

limiter = RateLimiter(calls_per_second=2.0)

async def fetch_throttled(browser: HumanBrowser, url: str) -> dict:
    await limiter.wait()
    resp = await browser.fetch(url)
    return resp.json()
```

### Random human-like delay between tasks

```python
import random
import asyncio

async def human_delay(min_s: float = 1.0, max_s: float = 4.0) -> None:
    """Exponentially distributed delay, biased towards lower values."""
    delay = min_s + random.expovariate(1.5) * (max_s - min_s)
    delay = min(delay, max_s)
    await asyncio.sleep(delay)
```

### Save results incrementally (crash-safe)

```python
import json
import os

def append_result(path: str, result: dict) -> None:
    """Append one result to a JSONL file. Safe to call on crash-restart."""
    with open(path, "a") as f:
        f.write(json.dumps(result) + "\n")

def load_results(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]

# Usage
results_path = "./data/results.jsonl"
done_urls = {r["url"] for r in load_results(results_path)}
remaining = [item for item in all_items if item["url"] not in done_urls]

async with HumanBrowser(profile_dir="./profiles/run") as browser:
    for item in remaining:
        result = await scrape(browser, item)
        append_result(results_path, result)
```
