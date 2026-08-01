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
    "--bg": "#f4f6fa", "--panel": "#ffffff", "--fg": "#171d2b", "--faint": "#5f6878",
    "--border": "#e1e6ef", "--accent": "#6d5cf0", "--accent-fg": "#ffffff",
    "--accent2": "#8b5cf6", "--glow": "rgba(109,92,240,.18)",
    "--good": "#15803d", "--warn": "#b45309", "--bad": "#dc2626",
    "--chip": "#eef0f7", "--chip-fg": "#3a4252", "--shadow": "rgba(20,24,40,.10)",
}
PALETTE_DARK = {
    "--bg": "#0f1219", "--panel": "#181d2a", "--fg": "#e9edf5", "--faint": "#9aa4b6",
    "--border": "#293144", "--accent": "#8b7cf6", "--accent-fg": "#0c0e14",
    "--accent2": "#a78bfa", "--glow": "rgba(139,124,246,.22)",
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


# ── Design tokens: the ONE spacing/type/radius scale every surface derives from. Lengths
#    only (no colors), so the dark-lint has nothing to check here; a template that hardcodes
#    a px value instead of a token is the drift this kills. ──
TOKENS_CSS = """
:root{--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:36px;
--r1:6px;--r2:10px;--r3:14px;
--t-title:17px;--t-body:14.5px;--t-small:13px;--t-micro:11px;
--mono:ui-monospace,Menlo,monospace;}
"""

# ── Shared components: the standard every surface builds from. A template styles ONLY its
#    own template-specific selectors, thinly, on top of these; it never redefines a chu-*
#    class or a primitive below. The readout strip (.chu-read) is the house signature: every
#    surface carries its vitals as one mono strip under the title. ──
COMPONENTS_CSS = """
.chu-head{display:flex;flex-direction:column;gap:var(--s2);margin:0 0 var(--s4);}
.chu-title{font-size:var(--t-title);font-weight:650;letter-spacing:-.01em;margin:0;line-height:1.3;}
.chu-read{display:flex;flex-wrap:wrap;gap:var(--s1) var(--s4);font:500 var(--t-micro)/1.7 var(--mono);
 color:var(--faint);text-transform:uppercase;letter-spacing:.07em;}
.chu-read b{color:var(--fg);font-weight:650;}
.chu-brief{margin:0;max-width:76ch;font-size:var(--t-body);color:var(--fg);}
.chu-brief.faint{color:var(--faint);}
.chu-label{display:inline-block;font:700 var(--t-micro)/1.5 var(--mono);letter-spacing:.07em;
 text-transform:uppercase;color:var(--faint);background:var(--chip);border-radius:var(--r1);
 padding:2px 7px;}
.chu-mono{white-space:pre-wrap;overflow-wrap:break-word;background:var(--bg);border:1px solid var(--border);
 border-radius:var(--r2);padding:var(--s2) var(--s3);font:var(--t-small)/1.6 var(--mono);color:var(--fg);}
.chu-table{width:100%;border-collapse:collapse;font-size:var(--t-body);}
.chu-table th{text-align:left;font:700 var(--t-micro)/1.5 var(--mono);text-transform:uppercase;
 letter-spacing:.07em;color:var(--faint);padding:var(--s1) var(--s3);}
.chu-table td{padding:var(--s2) var(--s3);border-top:1px solid var(--border);}
.chu-pass{color:var(--good);font-weight:700;} .chu-fail{color:var(--bad);font-weight:700;}
.chu-run{color:var(--warn);font-weight:700;} .chu-na{color:var(--faint);}
.chu-tl{font:var(--t-small)/1.8 var(--mono);padding:1px 0;}
.chu-tl .t{color:var(--faint);margin-right:var(--s3);}
.chu-actions{position:sticky;bottom:0;display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap;
 background:var(--panel);border:1px solid var(--border);border-radius:var(--r2);
 padding:var(--s2) var(--s4);margin-top:var(--s5);box-shadow:0 -6px 22px var(--shadow);}
"""

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

# ── Base CSS: tokens + layout + components + affordance + channel. Vars only, no raw hex. ──
BASE_CSS = TOKENS_CSS + """
*{box-sizing:border-box}
body{margin:0;font:var(--t-body)/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);
 color:var(--fg);-webkit-font-smoothing:antialiased;}
.wrap{max-width:880px;margin:0 auto;padding:var(--s5) var(--s4) var(--s6);}
h1,h2,h3{color:var(--fg);line-height:1.3;letter-spacing:-.01em;} a{color:var(--accent);}
h1{font-size:var(--t-title);font-weight:650;}
code,pre{font:.92em var(--mono);}
::selection{background:var(--accent);color:var(--accent-fg);}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--r3);padding:var(--s4) var(--s4);margin:var(--s3) 0;box-shadow:0 2px 10px var(--shadow);}
.faint{color:var(--faint);}
button,.chu-act{font:inherit;font-size:var(--t-small);border:1px solid var(--border);background:var(--panel);color:var(--fg);padding:7px 14px;border-radius:var(--r2);cursor:pointer;transition:transform .1s,filter .1s,background .12s,border-color .12s;}
button:hover{border-color:var(--accent);}
button.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:var(--accent-fg);border-color:var(--accent);box-shadow:0 2px 12px var(--glow);}
button.primary:hover{filter:brightness(1.07);}
button.quiet{border-color:transparent;background:none;color:var(--faint);}
button.quiet:hover{color:var(--fg);border-color:var(--border);}
button#themebtn{position:fixed;top:12px;right:12px;z-index:50;}
textarea,input,select{font:inherit;color:var(--fg);}
.chip{display:inline-block;background:var(--chip);color:var(--chip-fg);border-radius:999px;padding:2px 10px;font-size:12px;}
@media (prefers-reduced-motion:reduce){*{transition-duration:.01ms!important;animation-duration:.01ms!important;}}
""" + COMPONENTS_CSS + AFFORD_CSS + CHANNEL_CSS

# ── One theme model: THEME_KEY in localStorage is the single source of truth. A top-level
#    page shows the toggle; an EMBEDDED page (an iframe under the hub shell) hides its own
#    toggle and follows the shell live via the storage event, so the shell's one switch
#    re-themes every surface at once: never a dark bar over a light body. ──
_THEME_JS = ("""
(function(){var root=document.documentElement,K='__THEME_KEY__',framed=(window.self!==window.top);
function get(){try{return localStorage.getItem(K);}catch(e){return null;}}
function apply(d){root.dataset.theme=d?'dark':'light';var b=document.getElementById('themebtn');
 if(b){b.hidden=framed;b.textContent=d?'\\u2600 light':'\\u263e dark';}}
function set(d){apply(d);try{localStorage.setItem(K,d?'dark':'light');}catch(e){}}
var s=get();apply(s?s==='dark':(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches));
window.addEventListener('storage',function(e){if(e.key===K)apply(e.newValue==='dark');});
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
