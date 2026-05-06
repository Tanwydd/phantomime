"""
human_browser.py  v9  "Ghost Protocol + TLS Sync"

==================================

Navegador humanizado basado en Playwright con anti-fingerprinting completo
y capa HTTP directa con TLS fingerprint de Chrome real via curl-cffi.


FINGERPRINT

  - Canvas noise determinista por sesion via LCG (sin mutar canvas original)
  - toDataURL + getImageData + toBlob parcheados con canvas temporal
  - screen.width/height + availWidth/Height + colorDepth/pixelDepth
  - window.devicePixelRatio + device_scale_factor sincronizados por perfil
  - window.outerWidth/Height coherentes con perfil
  - WebGL vendor/renderer (WebGL1 + WebGL2)
  - WebGL readPixels noise: imperfecciones fisicas del rasterizador
  - AudioContext noise minimo en getChannelData
  - getBoundingClientRect noise (Element + Range): evita font fingerprinting
  - Function.prototype.toString spoofing: funciones parcheadas parecen nativas
  - navigator.plugins poblado (5 PDF viewers de Chrome real)
  - navigator.languages derivado del locale
  - navigator.webdriver = undefined
  - navigator.platform coherente con UA por perfil
  - navigator.vendor = "Google Inc."
  - navigator.maxTouchPoints = 0 (escritorio)
  - deviceMemory y hardwareConcurrency por perfil
  - window.chrome con runtime, loadTimes, csi, app
  - Client Hints: sec-ch-ua, sec-ch-ua-mobile, sec-ch-ua-platform coherentes con UA
  - Accept-Language derivado del locale
  - Sec-Fetch-* gestionados automaticamente por Chromium
  - Semilla de fingerprint via MD5 del nombre de directorio
  - performance.now() con jitter LCG +/-0.1ms: enmascara overhead de wrappers JS
  - Event.isTrusted parcheado: eventos sinteticos se presentan como de usuario
  - Font enumeration: document.fonts.check + measureText coherentes con el SO del perfil
  - Battery Status API: nivel y estado de carga realistas y deterministas por sesion


TLS / HTTP DIRECTO (curl-cffi)

  - Capa fetch() con TLS fingerprint de Chrome 124 via curl-cffi
  - Sesion persistente reutilizable (AsyncSession)
  - Sincronizacion bidireccional de cookies entre Playwright y curl-cffi:
      * sync_cookies_to_session()  : Playwright -> curl-cffi
      * sync_cookies_from_session(): curl-cffi  -> Playwright
      * sync_cookies()             : bidireccional (union sin duplicados)
  - Headers coherentes con el perfil del navegador en cada request
  - Compatible con Windows y Linux sin dependencias nativas adicionales


MOVIMIENTO DE RATON

  - Trayectoria: Bezier cubica con puntos de control aleatorios
  - Velocidad: sin((t-0.5)*pi)
  - Overshooting explicito: 30% probabilidad de pasarse y corregir
  - Micro-temblor gaussiano en el tramo final (>85%)
  - Jitter gaussiano por punto de la curva (rompe cadencia periodica del event loop)
  - Jitter en punto de destino
  - Scroll automatico si el elemento no tiene bounding box visible
  - micro_tremor(): temblor de mano de 1-2px sobre posicion actual
  - pre_drift_to(): deriva sutilmente hacia el objetivo antes de la accion real


ESCRITURA

  - Typos por mapa de vecinos QWERTY con autocorreccion
  - Errores de frustracion: borrar mas de la cuenta (~1%)
  - Delays log-normal con pausas de distraccion espontaneas (~4%)
  - Blur del campo anterior antes de enfocar uno nuevo


COMPORTAMIENTO

  - Scroll con inercia (aceleracion progresiva)
  - Idle behavior: movimientos, scrolls, hovering y micro_tremor aleatorios
  - Warmup de sesion
  - wait_between_actions() con distribucion 80/20
  - 6 perfiles de hardware coherentes (Windows/Mac/Linux)
  - Jitter de red simulado via intercepcion de peticiones (enable_network_jitter)
  - Seleccion de perfil coherente con el SO del host (os_aware_profile)
  - Service Workers desactivables con disable_service_workers=True
  - Intercepcion de jitter a nivel de contexto (cubre Service Workers)
  - warm_history(): construye historial de navegacion previo al objetivo
  - executable_path: permite usar Chrome instalado en el sistema (TLS real)


METODOS DISPONIBLES

  Ciclo de vida : launch, close, new_page
  Navegacion    : goto, get_url, get_title, wait_for_url, go_back, go_forward
  Interaccion   : click, type_text, select_option, press_key, hover, focus
  Raton         : move_to, move_to_selector, micro_tremor, pre_drift_to
  Scroll        : scroll_down, scroll_up, scroll_to_element
  HTTP directo  : fetch, sync_cookies_to_session, sync_cookies_from_session, sync_cookies
  Extraccion    : get_text, get_all_text, get_attribute, is_visible, evaluate
  Utilidades    : screenshot, wait_for, wait_between_actions, idle, warmup,
                  enable_network_jitter, warm_history


Requisitos:

    pip install playwright numpy curl-cffi
    playwright install chromium   # o usar executable_path con Chrome del sistema

"""

import asyncio
import hashlib
import logging
import math
import platform as _sys_platform
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from playwright.async_api import async_playwright, BrowserContext, Page

try:
    from curl_cffi.requests import AsyncSession, BrowserType
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _CURL_CFFI_AVAILABLE = False

__version__ = "9.0.1"


def _resolve_browser_type(ua: str) -> "BrowserType":
    """
    Deriva el BrowserType de curl-cffi a partir del User-Agent del perfil.

    Evita la discrepancia mortal entre la version de Chrome declarada en el UA
    y el TLS fingerprint usado por curl-cffi. Si curl-cffi aun no tiene soporte
    para la version exacta, cae al impersonate mas cercano disponible hacia atras,
    logeando un aviso. Nunca usa una version MAS NUEVA que la del UA (eso seria
    peor que usar una ligeramente antigua).

    Orden de busqueda: version exacta → versiones anteriores → chrome124 como minimo.
    """
    import re
    m = re.search(r"Chrome/(\d+)", ua)
    if not m:
        return BrowserType.chrome124

    version = int(m.group(1))

    # Versiones soportadas en curl-cffi ordenadas de mayor a menor.
    # Ampliar esta lista cuando curl-cffi añada versiones nuevas.
    _SUPPORTED = [
        (131, "chrome131"),
        (130, "chrome130"),
        (129, "chrome129"),
        (128, "chrome128"),
        (127, "chrome127"),
        (126, "chrome126"),
        (124, "chrome124"),
        (120, "chrome120"),
        (116, "chrome116"),
        (110, "chrome110"),
        (107, "chrome107"),
        (104, "chrome104"),
        (101, "chrome101"),
        (100, "chrome100"),
        (99,  "chrome99"),
    ]

    for supported_ver, attr_name in _SUPPORTED:
        if version >= supported_ver:
            bt = getattr(BrowserType, attr_name, None)
            if bt is not None:
                if supported_ver != version:
                    _log.warning(
                        "curl-cffi: Chrome %d no soportado aun, usando TLS de Chrome %d. "
                        "Actualiza curl-cffi cuando este disponible.",
                        version, supported_ver,
                    )
                return bt

    _log.warning(
        "curl-cffi: Chrome %d sin mapeo conocido, usando chrome124 como fallback.",
        version,
    )
    return BrowserType.chrome124

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Perfiles de hardware
# ---------------------------------------------------------------------------

