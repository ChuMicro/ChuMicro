"""The webui kit: one palette, one page shell, one affordance helper, one content-key, and the
SSE re-serve client. The shared construction layer beneath every browser surface an agent renders
for a human (the decision picker, a report, an A/B compare), so a palette, affordance, or theme fix
lands once and every surface inherits it.

Every page is self-contained: the kit emits one inline blob of CSS + JS, never an external served
asset, so a page works from file://. Pure stdlib. page() runs the dark-override linter (theme.py)
before it returns, so the kit can never ship a half-theme (light text on a light background in dark
mode).
"""
from __future__ import annotations

import hashlib
import json

from .theme import THEME_KEY, assert_full_dark_override

# ── One semantic palette ──────────────────────────────────────────────────────────────────
# Light on :root, FULLY overridden under :root[data-theme=dark] (the one hard theming rule).
# Same KEYS in both dicts is the invariant the dark-lint enforces; check_kit asserts it too.
PALETTE_LIGHT = {
    "--bg": "#f3f5f9", "--panel": "#ffffff", "--fg": "#1b2130", "--faint": "#69707e",
    "--border": "#e1e6ef", "--accent": "#6d5cf0", "--accent-fg": "#ffffff",
    "--accent2": "#8b5cf6", "--glow": "rgba(109,92,240,.18)",
    "--good": "#15803d", "--warn": "#b45309", "--bad": "#dc2626",
    "--chip": "#eef0f7", "--chip-fg": "#3a4252", "--shadow": "rgba(20,24,40,.10)",
}
PALETTE_DARK = {
    "--bg": "#12151c", "--panel": "#1b2030", "--fg": "#e7ebf3", "--faint": "#9aa3b4",
    "--border": "#2a3142", "--accent": "#8b7cf6", "--accent-fg": "#0c0e14",
    "--accent2": "#a78bfa", "--glow": "rgba(139,124,246,.20)",
    "--good": "#54d98a", "--warn": "#f0b357", "--bad": "#f3756b",
    "--chip": "#232a3a", "--chip-fg": "#c2cad9", "--shadow": "rgba(0,0,0,.45)",
}


def palette_css():
    """The single source of theme color: both blocks, identical keys."""
    light = "".join(f"{k}:{v};" for k, v in PALETTE_LIGHT.items())
    dark = "".join(f"{k}:{v};" for k, v in PALETTE_DARK.items())
    return f":root{{{light}}}\n:root[data-theme=dark]{{{dark}}}"


# ── Content key (the stale-verdict guard) ───────────────────────────────────────────────────
def content_key(content, *, prefix="page"):
    """A localStorage namespace derived from page CONTENT, so a regenerated page opens at its
    default state instead of restoring a stale verdict a prior render left under the same key."""
    if not isinstance(content, str):
        content = json.dumps(content, sort_keys=True, default=str)
    return f"{prefix}:{hashlib.sha1(content.encode()).hexdigest()[:12]}"


# ── The affordance rules, extracted so any surface (even a JS-rendered one) gets the SAME
#    press / confirm-flash / busy feedback ("a button press must show something"). ──
AFFORD_CSS = """
.chu-ok{background:var(--good)!important;color:var(--accent-fg)!important;border-color:var(--good)!important;}
.chu-press{transform:translateY(1px) scale(.99);filter:brightness(.94);}
.chu-busy{opacity:.6;cursor:progress;}
"""

# ── The re-serve channel surfaces (toast + progress), extracted so a surface that opts into the
#    live canvas gets them WITHOUT pulling in the kit's layout CSS. ──
CHANNEL_CSS = """
/* re-serve channel surfaces */
.chu-toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(12px);background:var(--panel);color:var(--fg);border:1px solid var(--border);box-shadow:0 8px 28px var(--shadow);padding:10px 16px;border-radius:10px;opacity:0;pointer-events:none;transition:.18s;z-index:9999;}
.chu-toast.show{opacity:1;transform:translateX(-50%) translateY(0);}
.chu-toast.good{border-color:var(--good);} .chu-toast.bad{border-color:var(--bad);}
.chu-prog{position:fixed;left:0;top:0;width:100%;height:3px;opacity:0;transition:.2s;z-index:9999;}
.chu-prog.show{opacity:1;} .chu-prog .bar{height:3px;background:var(--accent);transition:width .25s;}
.chu-prog span{position:absolute;right:8px;top:6px;font:11px system-ui;color:var(--faint);}
"""

# ── Base CSS: layout + the affordance + the re-serve toast/progress. Vars only, no raw hex. ──
BASE_CSS = """
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg);}
.wrap{max-width:860px;margin:0 auto;padding:32px 20px 80px;}
h1,h2,h3{color:var(--fg);line-height:1.2;} a{color:var(--accent);}
.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:18px 20px;margin:14px 0;box-shadow:0 2px 10px var(--shadow);}
.faint{color:var(--faint);}
button,.chu-act{font:inherit;border:1px solid var(--border);background:var(--panel);color:var(--fg);padding:8px 14px;border-radius:10px;cursor:pointer;transition:transform .1s,filter .1s,background .12s;}
button.primary{background:var(--accent);color:var(--accent-fg);border-color:var(--accent);}
button#themebtn{position:fixed;top:12px;right:12px;z-index:50;}
.chip{display:inline-block;background:var(--chip);color:var(--chip-fg);border-radius:999px;padding:2px 10px;font-size:12px;}
""" + AFFORD_CSS + CHANNEL_CSS

