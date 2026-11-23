#!/usr/bin/env python3
"""chrome_ctl: drive the user's REAL Google Chrome via AppleScript + JS (no downloads, background-friendly).
Usage: chrome_ctl.py [--tab ID] [--front] [--yes] CMD ...
 tabs | open URL | activate [ID] | close [ID|--mine] | read [--max N] | click N | fill N "text"
 select N "option" | press-enter N | scroll [down|up|top|bottom|PIXELS] | wait-for "text" [--timeout S]
 download-links | get-html [--max N] | status
All output is one JSON line. Needs Chrome > View > Developer > Allow JavaScript from Apple Events
(only for read/click/fill/...; tabs/open/close/activate work without). Never toggled by this tool.
Safety: refuses password/card fills, and click/press-enter on send/submit/buy/pay/delete-like controls unless --yes
(use --yes ONLY after the user said yes). Opened tabs tracked in data/chrome_tabs.json."""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "data", "chrome_tabs.json")
FIX = "Chrome menu bar: View > Developer > Allow JavaScript from Apple Events (tick it once)."

def out(d, code=0):
    print(json.dumps(d, ensure_ascii=False)); sys.exit(code)

def osa(script, *args, timeout=20):
    p = subprocess.run(["osascript", "-e", script, *map(str, args)], capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.rstrip("\n"), p.stderr.strip()

def running():
    return osa('application "Google Chrome" is running')[1] == "true"

def load():
    try: return json.load(open(STATE))
    except Exception: return {"mine": [], "current": None}

def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True); json.dump(s, open(STATE, "w"))

# ---------- AppleScript pieces ----------
LIST_S = '''tell application "Google Chrome"
set o to ""
repeat with w in windows
set wid to id of w
set ai to active tab index of w
set i to 0
repeat with t in tabs of w
set i to i + 1
set o to o & wid & (ASCII character 9) & (id of t) & (ASCII character 9) & (i = ai) & (ASCII character 9) & (title of t) & (ASCII character 9) & (URL of t) & linefeed
end repeat
end repeat
return o
end tell'''

OPEN_S = '''on run argv
set u to item 1 of argv
set fr to item 2 of argv
tell application "Google Chrome"
set w to missing value
repeat with x in windows
if mode of x is "normal" then
set w to x
exit repeat
end if
end repeat
if w is missing value then
set w to make new window
set t to active tab of w
set URL of t to u
else
set prev to active tab index of w
set t to make new tab at end of tabs of w with properties {URL:u}
if fr is not "1" then set active tab index of w to prev
end if
if fr is "1" then
activate
set index of w to 1
end if
return ((id of w) as text) & (ASCII character 9) & ((id of t) as text)
end tell
end run'''

FIND = '''on run argv
set tid to (item 1 of argv) as integer
set act to item 2 of argv
set js to item 3 of argv
tell application "Google Chrome"
repeat with w in windows
set ts to (tabs of w whose id is tid)
if (count of ts) > 0 then
set t to item 1 of ts
if act is "js" then return (execute t javascript js)
if act is "close" then
close t
return "closed"
end if
if act is "activate" then
set active tab index of w to (index of t)
activate
set index of w to 1
return "ok"
end if
end if
end repeat
return "NOTAB"
end tell
end run'''

def tab_list():
    rc, o, e = osa(LIST_S)
    if rc: out({"ok": False, "error": e[:200]}, 1)
    st = load(); rows = []
    for ln in o.split("\n"):
        f = ln.split("\t")
        if len(f) >= 5:
            rows.append({"win": int(f[0]), "tab": int(f[1]), "active": f[2] == "true", "title": f[3][:80], "url": f[4][:200], "mine": int(f[1]) in st["mine"]})
    return rows

def run_js(tab, js):
    rc, o, e = osa(FIND, tab, "js", js, timeout=30)
    if rc:
        if "turned off" in e or "Allow JavaScript" in e or "JavaScript through AppleScript" in e:
            out({"ok": False, "error": "js_off", "fix": FIX}, 2)
        out({"ok": False, "error": e[:250]}, 1)
    if o == "NOTAB": out({"ok": False, "error": "tab %s not found (closed?)" % tab}, 1)
    return o