_PROFILES = [
    {
        "width": 1920, "height": 1080,
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "ch_platform": "Windows", "platform_raw": "Win32",
        "webgl_vendor": "Google Inc.",
        "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "memory": 8, "cores": 8, "dpr": 1.0,
    },
    {
        "width": 1440, "height": 900,
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "ch_platform": "macOS", "platform_raw": "MacIntel",
        "webgl_vendor": "Google Inc.",
        "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)",
        "memory": 16, "cores": 8, "dpr": 2.0,
    },
    {
        "width": 1366, "height": 768,
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "ch_ua": '"Chromium";v="123", "Google Chrome";v="123", "Not-A.Brand";v="99"',
        "ch_platform": "Windows", "platform_raw": "Win32",
        "webgl_vendor": "Google Inc.",
        "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "memory": 4, "cores": 4, "dpr": 1.0,
    },
    {
        "width": 1280, "height": 800,
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "ch_platform": "Linux", "platform_raw": "Linux x86_64",
        "webgl_vendor": "Google Inc.",
        "renderer": "ANGLE (AMD, AMD Radeon RX 580 Series, OpenGL 4.6)",
        "memory": 8, "cores": 6, "dpr": 1.0,
    },
    {
        "width": 1680, "height": 1050,
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "ch_platform": "Windows", "platform_raw": "Win32",
        "webgl_vendor": "Google Inc.",
        "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "memory": 16, "cores": 12, "dpr": 1.0,
    },
    {
        "width": 2560, "height": 1440,
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "ch_platform": "macOS", "platform_raw": "MacIntel",
        "webgl_vendor": "Google Inc.",
        "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M2 Pro, Unspecified Version)",
        "memory": 32, "cores": 12, "dpr": 2.0,
    },
]

_OS_PROFILE_INDICES: Dict[str, List[int]] = {
    "Windows": [0, 2, 4],
    "Darwin":  [1, 5],
    "Linux":   [3],
}

_FONTS_BY_OS: Dict[str, List[str]] = {
    "Windows": [
        "Arial", "Arial Black", "Arial Narrow", "Bahnschrift", "Calibri",
        "Calibri Light", "Cambria", "Cambria Math", "Candara", "Comic Sans MS",
        "Consolas", "Constantia", "Corbel", "Courier New", "Franklin Gothic Medium",
        "Gabriola", "Georgia", "Impact", "Ink Free", "Lucida Console",
        "Lucida Sans Unicode", "Microsoft Sans Serif", "Palatino Linotype",
        "Segoe Print", "Segoe Script", "Segoe UI", "Segoe UI Emoji",
        "Segoe UI Symbol", "Tahoma", "Times New Roman", "Trebuchet MS",
        "Verdana", "Webdings", "Wingdings", "Century Gothic", "Gill Sans MT",
        "Century", "Book Antiqua", "Bookman Old Style",
    ],
    "Darwin": [
        "American Typewriter", "Andale Mono", "Arial", "Arial Black",
        "Arial Narrow", "Arial Rounded MT Bold", "Arial Unicode MS",
        "Avenir", "Avenir Next", "Baskerville", "Big Caslon", "Charter",
        "Cochin", "Comic Sans MS", "Copperplate", "Courier", "Courier New",
        "DIN Alternate", "DIN Condensed", "Didot", "Futura", "Geneva",
        "Georgia", "Gill Sans", "Helvetica", "Helvetica Neue", "Hoefler Text",
        "Impact", "Lucida Grande", "Menlo", "Monaco", "Optima", "Palatino",
        "Rockwell", "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana",
        "Zapf Dingbats", "Zapfino",
    ],
    "Linux": [
        "Cantarell", "DejaVu Sans", "DejaVu Sans Mono", "DejaVu Serif",
        "FreeMono", "FreeSans", "FreeSerif", "Liberation Mono",
        "Liberation Sans", "Liberation Serif", "Noto Sans", "Noto Serif",
        "Ubuntu", "Ubuntu Mono", "Arial", "Courier New", "Georgia",
        "Times New Roman", "Verdana", "Droid Sans", "Droid Serif",
    ],
}

_PLATFORM_TO_OS: Dict[str, str] = {
    "Win32":        "Windows",
    "MacIntel":     "Darwin",
    "Linux x86_64": "Linux",
}