# ── One theme toggle (single THEME_KEY → the choice follows the human across every surface) ─────
_THEME_JS = ("""
(function(){var root=document.documentElement,K='__THEME_KEY__';
function get(){try{return localStorage.getItem(K);}catch(e){return null;}}
function set(d){root.dataset.theme=d?'dark':'light';var b=document.getElementById('themebtn');
 if(b)b.textContent=d?'\\u2600 light':'\\u263e dark';try{localStorage.setItem(K,d?'dark':'light');}catch(e){}}
var s=get();set(s?s==='dark':(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches));
document.addEventListener('click',function(e){if(e.target&&e.target.id==='themebtn')set(root.dataset.theme!=='dark');});})();
""".replace("__THEME_KEY__", THEME_KEY))

# ── One affordance helper (chuFlash / chuBusy / chuDone + a universal press feedback) ─────
_AFFORD_JS = """
(function(){
window.chuFlash=function(el,label){if(!el)return;if(el.dataset._restore===undefined)el.dataset._restore=el.textContent;
 if(label!==undefined)el.textContent=label;el.classList.add('chu-ok');clearTimeout(el._ft);
 el._ft=setTimeout(function(){el.classList.remove('chu-ok');el.textContent=el.dataset._restore;delete el.dataset._restore;},1400);};
window.chuBusy=function(el){if(el){el.disabled=true;el.classList.add('chu-busy');}};
window.chuDone=function(el){if(el){el.disabled=false;el.classList.remove('chu-busy');}};
document.addEventListener('pointerdown',function(e){var t=e.target.closest&&e.target.closest('button,[role=button],.chu-act');
 if(t){t.classList.add('chu-press');setTimeout(function(){t.classList.remove('chu-press');},140);}});})();
"""


def affordance_js():
    """The shared affordance JS (chuFlash / chuBusy / chuDone + a universal press feedback),
    exposed so a JS-rendered surface reuses it instead of rolling its own."""
    return _AFFORD_JS


def live_css():
    """The CSS a surface needs to host the re-serve channel (affordance + toast/progress) WITHOUT
    the kit's layout CSS, for a surface that has its own layout but opts into being driven through
    the live canvas."""
    return AFFORD_CSS + CHANNEL_CSS


def sse_client_js(events_path="/events"):
    """The re-serve client: subscribe to the server→browser push channel and act on each event
    (reload the canvas · navigate/scroll · toast · progress · done). EventSource auto-reconnects,
    so a respawned session server is picked up without a manual refresh."""
    return ("""
(function(){if(!window.EventSource)return;
function ensure(id){var e=document.getElementById(id);if(!e){e=document.createElement('div');e.id=id;document.body.appendChild(e);}return e;}
window.chuToast=function(text,kind){var t=ensure('chu-toast');t.textContent=text||'';t.className='chu-toast '+(kind||'');t.classList.add('show');
 clearTimeout(t._tt);t._tt=setTimeout(function(){t.classList.remove('show');},2600);};
window.chuProgress=function(v,text){var p=ensure('chu-prog');p.className='chu-prog show';
 p.textContent='';
 var bar=document.createElement('div');bar.className='bar';bar.style.width=Math.round((v||0)*100)+'%';
 var label=document.createElement('span');label.textContent=text||'';
 p.appendChild(bar);p.appendChild(label);
 if(v>=1)setTimeout(function(){p.classList.remove('show');},1200);};
var es=new EventSource('__EVENTS_PATH__');
es.onmessage=function(ev){var m;try{m=JSON.parse(ev.data);}catch(e){return;}
 if(m.type==='reload'){location.reload();}
 else if(m.type==='navigate'){if(m.url)location.href=m.url;else if(m.id){var el=document.getElementById(m.id);if(el)el.scrollIntoView({behavior:'smooth',block:'center'});}}
 else if(m.type==='toast'){chuToast(m.text,m.kind);}
 else if(m.type==='progress'){chuProgress(m.value,m.text);}
 else if(m.type==='done'){chuToast(m.text||'done','good');}};})();
""".replace("__EVENTS_PATH__", events_path))


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def page(title, body, *, extra_css="", extra_js="", live=False, theme_button=True):
    """Assemble a self-contained page from the kit: palette + base CSS + the theme toggle +
    the affordance helper (+ the re-serve SSE client when `live`). Asserts the dark-override
    contract before returning, so a kit page can never ship a half-theme.

    `live=True` injects the SSE client (the page is served by a SessionServer with /events).
    """
    css = palette_css() + "\n" + BASE_CSS + (("\n" + extra_css) if extra_css else "")
    js = _THEME_JS + _AFFORD_JS + (sse_client_js() if live else "") + (extra_js or "")
    btn = '<button id="themebtn" class="chu-act" type="button"></button>' if theme_button else ""
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>' + _esc(title) + '</title><style>' + css + '</style></head><body>'
        + btn + body + '<script>' + js + '</script></body></html>'
    )
    assert_full_dark_override(html, label=title)
    return html