# ---------- page-side JS ----------
COLLECT = r'''
function jvCollect(){var sel='a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=textbox],[role=combobox],[role=menuitem],[role=tab],[role=checkbox],[onclick],[contenteditable=""],[contenteditable=true]';
var seen=new Set(),res=[];document.querySelectorAll(sel).forEach(function(e){if(seen.has(e))return;seen.add(e);
var r=e.getBoundingClientRect();var cs=getComputedStyle(e);if((r.width<2&&r.height<2)||cs.visibility==='hidden'||cs.display==='none')return;res.push(e)});return res}
function jvLabel(e){var t=e.getAttribute('aria-label')||(e.innerText||'').trim()||e.value&&e.type!=='password'&&e.type!=='text'&&e.value||e.placeholder||e.title||e.alt||e.name||(e.querySelector&&e.querySelector('img[alt]')||{}).alt||'';
t=String(t).replace(/\s+/g,' ').trim();return t.slice(0,70)}
function jvKind(e){var t=e.tagName.toLowerCase();if(t==='a')return'link';if(t==='button'||e.getAttribute('role')==='button')return'button';if(t==='select')return'select';if(t==='textarea')return'input';if(t==='input'){var y=(e.type||'text').toLowerCase();return(y==='submit'||y==='button'||y==='image')?'button':(y==='checkbox'||y==='radio')?y:'input'}return e.getAttribute('contenteditable')!==null?'input':(e.getAttribute('role')||t)}
var RISK=/\b(send|submit|buy|pay|purchase|place order|order now|checkout|confirm|delete|remove|post|publish|subscribe|sign ?up|donate|transfer)\b/i;
function jvRisky(e){var l=jvLabel(e),k=jvKind(e);if((k==='button'||e.type==='submit')&&RISK.test(l))return true;if(e.type==='submit'&&k==='button')return true;return false}
function jvSecret(e){var s=((e.type||'')+' '+(e.autocomplete||'')+' '+(e.name||'')+' '+(e.id||'')).toLowerCase();return /password|passwd|cc-|card|cvv|cvc|iban|ssn/.test(s)}
'''

def page(body):
    return "(function(){try{" + COLLECT + body + "}catch(e){return JSON.stringify({ok:false,error:String(e)})}})()"

def jarg(s): return json.dumps(s)

def parse(o):
    try: return json.loads(o)
    except Exception: return {"ok": False, "error": "bad js result", "raw": o[:200]}

def cur_tab(a):
    if a["tab"]: return int(a["tab"])
    st = load()
    if st["current"]: return st["current"]
    out({"ok": False, "error": "no tab: run `open URL` first or pass --tab ID"}, 1)

def parse_args(argv):
    a = {"tab": None, "front": False, "yes": False, "max": None, "timeout": 10, "mine": False}; rest = []; i = 0
    while i < len(argv):
        x = argv[i]
        if x == "--tab": a["tab"] = argv[i+1]; i += 2
        elif x == "--max": a["max"] = int(argv[i+1]); i += 2
        elif x == "--timeout": a["timeout"] = float(argv[i+1]); i += 2
        elif x == "--front": a["front"] = True; i += 1
        elif x == "--yes": a["yes"] = True; i += 1
        elif x == "--mine": a["mine"] = True; i += 1
        else: rest.append(x); i += 1
    return a, rest