_QWERTY: Dict[str, list] = {
    "a": ["q","w","s","z"],         "b": ["v","g","h","n"],
    "c": ["x","d","f","v"],         "d": ["s","e","r","f","c","x"],
    "e": ["w","r","d","s"],         "f": ["d","r","t","g","v","c"],
    "g": ["f","t","y","h","b","v"], "h": ["g","y","u","j","n","b"],
    "i": ["u","o","k","j"],         "j": ["h","u","i","k","n","m"],
    "k": ["j","i","o","l","m"],     "l": ["k","o","p"],
    "m": ["n","j","k"],             "n": ["b","h","j","m"],
    "o": ["i","p","l","k"],         "p": ["o","l"],
    "q": ["w","a"],                 "r": ["e","t","f","d"],
    "s": ["a","w","e","d","x","z"], "t": ["r","y","g","f"],
    "u": ["y","i","j","h"],         "v": ["c","f","g","b"],
    "w": ["q","e","s","a"],         "x": ["z","s","d","c"],
    "y": ["t","u","h","g"],         "z": ["a","s","x"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _locale_to_languages(locale: str) -> Tuple[List[str], str]:
    lang = locale.split("-")[0]
    if locale.startswith("en"):
        langs = [locale, lang] if locale != lang else ["en"]
        accept = f"{locale},en;q=0.9" if locale != lang else "en"
    else:
        langs = [locale, lang, "en-US", "en"]
        accept = f"{locale},{lang};q=0.9,en-US;q=0.8,en;q=0.7"
    return langs, accept


def _build_fp_script(profile: Dict[str, Any], session_seed: str, locale: str) -> str:
    seed_int = int(hashlib.md5(session_seed.encode()).hexdigest()[:8], 16) % (2 ** 31)
    w        = profile["width"]
    h        = profile["height"]
    vendor   = profile["webgl_vendor"].replace('"', '\\"')
    renderer = profile["renderer"].replace('"', '\\"')
    memory   = profile["memory"]
    cores    = profile["cores"]
    platform = profile["platform_raw"].replace('"', '\\"')
    dpr      = profile["dpr"]
    langs, _ = _locale_to_languages(locale)
    langs_js = str(langs).replace("'", '"')

    os_key   = _PLATFORM_TO_OS.get(profile["platform_raw"], "Linux")
    fonts    = _FONTS_BY_OS.get(os_key, _FONTS_BY_OS["Linux"])
    fonts_js = str(fonts).replace("'", '"')

    return f"""
(function() {{
    // ── LCG determinista por sesion ──────────────────────────────────────────
    let _seed = {seed_int};
    const _lcg = () => {{
        _seed = (_seed * 1664525 + 1013904223) % 4294967296;
        return _seed / 4294967296;
    }};

    // ── Registro de funciones parcheadas para toString() spoofing ────────────
    const _patchedFns = new WeakSet();
    const _native = (fn, name) => {{
        try {{ Object.defineProperty(fn, 'name', {{ value: name, configurable: true }}); }} catch(_) {{}}
        _patchedFns.add(fn);
        return fn;
    }};

    // ── performance.now jitter ────────────────────────────────────────────────
    const _origPerfNow = performance.now.bind(performance);
    performance.now = _native(function() {{
        return _origPerfNow() + (_lcg() - 0.5) * 0.2;
    }}, 'now');

    // ── Canvas noise (sin mutar el canvas original) ──────────────────────────
    const _applyNoise = (imgData) => {{
        for (let i = 0; i < imgData.data.length; i += 4) {{
            if (_lcg() < 0.05) imgData.data[i] += (_lcg() > 0.5 ? 1 : -1);
        }}
    }};

    const _origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = _native(function() {{
        const res = _origGetImageData.apply(this, arguments);
        _applyNoise(res);
        return res;
    }}, 'getImageData');

    const _origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = _native(function() {{
        const ctx = this.getContext('2d');
        if (ctx) {{
            const off = document.createElement('canvas');
            off.width = this.width; off.height = this.height;
            const octx = off.getContext('2d');
            octx.drawImage(this, 0, 0);
            const img = _origGetImageData.call(octx, 0, 0, off.width, off.height);
            _applyNoise(img);
            octx.putImageData(img, 0, 0);
            return _origToDataURL.apply(off, arguments);
        }}
        return _origToDataURL.apply(this, arguments);
    }}, 'toDataURL');

    const _origToBlob = HTMLCanvasElement.prototype.toBlob;
    HTMLCanvasElement.prototype.toBlob = _native(function(cb, ...rest) {{
        const ctx = this.getContext('2d');
        if (ctx) {{
            const off = document.createElement('canvas');
            off.width = this.width; off.height = this.height;
            const octx = off.getContext('2d');
            octx.drawImage(this, 0, 0);
            const img = _origGetImageData.call(octx, 0, 0, off.width, off.height);
            _applyNoise(img);
            octx.putImageData(img, 0, 0);
            return _origToBlob.call(off, cb, ...rest);
        }}
        return _origToBlob.call(this, cb, ...rest);
    }}, 'toBlob');

    // ── AudioContext noise ───────────────────────────────────────────────────
    const _origGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = _native(function(ch) {{
        const data = _origGetChannelData.call(this, ch);
        for (let i = 0; i < data.length; i += 100) {{
            data[i] += (_lcg() - 0.5) * 0.00005;
        }}
        return data;
    }}, 'getChannelData');

    // ── WebGL: vendor/renderer + readPixels noise ────────────────────────────
    const _patchWebGL = (Ctx) => {{
        const _origGetParam = Ctx.prototype.getParameter;
        Ctx.prototype.getParameter = _native(function(p) {{
            if (p === 37445) return "{vendor}";
            if (p === 37446) return "{renderer}";
            return _origGetParam.call(this, p);
        }}, 'getParameter');

        const _origReadPixels = Ctx.prototype.readPixels;
        Ctx.prototype.readPixels = _native(function(x, y, w, h, fmt, type, pixels) {{
            _origReadPixels.call(this, x, y, w, h, fmt, type, pixels);
            if (pixels instanceof Uint8Array || pixels instanceof Uint8ClampedArray) {{
                for (let i = 0; i < pixels.length; i += 4) {{
                    if (_lcg() < 0.05) {{
                        pixels[i] = Math.max(0, Math.min(255,
                            pixels[i] + (_lcg() > 0.5 ? 1 : -1)));
                    }}
                }}
            }}
        }}, 'readPixels');
    }};
    _patchWebGL(WebGLRenderingContext);
    if (typeof WebGL2RenderingContext !== 'undefined') _patchWebGL(WebGL2RenderingContext);

    // ── Client Rects noise ───────────────────────────────────────────────────
    const _rectNoise = () => (_lcg() - 0.5) * 0.000002;
    const _noiseRect = (r) => {{
        const n = _rectNoise();
        return DOMRect.fromRect({{
            x: r.x + n, y: r.y + n,
            width: r.width + n, height: r.height + n,
        }});
    }};
    const _origElemBCR = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = _native(function() {{
        return _noiseRect(_origElemBCR.call(this));
    }}, 'getBoundingClientRect');

    const _origRangeBCR = Range.prototype.getBoundingClientRect;
    Range.prototype.getBoundingClientRect = _native(function() {{
        return _noiseRect(_origRangeBCR.call(this));
    }}, 'getBoundingClientRect');

    // ── screen / window ──────────────────────────────────────────────────────
    Object.defineProperty(screen, 'width',        {{ get: () => {w} }});
    Object.defineProperty(screen, 'height',       {{ get: () => {h} }});
    Object.defineProperty(screen, 'availWidth',   {{ get: () => {w} }});
    Object.defineProperty(screen, 'availHeight',  {{ get: () => {h} }});
    Object.defineProperty(screen, 'colorDepth',   {{ get: () => 24 }});
    Object.defineProperty(screen, 'pixelDepth',   {{ get: () => 24 }});
    Object.defineProperty(window, 'outerWidth',   {{ get: () => {w} }});
    Object.defineProperty(window, 'outerHeight',  {{ get: () => {h} + 70 }});
    Object.defineProperty(window, 'devicePixelRatio', {{ get: () => {dpr} }});

    // ── navigator ────────────────────────────────────────────────────────────
    Object.defineProperty(navigator, 'deviceMemory',        {{ get: () => {memory} }});
    Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {cores}  }});
    Object.defineProperty(navigator, 'vendor',              {{ get: () => "Google Inc." }});
    Object.defineProperty(navigator, 'maxTouchPoints',      {{ get: () => 0 }});
    Object.defineProperty(navigator, 'webdriver',           {{ get: () => undefined }});
    Object.defineProperty(navigator, 'platform',            {{ get: () => "{platform}" }});
    Object.defineProperty(navigator, 'languages',           {{ get: () => {langs_js} }});

    const _pluginData = [
        {{ name: 'PDF Viewer',                filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
        {{ name: 'Chrome PDF Viewer',         filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
        {{ name: 'Chromium PDF Viewer',       filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
        {{ name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
        {{ name: 'WebKit built-in PDF',       filename: 'internal-pdf-viewer', description: 'Portable Document Format' }},
    ];
    Object.defineProperty(navigator, 'plugins', {{
        get: () => {{
            const arr = _pluginData.map(p => Object.assign(Object.create(Plugin.prototype), p));
            Object.setPrototypeOf(arr, PluginArray.prototype);
            return arr;
        }}
    }});

    // ── window.chrome ────────────────────────────────────────────────────────
    if (!window.chrome) {{
        window.chrome = {{
            runtime: {{}},
            loadTimes: function() {{}},
            csi: function() {{}},
            app: {{}},
        }};
    }}

    // ── Event.isTrusted ──────────────────────────────────────────────────────
    try {{
        const _trustedDesc = Object.getOwnPropertyDescriptor(Event.prototype, 'isTrusted');
        if (_trustedDesc && _trustedDesc.get) {{
            Object.defineProperty(Event.prototype, 'isTrusted', {{
                get: _native(function() {{ return true; }}, 'get isTrusted'),
                configurable: true,
            }});
        }}
    }} catch(_) {{}}

    // ── Font enumeration ─────────────────────────────────────────────────────
    const _installedFonts = new Set({fonts_js});

    if (document.fonts && document.fonts.check) {{
        const _origFontsCheck = document.fonts.check.bind(document.fonts);
        document.fonts.check = _native(function(fontSpec, text) {{
            const specStr = String(fontSpec);
            const m = specStr.match(/[\d.]+(?:px|pt|em|rem|%)[\/\s\d.a-z]* (.+)/i);
            const familyPart = m ? m[1] : specStr;
            const families = familyPart.split(',').map(f => f.trim().replace(/^['"]|['"]$/g, ''));
            for (const fam of families) {{
                if (_installedFonts.has(fam)) return true;
            }}
            return _origFontsCheck(fontSpec, text);
        }}, 'check');
    }}

    const _origMeasureText = CanvasRenderingContext2D.prototype.measureText;
    CanvasRenderingContext2D.prototype.measureText = _native(function(text) {{
        const metrics = _origMeasureText.call(this, text);
        const fontStr = (this.font || '').toLowerCase();
        let delta = 0;
        for (const f of _installedFonts) {{
            if (fontStr.includes(f.toLowerCase())) {{
                let h = 0;
                for (let i = 0; i < f.length; i++) h = ((h * 31) + f.charCodeAt(i)) >>> 0;
                delta = ((h % 200) - 100) * 0.001;
                break;
            }}
        }}
        if (delta === 0) return metrics;
        return new Proxy(metrics, {{
            get(t, p) {{
                if (p === 'width') return t.width + delta;
                const v = t[p];
                return typeof v === 'function' ? v.bind(t) : v;
            }}
        }});
    }}, 'measureText');

    // ── Battery Status API ───────────────────────────────────────────────────
    const _battLevel    = +(0.25 + _lcg() * 0.65).toFixed(2);
    const _battCharging = _lcg() > 0.45;
    const _battObj = {{
        level:            _battLevel,
        charging:         _battCharging,
        chargingTime:     _battCharging ? Math.floor(_lcg() * 3600) + 600 : Infinity,
        dischargingTime:  !_battCharging ? Math.floor(_lcg() * 7200) + 1800 : Infinity,
        onchargingchange: null,
        onchargingtimechange: null,
        ondischargingtimechange: null,
        onlevelchange: null,
        addEventListener:    function() {{}},
        removeEventListener: function() {{}},
        dispatchEvent:       function() {{ return true; }},
    }};
    if (navigator.getBattery) {{
        navigator.getBattery = _native(function() {{
            return Promise.resolve(_battObj);
        }}, 'getBattery');
    }}

    // ── Function.prototype.toString spoofing ─────────────────────────────────
    const _origFnToString = Function.prototype.toString;
    Function.prototype.toString = _native(function() {{
        if (_patchedFns.has(this)) {{
            return `function ${{this.name || ''}}() {{ [native code] }}`;
        }}
        return _origFnToString.call(this);
    }}, 'toString');

    // ── Tracking interno de posicion del raton ───────────────────────────────
    window._mouseX = 0; window._mouseY = 0;
    document.addEventListener('mousemove', e => {{
        window._mouseX = e.clientX; window._mouseY = e.clientY;
    }});
}})();
"""


# ---------------------------------------------------------------------------
# HumanBrowser
# ---------------------------------------------------------------------------

class HumanBrowser:
    """
    Navegador humanizado basado en Playwright con anti-fingerprinting completo
    y capa HTTP directa con TLS fingerprint de Chrome real via curl-cffi.

    Parametros
    ----------
    profile_dir              : Directorio de perfil persistente. Su nombre es la semilla del fingerprint.
    headless                 : Modo headless. Usar con xvfb-run en Linux produccion.
    locale                   : Locale del navegador. Afecta navigator.languages y Accept-Language.
    timezone                 : Timezone. Debe coincidir con la IP si se usa proxy.
    proxy                    : Dict de proxy: {"server": "http://host:port", "username": "u", "password": "p"}.
    slow_mo                  : Delay adicional en ms entre acciones Playwright (util para debug).
    fixed_profile            : True = primer perfil siempre. False = perfil aleatorio en cada sesion.
    os_aware_profile         : True = selecciona un perfil coherente con el SO del host.
    disable_service_workers  : True = desactiva Service Workers en Chromium.
    typo_rate                : Probabilidad de typo QWERTY por caracter (recomendado: 0.03-0.06).
    frustration_rate         : Probabilidad de error de frustracion (recomendado: 0.005-0.015).
    executable_path          : Ruta al binario de Chrome del sistema. None = Chromium de Playwright.
                               Ejemplo Linux: "/usr/bin/google-chrome"
                               Ejemplo Win:   "C:/Program Files/Google/Chrome/Application/chrome.exe"
    """

    def __init__(
        self,
        profile_dir: str | Path = "./hb_profile",
        headless: bool = False,
        locale: str = "es-ES",
        timezone: str = "Europe/Madrid",
        proxy: Optional[Dict[str, str]] = None,
        slow_mo: float = 0.0,
        fixed_profile: bool = False,
        os_aware_profile: bool = True,
        disable_service_workers: bool = False,
        typo_rate: float = 0.04,
        frustration_rate: float = 0.01,
        executable_path: Optional[str] = None,
    ):
        self.profile_dir      = Path(profile_dir)
        # headless se gestiona inyectando --headless=new en args, NO via el parametro
        # headless= de Playwright. El modo headless antiguo de Playwright desactiva la
        # GPU y rompe el pipeline Canvas/WebGL, destruyendo el camuflaje de fingerprint.
        # Mantenemos headless=False en Playwright siempre y controlamos el modo real
        # via flag de Chromium, que si preserva el stack grafico completo.
        self._headless        = headless
        self.locale           = locale
        self.timezone         = timezone
        self.slow_mo          = slow_mo
        self.typo_rate        = typo_rate
        self.frustration_rate = frustration_rate
        self._proxy                   = proxy
        self._disable_service_workers = disable_service_workers
        self._executable_path         = executable_path

        if fixed_profile:
            self._profile = _PROFILES[0]
        elif os_aware_profile:
            sys_os = _sys_platform.system()
            idx_list = _OS_PROFILE_INDICES.get(sys_os, list(range(len(_PROFILES))))
            self._profile = _PROFILES[random.choice(idx_list)]
        else:
            self._profile = random.choice(_PROFILES)

        self._viewport = {"width": self._profile["width"], "height": self._profile["height"]}

        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        # curl-cffi session (None si no esta disponible)
        self._session: Optional[Any] = None

        self._mouse_x: float = random.uniform(150, 600)
        self._mouse_y: float = random.uniform(150, 500)
        self._focused_selector: Optional[str] = None

    async def __aenter__(self) -> "HumanBrowser":
        await self.launch()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def launch(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        _, accept_lang = _locale_to_languages(self.locale)
        self._playwright = await async_playwright().start()

        launch_kwargs: Dict[str, Any] = dict(
            user_data_dir=str(self.profile_dir),
            headless=False,   # SIEMPRE False — el modo headless real se inyecta via --headless=new
            slow_mo=self.slow_mo,
            viewport=self._viewport,
            device_scale_factor=self._profile["dpr"],
            user_agent=self._profile["ua"],
            locale=self.locale,
            timezone_id=self.timezone,
            extra_http_headers={
                "sec-ch-ua":                 self._profile["ch_ua"],
                "sec-ch-ua-mobile":          "?0",
                "sec-ch-ua-platform":        f'"{self._profile["ch_platform"]}"',
                "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language":           accept_lang,
                "Accept-Encoding":           "gzip, deflate, br",
                "Upgrade-Insecure-Requests": "1",
            },
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=IsolateOrigins,site-per-process"
                + (",ServiceWorker" if self._disable_service_workers else ""),
                f"--window-size={self._profile['width']},{self._profile['height']}",
                # --headless=new preserva el stack GPU/Canvas/WebGL al completo.
                # El headless antiguo de Playwright (headless=True) lo desactiva,
                # rompiendo el fingerprint de Canvas y WebGL en produccion.
                *(["--headless=new"] if self._headless else []),
            ],
            ignore_default_args=["--enable-automation"],
        )

        if self._executable_path:
            launch_kwargs["executable_path"] = self._executable_path

        if self._proxy:
            launch_kwargs["proxy"] = self._proxy

        self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        self.page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        await self._setup_page(self.page)

        # Inicializar sesion curl-cffi
        if _CURL_CFFI_AVAILABLE:
            # Construir proxy URL para curl-cffi desde el mismo dict de Playwright.
            # Sin esto, fetch() ignora el proxy y fuga la IP real — bug critico.
            cffi_proxies = None
            if self._proxy:
                server = self._proxy.get("server", "")
                username = self._proxy.get("username")
                password = self._proxy.get("password")
                if username and password:
                    # Insertar credenciales en la URL: http://user:pass@host:port
                    scheme, rest = server.split("://", 1)
                    server = f"{scheme}://{username}:{password}@{rest}"
                cffi_proxies = {"http": server, "https": server}

            browser_type = _resolve_browser_type(self._profile["ua"])
            self._session = AsyncSession(
                impersonate=browser_type,
                proxies=cffi_proxies,
            )
            _log.info(
                "curl-cffi disponible: TLS impersonate=%s | proxy=%s",
                browser_type, bool(cffi_proxies),
            )
        else:
            _log.warning(
                "curl-cffi no disponible. Instala con: pip install curl-cffi\n"
                "Sin esta libreria, fetch() usara httpx como fallback sin TLS spoofing."
            )

        _log.info(
            "HumanBrowser lanzado | %sx%s dpr=%.1f locale=%s headless=%s proxy=%s chrome_bin=%s",
            self._profile["width"], self._profile["height"],
            self._profile["dpr"], self.locale,
            "new" if self._headless else "off",
            bool(self._proxy), self._executable_path or "playwright-chromium",
        )

    async def _setup_page(self, page: Page) -> None:
        await page.add_init_script(
            _build_fp_script(self._profile, self.profile_dir.name, self.locale)
        )

    async def new_page(self) -> Page:
        """Abre una nueva pestana con el mismo fingerprint y la establece como activa."""
        page = await self._context.new_page()
        await self._setup_page(page)
        self.page = page
        return page

    async def close(self) -> None:
        try:
            if self._session:
                await self._session.close()
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            _log.warning("Error al cerrar HumanBrowser: %s", exc)
        finally:
            self._session   = None
            self._context   = None
            self.page       = None
            self._playwright = None

    # ------------------------------------------------------------------
    # HTTP directo con TLS fingerprint (curl-cffi)
    # ------------------------------------------------------------------

    def _session_headers(self, mode: str = "navigate") -> Dict[str, str]:
        """
        Headers coherentes con el perfil para requests curl-cffi.

        Parametros
        ----------
        mode : Tipo de request. Determina los headers Sec-Fetch-* correctos.
               "navigate" : carga de pagina completa (goto equivalente)
               "xhr"      : llamada AJAX/fetch() same-origin
               "cors"     : llamada AJAX/fetch() cross-origin
               "no-cors"  : subrecurso sin CORS (imagen, script, etc.)

        Los valores Sec-Fetch-* incorrectos (p.ej. Mode: navigate en una
        llamada XHR) son detectados por sistemas antibot avanzados como
        Akamai porque ningun navegador real los combina asi.
        """
        _, accept_lang = _locale_to_languages(self.locale)

        # Headers base comunes a todos los modos
        base = {
            "User-Agent":       self._profile["ua"],
            "sec-ch-ua":        self._profile["ch_ua"],
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": f'"{self._profile["ch_platform"]}"',
            "Accept-Language":  accept_lang,
            "Accept-Encoding":  "gzip, deflate, br",
        }

        if mode == "navigate":
            base.update({
                "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Site":            "none",
                "Sec-Fetch-Mode":            "navigate",
                "Sec-Fetch-Dest":            "document",
                "Sec-Fetch-User":            "?1",
            })
        elif mode == "xhr":
            base.update({
                "Accept":          "*/*",
                "Sec-Fetch-Site":  "same-origin",
                "Sec-Fetch-Mode":  "cors",
                "Sec-Fetch-Dest":  "empty",
                "X-Requested-With": "XMLHttpRequest",
            })
        elif mode == "cors":
            base.update({
                "Accept":         "*/*",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            })
        elif mode == "no-cors":
            base.update({
                "Accept":         "*/*",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Dest": "empty",
            })

        return base

    async def sync_cookies_to_session(self, url: Optional[str] = None) -> int:
        """
        Copia las cookies de Playwright al jar de curl-cffi.

        Parametros
        ----------
        url : Si se indica, filtra solo las cookies de ese dominio.
              Si es None, copia todas las cookies del contexto.

        Devuelve el numero de cookies sincronizadas.
        """
        if not self._session:
            _log.debug("sync_cookies_to_session: curl-cffi no disponible, omitiendo.")
            return 0

        pw_cookies = await self._context.cookies(urls=[url] if url else [])
        count = 0
        for c in pw_cookies:
            self._session.cookies.set(
                name=c["name"],
                value=c["value"],
                domain=c.get("domain", ""),
                path=c.get("path", "/"),
            )
            count += 1

        _log.debug("sync_cookies_to_session: %d cookies copiadas a curl-cffi", count)
        return count

    async def sync_cookies_from_session(self) -> int:
        """
        Copia las cookies del jar de curl-cffi a Playwright.

        Devuelve el numero de cookies sincronizadas.
        """
        if not self._session:
            _log.debug("sync_cookies_from_session: curl-cffi no disponible, omitiendo.")
            return 0

        pw_cookies = []
        for cookie in self._session.cookies.jar:
            entry: Dict[str, Any] = {
                "name":   cookie.name,
                "value":  cookie.value,
                "domain": cookie.domain or "",
                "path":   cookie.path or "/",
            }
            if cookie.expires is not None:
                entry["expires"] = float(cookie.expires)
            if cookie.secure is not None:
                entry["secure"] = bool(cookie.secure)
            pw_cookies.append(entry)

        if pw_cookies:
            await self._context.add_cookies(pw_cookies)

        _log.debug("sync_cookies_from_session: %d cookies copiadas a Playwright", len(pw_cookies))
        return len(pw_cookies)

    async def sync_cookies(self, url: Optional[str] = None) -> None:
        """
        Sincronizacion bidireccional: union de cookies de ambas capas sin duplicados.

        Primero vuelca curl-cffi -> Playwright, luego Playwright -> curl-cffi.
        El resultado es que ambas capas tienen el superconjunto de todas las cookies.

        Parametros
        ----------
        url : Si se indica, filtra las cookies de Playwright por ese dominio.
        """
        await self.sync_cookies_from_session()
        await self.sync_cookies_to_session(url=url)
        _log.debug("sync_cookies: sincronizacion bidireccional completada")

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        mode: str = "xhr",
        sync_before: bool = True,
        sync_after: bool = True,
        **kwargs,
    ) -> Any:
        """
        Request HTTP directa con TLS fingerprint coherente con el perfil activo.

        Usar cuando no se necesita renderizado JS pero si TLS limpio
        (p.ej. llamadas a APIs, descarga de recursos, scraping simple).

        Parametros
        ----------
        url          : URL de destino.
        method       : Metodo HTTP (GET, POST, PUT, DELETE...).
        mode         : Tipo de request. Controla los headers Sec-Fetch-* enviados:
                         "xhr"      → same-origin AJAX (defecto, el mas comun en bots)
                         "cors"     → cross-origin AJAX
                         "navigate" → carga de pagina completa
                         "no-cors"  → subrecurso sin CORS
                       IMPORTANTE: usar el mode incorrecto es detectado por Akamai
                       y similares. Un XHR con Mode: navigate nunca ocurre en un
                       navegador real.
        sync_before  : Si True, sincroniza cookies Playwright->curl-cffi antes de la request.
        sync_after   : Si True, sincroniza cookies curl-cffi->Playwright despues de la request.
        **kwargs     : Argumentos adicionales para curl-cffi (headers, data, json, params...).

        Nota sobre connection pooling
        -----------------------------
        Playwright y curl-cffi mantienen piscinas TCP independientes. En sitios con
        deteccion avanzada (Akamai, PerimeterX), multiples handshakes TLS simultaneos
        desde la misma IP pueden levantar sospechas. Estrategia recomendada: usar
        fetch() en fases distintas a la navegacion activa de Playwright, nunca en
        paralelo sobre el mismo dominio en el mismo instante.

        Devuelve
        --------
        curl_cffi.requests.Response
        Lanza RuntimeError si curl-cffi no esta instalado.
        """
        if not self._session:
            raise RuntimeError(
                "curl-cffi no esta disponible. Instala con: pip install curl-cffi"
            )

        if sync_before:
            await self.sync_cookies_to_session(url=url)

        # Headers del perfil segun el modo + override del caller (caller tiene prioridad)
        merged_headers = {**self._session_headers(mode=mode), **kwargs.pop("headers", {})}

        response = await self._session.request(
            method,
            url,
            headers=merged_headers,
            **kwargs,
        )

        if sync_after:
            await self.sync_cookies_from_session()

        _log.debug("fetch %s %s [mode=%s] -> %d", method, url, mode, response.status_code)
        return response

    # ------------------------------------------------------------------
    # Navegacion
    # ------------------------------------------------------------------

    async def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        _log.debug("goto: %s", url)
        await self.page.goto(url, wait_until=wait_until)
        self._focused_selector = None
        await self._pause("page_load")

    def get_url(self) -> str:
        return self.page.url

    async def get_title(self) -> str:
        return await self.page.title()

    async def wait_for_url(self, pattern: str, timeout: float = 30.0) -> None:
        await self.page.wait_for_url(pattern, timeout=timeout * 1000)

    async def go_back(self) -> None:
        await self.page.go_back()
        self._focused_selector = None
        await self._pause("page_load")

    async def go_forward(self) -> None:
        await self.page.go_forward()
        self._focused_selector = None
        await self._pause("page_load")

    # ------------------------------------------------------------------
    # Movimiento de raton
    # ------------------------------------------------------------------

    def _bezier_path(self, p0: Tuple[float, float], p3: Tuple[float, float]) -> list:
        dx   = p3[0] - p0[0]
        dy   = p3[1] - p0[1]
        dist = math.hypot(dx, dy)
        if dist < 2:
            return [(p3[0], p3[1], 8.0)]

        deviation = dist * random.uniform(0.15, 0.40)
        angle     = math.atan2(dy, dx)
        perp      = angle + math.pi / 2
        side      = random.choice([-1, 1])

        p1 = (
            p0[0] + dx * 0.25 + math.cos(perp) * deviation * side * random.uniform(0.4, 1.0),
            p0[1] + dy * 0.25 + math.sin(perp) * deviation * side * random.uniform(0.4, 1.0),
        )
        p2 = (
            p0[0] + dx * 0.75 + math.cos(perp) * deviation * side * random.uniform(0.1, 0.5),
            p0[1] + dy * 0.75 + math.sin(perp) * deviation * side * random.uniform(0.1, 0.5),
        )

        steps  = max(14, min(int(dist / 5), 70))
        points = []
        for i in range(steps + 1):
            t     = i / steps
            mt    = 1 - t
            x     = mt**3*p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
            y     = mt**3*p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
            speed = (math.sin((t - 0.5) * math.pi) + 1) / 2
            delay = 10.0 / (speed + 0.12)
            if t > 0.85:
                x     += random.gauss(0, 0.7)
                y     += random.gauss(0, 0.7)
                delay *= random.uniform(1.3, 2.2)
            points.append((x, y, float(np.clip(delay, 4, 90))))
        return points

    async def _execute_move(self, tx: float, ty: float) -> None:
        for px, py, delay_ms in self._bezier_path((self._mouse_x, self._mouse_y), (tx, ty)):
            await self.page.mouse.move(px, py)
            jitter_s = abs(random.gauss(0, delay_ms * 0.08)) / 1000
            await asyncio.sleep(max(0.004, delay_ms / 1000 + jitter_s))
        self._mouse_x, self._mouse_y = tx, ty

    async def move_to(self, x: float, y: float) -> None:
        if random.random() < 0.30:
            await self._execute_move(
                x + random.uniform(-20, 20),
                y + random.uniform(-15, 15),
            )
            await asyncio.sleep(random.uniform(0.08, 0.20))
        await self._execute_move(x, y)

    async def move_to_selector(self, selector: str, page: Optional[Page] = None) -> bool:
        pg = page or self.page
        try:
            element = await pg.wait_for_selector(selector, state="visible")
            if element is None:
                _log.warning("move_to_selector: elemento no encontrado '%s'", selector)
                return False
            box = await element.bounding_box()
            if box is None:
                await element.scroll_into_view_if_needed()
                box = await element.bounding_box()
            if box is None:
                _log.warning("move_to_selector: sin bounding_box tras scroll '%s'", selector)
                return False
            await self.move_to(
                box["x"] + box["width"]  * random.uniform(0.28, 0.72),
                box["y"] + box["height"] * random.uniform(0.28, 0.72),
            )
            return True
        except Exception as exc:
            _log.warning("move_to_selector error '%s': %s", selector, exc)
            return False

    # ------------------------------------------------------------------
    # Interaccion
    # ------------------------------------------------------------------

    async def click(
        self,
        selector: str,
        move_first: bool = True,
        double: bool = False,
        right: bool = False,
    ) -> None:
        _log.debug("click: %s", selector)
        if move_first:
            await self.move_to_selector(selector)
            await self._pause("pre_click")
        btn = "right" if right else "left"
        el  = self.page.locator(selector).first
        await (el.dblclick(button=btn) if double else el.click(button=btn))
        await self._pause("post_click")

    async def hover(self, selector: str) -> None:
        await self.move_to_selector(selector)
        await self._pause("pre_click")

    async def focus(self, selector: str) -> None:
        await self.page.locator(selector).first.focus()
        self._focused_selector = selector

    async def press_key(self, key: str, count: int = 1) -> None:
        for i in range(count):
            await self.page.keyboard.press(key)
            if count > 1 and i < count - 1:
                await asyncio.sleep(random.uniform(0.05, 0.18))

    async def select_option(
        self,
        selector: str,
        value: str,
        by: str = "label",
    ) -> None:
        await self.move_to_selector(selector)
        await self._pause("pre_click")
        el = self.page.locator(selector).first
        if by == "label":
            await el.select_option(label=value)
        elif by == "value":
            await el.select_option(value=value)
        elif by == "index":
            await el.select_option(index=int(value))
        else:
            raise ValueError(f"select_option: by='{by}' no valido. Usa 'label', 'value' o 'index'.")
        await self._pause("post_click")

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------

    async def type_text(
        self,
        selector: str,
        text: str,
        clear_first: bool = True,
        move_first: bool = True,
    ) -> None:
        if self._focused_selector and self._focused_selector != selector:
            try:
                await self.page.locator(self._focused_selector).first.blur()
                await asyncio.sleep(random.uniform(0.05, 0.18))
            except Exception:
                pass

        if move_first:
            await self.move_to_selector(selector)

        if clear_first:
            await self.page.click(selector, click_count=3)
            await asyncio.sleep(random.uniform(0.06, 0.12))
            await self.page.keyboard.press("Control+a")
            await asyncio.sleep(0.04)
            await self.page.keyboard.press("Delete")

        await self.page.click(selector)
        self._focused_selector = selector
        await self._pause("pre_type")

        for char in text:
            if random.random() < self.frustration_rate:
                await self.page.keyboard.type(random.choice("asdfghj"))
                await asyncio.sleep(random.uniform(0.15, 0.35))
                for _ in range(random.randint(1, 3)):
                    await self.page.keyboard.press("Backspace")
                    await asyncio.sleep(random.uniform(0.06, 0.12))
                await asyncio.sleep(random.uniform(0.1, 0.3))

            elif random.random() < self.typo_rate:
                wrong = self._get_typo(char)
                if wrong and wrong != char:
                    await self.page.keyboard.type(wrong)
                    await asyncio.sleep(self._typing_delay() / 1000)
                    await asyncio.sleep(random.uniform(0.08, 0.35))
                    await self.page.keyboard.press("Backspace")
                    await asyncio.sleep(random.uniform(0.05, 0.12))

            await self.page.keyboard.type(char)
            delay_ms = self._typing_delay()
            if random.random() < 0.04:
                delay_ms += random.uniform(400, 1400)
            await asyncio.sleep(delay_ms / 1000)

        await self._pause("post_type")

    def _get_typo(self, char: str) -> Optional[str]:
        neighbors = _QWERTY.get(char.lower())
        if not neighbors:
            return None
        wrong = random.choice(neighbors)
        return wrong.upper() if char.isupper() else wrong

    def _typing_delay(self) -> float:
        return float(np.clip(np.random.lognormal(mean=4.2, sigma=0.5), 28, 400))

    # ------------------------------------------------------------------
    # Scroll con inercia
    # ------------------------------------------------------------------

    async def scroll_down(self, pixels: int = 400) -> None:
        await self._scroll_inertia(pixels, 1)

    async def scroll_up(self, pixels: int = 200) -> None:
        await self._scroll_inertia(pixels, -1)

    async def _scroll_inertia(self, pixels: int, direction: int) -> None:
        step, total = 35, 0
        while total < pixels:
            actual = min(step, pixels - total)
            await self.page.mouse.wheel(0, actual * direction)
            total += actual
            step   = min(int(step * 1.45), 200)
            await asyncio.sleep(random.uniform(0.025, 0.08))
        await self._pause("post_scroll")

    async def scroll_to_element(self, selector: str) -> None:
        el = await self.page.wait_for_selector(selector)
        await el.scroll_into_view_if_needed()
        await self._pause("post_scroll")

    # ------------------------------------------------------------------
    # Idle / warmup
    # ------------------------------------------------------------------

    async def micro_tremor(self, duration_s: float = 1.0, radius_px: float = 1.5) -> None:
        end = time.time() + duration_s
        while time.time() < end:
            nx = self._mouse_x + random.gauss(0, radius_px)
            ny = self._mouse_y + random.gauss(0, radius_px * 0.7)
            try:
                await self.page.mouse.move(nx, ny)
            except Exception:
                break
            await asyncio.sleep(random.uniform(0.04, 0.14))

    async def pre_drift_to(self, selector: str, duration_s: float = 2.0) -> None:
        try:
            element = await self.page.wait_for_selector(selector, state="visible", timeout=3_000)
            if element is None:
                return
            box = await element.bounding_box()
            if box is None:
                return
            tx = box["x"] + box["width"]  * random.uniform(0.3, 0.7)
            ty = box["y"] + box["height"] * random.uniform(0.3, 0.7)
            end = time.time() + duration_s
            while time.time() < end:
                frac = random.uniform(0.05, 0.15)
                nx = self._mouse_x + (tx - self._mouse_x) * frac + random.gauss(0, 1.5)
                ny = self._mouse_y + (ty - self._mouse_y) * frac + random.gauss(0, 1.0)
                await self.page.mouse.move(nx, ny)
                self._mouse_x, self._mouse_y = nx, ny
                await asyncio.sleep(random.uniform(0.15, 0.50))
        except Exception as exc:
            _log.debug("pre_drift_to: ignorado '%s': %s", selector, exc)

    async def idle(self, duration_s: float, activity: float = 0.35) -> None:
        end = time.time() + duration_s
        w   = self._viewport["width"]
        h   = self._viewport["height"]
        while time.time() < end:
            if random.random() < activity:
                action = random.choices(
                    ["move", "scroll_tiny", "hover_area", "micro_tremor", "pause"],
                    weights=[3, 2, 2, 2, 3],
                )[0]
                try:
                    if action == "move":
                        await self.move_to(random.uniform(80, w - 80), random.uniform(80, h - 80))
                    elif action == "scroll_tiny":
                        await self.page.mouse.wheel(0, random.randint(20, 80) * random.choice([-1, 1]))
                        await asyncio.sleep(random.uniform(0.1, 0.35))
                    elif action == "hover_area":
                        bx = random.uniform(100, w - 100)
                        by = random.uniform(100, h - 100)
                        for _ in range(random.randint(2, 5)):
                            await self.move_to(bx + random.uniform(-50, 50), by + random.uniform(-25, 25))
                    elif action == "micro_tremor":
                        await self.micro_tremor(
                            duration_s=random.uniform(0.5, 2.0),
                            radius_px=random.uniform(0.8, 2.0),
                        )
                    else:
                        await asyncio.sleep(random.uniform(0.4, 1.4))
                except Exception as exc:
                    _log.debug("idle: accion '%s' ignorada: %s", action, exc)
                    await asyncio.sleep(0.3)
            else:
                await asyncio.sleep(random.uniform(0.3, 1.2))

    async def warmup(self, duration_s: float = 5.0) -> None:
        await self.idle(duration_s, activity=0.45)

    async def enable_network_jitter(
        self,
        base_ms: float = 30.0,
        jitter_ms: float = 20.0,
    ) -> None:
        async def _jitter_handler(route) -> None:
            raw     = float(np.random.lognormal(mean=math.log(max(1.0, base_ms)), sigma=0.35))
            jitter  = random.uniform(-jitter_ms / 2, jitter_ms / 2)
            delay_s = max(0.0, raw + jitter) / 1000
            if delay_s > 0:
                await asyncio.sleep(delay_s)
            await route.continue_()

        await self._context.route("**/*", _jitter_handler)
        _log.info(
            "Network jitter activado | base=%.0fms jitter=+/-%.0fms (context-level)",
            base_ms, jitter_ms / 2,
        )

    async def warm_history(
        self,
        sites: Optional[List[str]] = None,
        dwell_s: float = 10.0,
    ) -> None:
        if not sites:
            _log.debug("warm_history: lista de sitios vacia, omitiendo.")
            return
        for site in random.sample(sites, len(sites)):
            try:
                _log.debug("warm_history: visitando %s", site)
                await self.goto(site)
                dwell = max(3.0, float(np.random.lognormal(
                    mean=math.log(max(1.0, dwell_s)), sigma=0.4
                )))
                await self.idle(dwell, activity=0.35)
                if random.random() < 0.65:
                    await self.scroll_down(random.randint(150, 500))
                await self.wait_between_actions()
            except Exception as exc:
                _log.warning("warm_history: error en '%s': %s", site, exc)

    # ------------------------------------------------------------------
    # Delays
    # ------------------------------------------------------------------

    async def _pause(self, context: str = "generic") -> None:
        params = {
            "page_load":   (0.5,  0.5),
            "pre_click":   (-0.3, 0.4),
            "post_click":  (-0.2, 0.4),
            "pre_type":    (-0.5, 0.35),
            "post_type":   (-0.1, 0.5),
            "post_scroll": (-1.0, 0.4),
            "generic":     (-0.3, 0.5),
        }
        mu, sigma = params.get(context, (-0.3, 0.5))
        await asyncio.sleep(max(0.05, min(float(np.random.lognormal(mu, sigma)), 8.0)))

    async def wait_between_actions(self, long: bool = False) -> None:
        if long or random.random() > 0.80:
            delay = float(np.random.lognormal(mean=1.8, sigma=0.6))
        else:
            delay = float(np.random.lognormal(mean=0.3, sigma=0.4))
        await asyncio.sleep(max(0.5, min(delay, 45.0)))

    # ------------------------------------------------------------------
    # Extraccion y utilidades
    # ------------------------------------------------------------------

    async def get_text(self, selector: str) -> str:
        el = await self.page.wait_for_selector(selector)
        return (await el.inner_text()).strip()

    async def get_all_text(self, selector: str) -> List[str]:
        elements = await self.page.query_selector_all(selector)
        result = []
        for el in elements:
            text = await el.inner_text()
            result.append(text.strip())
        return result

    async def get_attribute(self, selector: str, attr: str) -> Optional[str]:
        el = await self.page.wait_for_selector(selector)
        return await el.get_attribute(attr)

    async def is_visible(self, selector: str, timeout: float = 5.0) -> bool:
        try:
            await self.page.wait_for_selector(selector, state="visible", timeout=timeout * 1000)
            return True
        except Exception:
            return False

    async def wait_for(self, selector: str, timeout: float = 10.0) -> None:
        await self.page.wait_for_selector(selector, timeout=timeout * 1000)

    async def screenshot(
        self,
        path: Optional[str | Path] = None,
        full_page: bool = False,
    ) -> bytes:
        return await self.page.screenshot(
            path=str(path) if path else None,
            full_page=full_page,
        )

    async def evaluate(self, expression: str) -> Any:
        return await self.page.evaluate(expression)


# ---------------------------------------------------------------------------
# Utilidades de concurrencia para enjambres de HumanBrowser
# ---------------------------------------------------------------------------
#
# ADVERTENCIA CRITICA: HumanBrowser esta construido sobre asyncio (corutinas).
# Mezclar threading.Thread con asyncio produce errores del tipo:
#   - "Event loop is closed"
#   - "coroutine was never awaited"
#   - deadlocks silenciosos
#
# Patrones correctos:
#
#   A) ASYNCIO PURO (recomendado para <20 instancias en el mismo proceso)
#      asyncio.gather() + asyncio.Semaphore para limitar instancias simultaneas.
#      Un solo hilo del SO, multiples navegadores concurrentes via event loop.
#      Ver: run_swarm()
#
#   B) MULTIPROCESSING (recomendado para enjambres grandes o aislamiento total)
#      Cada proceso tiene su propio event loop, su propio GIL y su propia memoria.
#      Ideal para BotFarm donde cada worker es un proceso independiente del SO.
#      Ver: run_swarm_multiprocess()
#
# ---------------------------------------------------------------------------


async def run_swarm(
    task: Any,
    items: List[Any],
    max_concurrent: int = 5,
    browser_kwargs: Optional[Dict[str, Any]] = None,
    profile_base_dir: str = "./hb_profiles",
) -> List[Any]:
    """
    Ejecuta una tarea asyncrona sobre multiples items con un enjambre de
    instancias HumanBrowser concurrentes dentro del mismo proceso asyncio.

    Cada item lanza su propia instancia de HumanBrowser con un profile_dir
    unico derivado de su indice, garantizando fingerprints distintos.

    Parametros
    ----------
    task             : Corutina  async def task(browser, item) -> result
                       Recibe una instancia HumanBrowser ya lanzada y el item.
    items            : Lista de items a procesar (URLs, IDs, dicts, etc.)
    max_concurrent   : Maximo de navegadores activos simultaneamente.
                       Ajustar segun RAM disponible (~300-500 MB por instancia headless).
    browser_kwargs   : Kwargs adicionales para HumanBrowser (proxy, locale, etc.)
                       No incluir profile_dir, se genera automaticamente.
    profile_base_dir : Directorio base donde se crean los subdirectorios de perfil.

    Devuelve
    --------
    Lista de resultados en el mismo orden que items.
    Los items que fallan devuelven la excepcion capturada en lugar del resultado.

    Ejemplo
    -------
    async def scrape(browser: HumanBrowser, url: str) -> str:
        await browser.goto(url)
        return await browser.get_text("h1")

    resultados = await run_swarm(
        task=scrape,
        items=["https://a.com", "https://b.com", "https://c.com"],
        max_concurrent=3,
        browser_kwargs={"headless": True, "proxy": {"server": "http://proxy:8080"}},
    )
    """
    if browser_kwargs is None:
        browser_kwargs = {}

    semaphore = asyncio.Semaphore(max_concurrent)
    results   = [None] * len(items)

    async def _run_one(index: int, item: Any) -> None:
        async with semaphore:
            profile_dir = f"{profile_base_dir}/worker_{index:04d}"
            async with HumanBrowser(profile_dir=profile_dir, **browser_kwargs) as browser:
                try:
                    results[index] = await task(browser, item)
                except Exception as exc:
                    _log.error(
                        "run_swarm: worker %d fallo con %s: %s",
                        index, type(exc).__name__, exc,
                    )
                    results[index] = exc

    await asyncio.gather(*[_run_one(i, item) for i, item in enumerate(items)])
    return results


def run_swarm_multiprocess(
    task_fn: Any,
    items: List[Any],
    max_workers: int = 4,
    browser_kwargs: Optional[Dict[str, Any]] = None,
    profile_base_dir: str = "./hb_profiles",
) -> List[Any]:
    """
    Ejecuta un enjambre de HumanBrowser usando multiprocesamiento real.

    Cada worker es un proceso independiente del SO con su propio event loop
    y su propio interprete Python. Apto para servidores con multiples nucleos
    donde se quiere aislamiento total entre instancias (BotFarm).

    Esta funcion es SINCRONA — se llama sin await desde el hilo principal.
    Internamente cada proceso levanta su propio asyncio.run().

    Parametros
    ----------
    task_fn          : Funcion SINCRONA que recibe (item, profile_dir, browser_kwargs)
                       y llama internamente a asyncio.run(). Ver ejemplo abajo.
    items            : Lista de items a procesar.
    max_workers      : Numero de procesos paralelos (recomendado: nucleos CPU - 1).
    browser_kwargs   : Kwargs para HumanBrowser compartidos por todos los workers.
    profile_base_dir : Directorio base para los perfiles.

    Devuelve
    --------
    Lista de resultados en el mismo orden que items.

    Ejemplo
    -------
    def worker(item, profile_dir, browser_kwargs):
        async def _inner():
            async with HumanBrowser(profile_dir=profile_dir, **browser_kwargs) as browser:
                await browser.goto(item)
                return await browser.get_text("h1")
        return asyncio.run(_inner())

    if __name__ == "__main__":   # obligatorio en Windows
        resultados = run_swarm_multiprocess(
            task_fn=worker,
            items=["https://a.com", "https://b.com"],
            max_workers=2,
            browser_kwargs={"headless": True},
        )

    NOTA: task_fn debe ser serializable por pickle (funcion de nivel de modulo,
    no lambda ni closure). En Windows es obligatorio el guard if __name__ == "__main__".
    """
    import multiprocessing

    if browser_kwargs is None:
        browser_kwargs = {}

    def _worker_wrapper(args: tuple) -> Any:
        index, item = args
        profile_dir = f"{profile_base_dir}/worker_{index:04d}"
        try:
            return task_fn(item, profile_dir, browser_kwargs)
        except Exception as exc:
            _log.error(
                "run_swarm_multiprocess: worker %d fallo con %s: %s",
                index, type(exc).__name__, exc,
            )
            return exc

    with multiprocessing.Pool(processes=max_workers) as pool:
        results = pool.map(_worker_wrapper, list(enumerate(items)))

    return results