def main():
    a, r = parse_args(sys.argv[1:])
    if not r: out({"ok": False, "error": "usage: chrome_ctl.py CMD (see header)"}, 1)
    cmd, args = r[0], r[1:]
    if not running(): out({"ok": False, "error": "Google Chrome is not running"}, 1)
    st = load()

    if cmd == "status":
        rc, o, e = osa(FIND, 0, "js", "1")  # tab 0 never exists; probes JS permission via a real tab below
        t = tab_list()
        probe = next((x for x in t if x["tab"] == st["current"]), None)
        js = "unknown (open a tab first)"
        if probe:
            rc, o, e = osa(FIND, probe["tab"], "js", "1")
            js = "off" if rc and ("turned off" in e or "Allow JavaScript" in e) else "on"
        out({"ok": True, "tabs": len(t), "mine": st["mine"], "current": st["current"], "js_from_apple_events": js, "fix_if_off": FIX})
    if cmd == "tabs":
        out({"ok": True, "tabs": tab_list()})
    if cmd == "open":
        if not args: out({"ok": False, "error": "open URL"}, 1)
        u = args[0] if "://" in args[0] else "https://" + args[0]
        rc, o, e = osa(OPEN_S, u, "1" if a["front"] else "0")
        if rc: out({"ok": False, "error": e[:200]}, 1)
        w, t = o.split("\t"); t = int(t)
        st["mine"].append(t); st["current"] = t; save(st)
        out({"ok": True, "tab": t, "win": int(w), "url": u})
    if cmd == "activate":
        t = int(args[0]) if args else cur_tab(a)
        rc, o, e = osa(FIND, t, "activate", ""); out({"ok": o == "ok", "tab": t})
    if cmd == "close":
        if a["mine"] or (args and args[0] == "--mine"):
            ids = list(st["mine"])
        else:
            ids = [int(args[0])] if args else [cur_tab(a)]
            # only ever close tabs Alfred opened
            bad = [i for i in ids if i not in st["mine"]]
            if bad: out({"ok": False, "error": "refusing: tab %s was not opened by Alfred" % bad}, 1)
        closed = []
        for i in ids:
            rc, o, e = osa(FIND, i, "close", "")
            closed.append(i)  # NOTAB also fine: already gone
        st["mine"] = [i for i in st["mine"] if i not in closed]
        if st["current"] in closed: st["current"] = st["mine"][-1] if st["mine"] else None
        save(st); out({"ok": True, "closed": closed})

    tab = cur_tab(a)
    if cmd == "read":
        mx = a["max"] or 3000
        res = parse(run_js(tab, page('''
var els=jvCollect(),items=[];els.forEach(function(e,i){if(items.length>=150)return;var k=jvKind(e),l=jvLabel(e);if(!l&&k==='link')return;
var d={i:i,k:k,l:l};if(k==='input'||k==='select'){d.v=(e.type==='password')?'':String(e.value||'').slice(0,40)}if(k==='link'){try{d.h=e.getAttribute('href').slice(0,80)}catch(x){}}items.push(d)});
var txt=(document.body?document.body.innerText:'').replace(/\\n{3,}/g,'\\n\\n').trim();
return JSON.stringify({ok:true,title:document.title,url:location.href,text:txt.slice(0,%d),text_len:txt.length,items:items,scrollY:Math.round(scrollY),height:document.documentElement.scrollHeight})''' % mx)))
        if res.get("ok"):
            res["items"] = ["[%d] %s \"%s\"%s%s" % (x["i"], x["k"], x["l"], (" ="+x["v"]) if x.get("v") else "", (" -> "+x["h"]) if x.get("h") else "") for x in res["items"]]
            res["tab"] = tab
        out(res)
    if cmd in ("click", "fill", "select", "press-enter"):
        if not args: out({"ok": False, "error": cmd + " N"}, 1)
        n = int(args[0].strip("[]")); val = args[1] if len(args) > 1 else ""
        if cmd in ("fill", "select") and len(args) < 2: out({"ok": False, "error": cmd + " N \"text\""}, 1)
        yes = "true" if a["yes"] else "false"
        pre = 'var els=jvCollect(),e=els[%d];if(!e)return JSON.stringify({ok:false,error:"no element [%d] (run read again)"});var YES=%s,L=jvLabel(e);' % (n, n, yes)
        if cmd == "click":
            body = pre + 'if(!YES&&jvRisky(e))return JSON.stringify({ok:false,error:"needs_user_yes",label:L,hint:"risky control; ask the user, then rerun with --yes"});e.scrollIntoView({block:"center"});e.click();return JSON.stringify({ok:true,clicked:L})'
        elif cmd == "fill":
            body = pre + '''if(jvSecret(e))return JSON.stringify({ok:false,error:"secret_field",hint:"never type passwords/card numbers; ask the user to type it"});
var v=%s;e.focus();if(e.isContentEditable){document.execCommand("selectAll");document.execCommand("insertText",false,v)}else{var p=e.tagName==="TEXTAREA"?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(p,"value").set.call(e,v);e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}))}
return JSON.stringify({ok:true,filled:L,value:(e.value!==undefined?e.value:e.innerText).slice(0,60)})''' % jarg(val)
        elif cmd == "select":
            body = pre + '''if(e.tagName!=="SELECT")return JSON.stringify({ok:false,error:"not a select"});var v=%s.toLowerCase(),f=null;
for(var o of e.options){if(o.text.trim().toLowerCase()===v||o.value.toLowerCase()===v){f=o;break}}if(!f)for(var o of e.options){if(o.text.toLowerCase().indexOf(v)>=0){f=o;break}}
if(!f)return JSON.stringify({ok:false,error:"option not found",options:Array.from(e.options).slice(0,20).map(function(o){return o.text.trim()})});
e.value=f.value;e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));return JSON.stringify({ok:true,selected:f.text.trim()})''' % jarg(val)
        else:
            body = pre + '''var f=e.form;if(!YES&&f){var sb=f.querySelector("[type=submit],button:not([type])");var pw=f.querySelector("input[type=password]");var risky=pw||Array.from(f.querySelectorAll("input")).some(jvSecret)||(sb&&jvRisky(sb));if(risky)return JSON.stringify({ok:false,error:"needs_user_yes",hint:"form looks like login/payment/send; ask the user, then rerun with --yes"})}
e.focus();var o={key:"Enter",code:"Enter",keyCode:13,which:13,bubbles:true,cancelable:true};e.dispatchEvent(new KeyboardEvent("keydown",o));e.dispatchEvent(new KeyboardEvent("keypress",o));
if(f&&f.requestSubmit&&e.tagName==="INPUT"){try{f.requestSubmit()}catch(x){}}e.dispatchEvent(new KeyboardEvent("keyup",o));return JSON.stringify({ok:true,pressed:L})'''
        out(parse(run_js(tab, page(body))))
    if cmd == "scroll":
        w = args[0] if args else "down"
        js = {"down": "scrollBy(0,innerHeight*0.8)", "up": "scrollBy(0,-innerHeight*0.8)", "top": "scrollTo(0,0)", "bottom": "scrollTo(0,document.documentElement.scrollHeight)"}.get(w) or "scrollBy(0,%d)" % int(w)
        out(parse(run_js(tab, page(js + ';return JSON.stringify({ok:true,scrollY:Math.round(scrollY),height:document.documentElement.scrollHeight})'))))
    if cmd == "wait-for":
        if not args: out({"ok": False, "error": 'wait-for "text"'}, 1)
        end = time.time() + a["timeout"]
        while True:
            res = parse(run_js(tab, page('return JSON.stringify({ok:true,found:(document.body?document.body.innerText:"").toLowerCase().indexOf(%s.toLowerCase())>=0,ready:document.readyState})' % jarg(args[0]))))
            if res.get("found"): out({"ok": True, "found": True})
            if time.time() > end: out({"ok": False, "found": False, "error": "timeout"}, 1)
            time.sleep(0.4)
    if cmd == "download-links":
        out(parse(run_js(tab, page('''var x=/\\.(pdf|zip|dmg|pkg|docx?|xlsx?|pptx?|csv|mp3|mp4|mov|png|jpe?g|gif|webp|svg|txt|json|epub)(\\?|#|$)/i,r=[];document.querySelectorAll("a[href]").forEach(function(a){if(r.length<100&&(a.hasAttribute("download")||x.test(a.href)))r.push({text:jvLabel(a),url:a.href})});return JSON.stringify({ok:true,links:r})'''))))
    if cmd == "get-html":
        mx = a["max"] or 6000
        out(parse(run_js(tab, page('''var c=document.body.cloneNode(true);c.querySelectorAll("script,style,svg,noscript,link,meta,iframe").forEach(function(n){n.remove()});var h=c.outerHTML.replace(/\\s+/g," ").replace(/ (style|class|data-[a-z-]+)="[^"]*"/g,"");return JSON.stringify({ok:true,len:h.length,html:h.slice(0,%d)})''' % mx))))
    out({"ok": False, "error": "unknown command " + cmd}, 1)

if __name__ == "__main__":
    try: main()
    except subprocess.TimeoutExpired: out({"ok": False, "error": "osascript timeout"}, 1)
