// alfred-ctl — fast computer-control CLI for Alfred. One-line JSON out, exit 0/1.
import AppKit
import ApplicationServices
import ScreenCaptureKit
import ImageIO
import UniformTypeIdentifiers

setvbuf(stdout, nil, _IOFBF, 1 << 16)

func out(_ d: [String: Any], code: Int32 = 0) -> Never {
    var o = d
    if o["ok"] == nil { o["ok"] = code == 0 }
    if let data = try? JSONSerialization.data(withJSONObject: o, options: [.sortedKeys, .withoutEscapingSlashes]),
       let s = String(data: data, encoding: .utf8) { print(s) }
    fflush(stdout)
    exit(code)
}
func ok(_ extra: [String: Any] = [:]) -> Never { var d = extra; d["ok"] = true; out(d) }
func fail(_ msg: String, _ extra: [String: Any] = [:]) -> Never { var d = extra; d["ok"] = false; d["error"] = msg; out(d, code: 1) }

let usage = """
alfred-ctl — computer control (JSON out). BACKGROUND MODE is default: no focus steal / mouse / front-app keys unless --mouse or --front (setting background_mode=false turns it off).
  Background-safe: front find ui windows apps wait menu press fill window quit screenshot open-url/open-file/open-app (open -g) key|type --app Name (posted to that app only)
  click X Y [--right|--double]   move X Y   scroll DX DY   type "text"   key cmd+shift+4
  open-app Name   open-url URL [--app Name]   open-file PATH [--app Name]   focus Name   quit Name   front   apps
  window Name X Y W H | window Name left|right|full|center|top-left|top-right|bottom-left|bottom-right   windows [--app Name]
  find "title" [--app Name] [--role Button]   press "title" [--app Name] [--role R] [--index N] [--click]   fill "field" "text" [--app Name]
  ui [--app Name] [--depth 4]   wait "title" [--app Name] [--timeout 5]   menu "File>Export>File…" [--app Name]   menus [--app Name] [File]
  do "step" "step" …   (run several commands in one call, stop at the first failure; steps: any command above or "sleep 0.5")
  screenshot PATH [--window] [--app Name] [--retina]   point X Y "label" ["hint"] [--step N --of M]   doctor
"""

// MARK: watchdog: this tool must never hang the brain (a stuck SkyLight/AX call = JSON error + exit)
let watchdogSecs: Double = {
    let c = CommandLine.arguments.dropFirst().first ?? ""
    return ["screenshot": 20, "open-app": 15, "focus": 15, "quit": 8, "wait": 40, "do": 90, "press": 15, "find": 12, "menu": 12][c] ?? 8
}()
DispatchQueue.global().asyncAfter(deadline: .now() + watchdogSecs) {
    let msg = "{\"error\":\"TIMEOUT: alfred-ctl \\(CommandLine.arguments.dropFirst().first ?? \"\") hung for \\(Int(watchdogSecs))s; the target app may be frozen or blocked. Try a different way.\",\"ok\":false}\n"
    FileHandle.standardOutput.write(msg.data(using: .utf8)!)
    _exit(1)
}

// MARK: args
var args = Array(CommandLine.arguments.dropFirst())
guard let cmd = args.first else { out(["ok": true, "usage": usage]) }
args.removeFirst()
func flag(_ n: String) -> Bool { if let i = args.firstIndex(of: n) { args.remove(at: i); return true }; return false }
func opt(_ n: String) -> String? {
    guard let i = args.firstIndex(of: n), i + 1 < args.count else { return nil }
    let v = args[i + 1]; args.removeSubrange(i...(i + 1)); return v
}
// MARK: background mode (default ON): never steal focus, mouse or keyboard unless told (--mouse / --front) or the setting is off
let alfredHome: String = {
    if let e = ProcessInfo.processInfo.environment["ALFRED_HOME"], !e.isEmpty { return (e as NSString).expandingTildeInPath }
    return NSHomeDirectory() + "/Library/Application Support/Alfred"
}()
let useBG: Bool = {
    var v = true
    if let d = FileManager.default.contents(atPath: alfredHome + "/data/ui/settings.json"),
       let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any], let b = j["background_mode"] as? Bool { v = b }
    if ProcessInfo.processInfo.environment["ALFRED_BG"] == "0" { v = false }
    if args.contains("--mouse") || args.contains("--front") { v = false }
    return v
}()
args.removeAll { $0 == "--mouse" || $0 == "--front" }
func requireMouse(_ what: String) {
    if useBG {
        fail("NEEDS_MOUSE: \(what) needs the mouse or the keyboard focus, and background mode is on. Say a short heads-up to the user first (\"I need the mouse for a moment\"), then repeat with --mouse. Prefer: menu, press (AX), fill, key/type with --app, open -g.", ["code": "NEEDS_MOUSE"])
    }
}
func num(_ s: String?, _ what: String) -> Double {
    guard let s, let d = Double(s) else { fail("bad number for \(what)") }
    return d
}

// MARK: AX helpers
func needAX() {
    if !AXIsProcessTrusted() {
        fail("NO_ACCESSIBILITY: Accessibility permission is not granted. the user must enable it in System Settings > Privacy & Security > Accessibility for Alfred (the app that runs this tool), then retry. Fall back to open-app/open-url/key only; do not claim success.")
    }
}
func attr(_ e: AXUIElement, _ a: String) -> CFTypeRef? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(e, a as CFString, &v) == .success ? v : nil
}
func str(_ e: AXUIElement, _ a: String) -> String? {
    if let s = attr(e, a) as? String, !s.isEmpty { return s }
    return nil
}
func kids(_ e: AXUIElement) -> [AXUIElement] { (attr(e, kAXChildrenAttribute) as? [AXUIElement]) ?? [] }
func frame(_ e: AXUIElement) -> [Int]? {
    var p = CGPoint.zero, s = CGSize.zero
    guard let pv = attr(e, kAXPositionAttribute), let sv = attr(e, kAXSizeAttribute),
          AXValueGetValue(pv as! AXValue, .cgPoint, &p), AXValueGetValue(sv as! AXValue, .cgSize, &s) else { return nil }
    return [Int(p.x), Int(p.y), Int(s.width), Int(s.height)]
}
func titleOf(_ e: AXUIElement) -> String? {
    str(e, kAXTitleAttribute) ?? str(e, kAXDescriptionAttribute) ?? (attr(e, kAXValueAttribute) as? String).flatMap { $0.isEmpty ? nil : String($0.prefix(80)) }
}
func actions(_ e: AXUIElement) -> [String] {
    var acts: CFArray?
    AXUIElementCopyActionNames(e, &acts)
    return (acts as? [String]) ?? []
}

func alive(_ a: NSRunningApplication) -> Bool { NSRunningApplication(processIdentifier: a.processIdentifier) != nil }
func isRunningVisible(_ a: NSRunningApplication) -> Bool { a.activationPolicy != .prohibited && alive(a) }
func findRunning(_ name: String) -> NSRunningApplication? {
    let n = name.lowercased()
    let apps = NSWorkspace.shared.runningApplications.filter(isRunningVisible)
    return apps.first(where: { $0.localizedName?.lowercased() == n })
        ?? apps.first(where: { $0.bundleIdentifier?.lowercased() == n })
        ?? apps.first(where: { $0.localizedName?.lowercased().hasPrefix(n) == true })
        ?? apps.first(where: { $0.localizedName?.lowercased().contains(n) == true })
}
func runningApp(_ name: String?) -> NSRunningApplication {
    if let name {
        if let a = findRunning(name) { return a }
        fail("app not running: \(name). Use open-app \"\(name)\" first.")
    }
    guard let a = NSWorkspace.shared.frontmostApplication else { fail("no frontmost app") }
    return a
}
func axApp(_ name: String?, timeout: Float = 1.0) -> (AXUIElement, NSRunningApplication) {
    needAX()
    let a = runningApp(name)
    let e = AXUIElementCreateApplication(a.processIdentifier)
    AXUIElementSetMessagingTimeout(e, timeout)
    // Electron / Chromium apps only expose their tree when asked
    AXUIElementSetAttributeValue(e, "AXManualAccessibility" as CFString, kCFBooleanTrue)
    return (e, a)
}
func windowsOf(_ app: AXUIElement) -> [AXUIElement] {
    var w: [AXUIElement] = []
    if let f = attr(app, kAXFocusedWindowAttribute) { w.append(f as! AXUIElement) }
    if let m = attr(app, kAXMainWindowAttribute) { let x = m as! AXUIElement; if !w.contains(where: { CFEqual($0, x) }) { w.append(x) } }
    for x in (attr(app, kAXWindowsAttribute) as? [AXUIElement]) ?? [] where !w.contains(where: { CFEqual($0, x) }) { w.append(x) }
    return w
}
func activate(_ a: NSRunningApplication, force: Bool = false) {
    if useBG && !force { return }  // background mode: never raise an app
    a.unhide()
    a.activate(options: [.activateAllWindows])
}
/// wait until `a` is frontmost (max `secs`)
func waitFront(_ a: NSRunningApplication, _ secs: Double = 1.5) -> Bool {
    let end = Date().addingTimeInterval(secs)
    while Date() < end {
        if NSWorkspace.shared.frontmostApplication?.processIdentifier == a.processIdentifier { return true }
        usleep(40000)
    }
    return NSWorkspace.shared.frontmostApplication?.processIdentifier == a.processIdentifier
}

// MARK: input synthesis
// nil source: a pre-created hidSystemState CGEventSource deadlocked inside SkyLight (SLEventCreate) when run under the brain
let src: CGEventSource? = nil
func mouse(_ type: CGEventType, _ p: CGPoint, _ btn: CGMouseButton = .left, clicks: Int64 = 1) {
    let e = CGEvent(mouseEventSource: src, mouseType: type, mouseCursorPosition: p, mouseButton: btn)
    e?.setIntegerValueField(.mouseEventClickState, value: clicks)
    e?.post(tap: .cghidEventTap)
}
func click(_ p: CGPoint, right: Bool = false, double: Bool = false) {
    mouse(.mouseMoved, p)
    usleep(8000)
    let (d, u, b): (CGEventType, CGEventType, CGMouseButton) = right ? (.rightMouseDown, .rightMouseUp, .right) : (.leftMouseDown, .leftMouseUp, .left)
    mouse(d, p, b, clicks: 1); usleep(3000); mouse(u, p, b, clicks: 1)
    if double { usleep(30000); mouse(d, p, b, clicks: 2); usleep(3000); mouse(u, p, b, clicks: 2) }
}

let keyCodes: [String: CGKeyCode] = [
    "a":0,"s":1,"d":2,"f":3,"h":4,"g":5,"z":6,"x":7,"c":8,"v":9,"b":11,"q":12,"w":13,"e":14,"r":15,"y":16,"t":17,
    "1":18,"2":19,"3":20,"4":21,"6":22,"5":23,"=":24,"9":25,"7":26,"-":27,"8":28,"0":29,"]":30,"o":31,"u":32,"[":33,
    "i":34,"p":35,"l":37,"j":38,"'":39,"k":40,";":41,"\\":42,",":43,"/":44,"n":45,"m":46,".":47,"`":50,
    "return":36,"enter":36,"tab":48,"space":49,"delete":51,"backspace":51,"esc":53,"escape":53,"forwarddelete":117,
    "left":123,"right":124,"down":125,"up":126,"home":115,"end":119,"pageup":116,"pagedown":121,
    "f1":122,"f2":120,"f3":99,"f4":118,"f5":96,"f6":97,"f7":98,"f8":100,"f9":101,"f10":109,"f11":103,"f12":111,
]
func post(_ e: CGEvent?, _ pid: pid_t?) { if let pid { e?.postToPid(pid) } else { e?.post(tap: .cghidEventTap) } }
func pressKey(_ combo: String, pid: pid_t? = nil) {
    var flags: CGEventFlags = []
    var key: String?
    for part in combo.lowercased().split(separator: "+", omittingEmptySubsequences: false).map(String.init) {
        switch part {
        case "cmd", "command", "meta": flags.insert(.maskCommand)
        case "shift": flags.insert(.maskShift)
        case "ctrl", "control": flags.insert(.maskControl)
        case "opt", "option", "alt": flags.insert(.maskAlternate)
        case "fn": flags.insert(.maskSecondaryFn)
        case "": key = "+"
        default: key = part
        }
    }
    guard let k = key, let code = keyCodes[k] ?? (k == "+" ? keyCodes["="] : nil) else { fail("unknown key in '\(combo)'") }
    if k == "+" { flags.insert(.maskShift) }
    for down in [true, false] {
        let e = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: down)
        e?.flags = flags
        post(e, pid)
        usleep(2000)
    }
}
func typeText(_ s: String, pid: pid_t? = nil) {
    var chunk: [UniChar] = []
    func flush() {
        guard !chunk.isEmpty else { return }
        for down in [true, false] {
            let e = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: down)
            e?.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: chunk)
            post(e, pid)
        }
        chunk = []; usleep(4000)
    }
    for ch in s {
        if ch == "\n" { flush(); pressKey("return", pid: pid); continue }
        if ch == "\t" { flush(); pressKey("tab", pid: pid); continue }
        chunk.append(contentsOf: Array(String(ch).utf16))
        if chunk.count >= 16 { flush() }
    }
    flush()
}

// MARK: fuzzy matching
func norm(_ s: String) -> String {
    var t = s.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
    t = t.replacingOccurrences(of: "…", with: "...").replacingOccurrences(of: "’", with: "'").replacingOccurrences(of: "‘", with: "'")
    t = t.replacingOccurrences(of: "\u{00A0}", with: " ")
    return t.trimmingCharacters(in: .whitespacesAndNewlines)
}
func tokens(_ s: String) -> [String] {
    norm(s).split(whereSeparator: { !$0.isLetter && !$0.isNumber }).map(String.init)
}
func lev(_ a: [Character], _ b: [Character]) -> Int {
    if a.isEmpty { return b.count }; if b.isEmpty { return a.count }
    var prev = Array(0...b.count), cur = [Int](repeating: 0, count: b.count + 1)
    for i in 1...a.count {
        cur[0] = i
        for j in 1...b.count { cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1)) }
        swap(&prev, &cur)
    }
    return prev[b.count]
}
/// 0 = no match, up to 100 = exact
func textScore(_ field: String, _ q: String, _ qTokens: [String]) -> Int {
    let f = norm(field)
    if f.isEmpty { return 0 }
    if f == q { return 100 }
    if f.hasPrefix(q) { return 85 - min(15, (f.count - q.count) / 4) }
    if f.contains(q) { return 70 - min(15, (f.count - q.count) / 6) }
    let ft = tokens(f)
    if !qTokens.isEmpty, qTokens.allSatisfy({ t in ft.contains(where: { $0.hasPrefix(t) || $0.contains(t) }) }) { return 55 }
    // fuzzy: typo tolerance for short labels
    if f.count <= 40, q.count >= 4 {
        let d = lev(Array(f), Array(q))
        let r = 1.0 - Double(d) / Double(max(f.count, q.count))
        if r >= 0.75 { return Int(30 + (r - 0.75) * 80) }
        for t in ft where t.count >= 4 && qTokens.count == 1 {
            let d2 = lev(Array(t), Array(q)); let r2 = 1.0 - Double(d2) / Double(max(t.count, q.count))
            if r2 >= 0.8 { return Int(30 + (r2 - 0.8) * 60) }
        }
    }
    return 0
}
let pressRoles: Set<String> = ["AXButton", "AXMenuItem", "AXMenuBarItem", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXMenuButton", "AXLink", "AXTextField", "AXSearchField", "AXTextArea", "AXComboBox", "AXTab", "AXDisclosureTriangle", "AXToolbar", "AXSegmentedControl", "AXSlider", "AXRow", "AXCell", "AXOutlineRow"]
let textRoles: Set<String> = ["AXTextField", "AXSearchField", "AXTextArea", "AXComboBox"]

struct Hit { var el: AXUIElement; var role: String; var title: String; var desc: String; var ident: String; var score: Int; var f: [Int]?; var inMenu: Bool }

let attrNames: [CFString] = [kAXRoleAttribute as CFString, kAXTitleAttribute as CFString, kAXDescriptionAttribute as CFString,
                             kAXValueAttribute as CFString, kAXHelpAttribute as CFString, kAXIdentifierAttribute as CFString,
                             kAXChildrenAttribute as CFString, kAXEnabledAttribute as CFString, kAXRoleDescriptionAttribute as CFString]
func multi(_ e: AXUIElement) -> [CFTypeRef?] {
    var vals: CFArray?
    guard AXUIElementCopyMultipleAttributeValues(e, attrNames as CFArray, AXCopyMultipleAttributeOptions(rawValue: 0), &vals) == .success,
          let arr = vals as? [Any] else { return [] }
    return arr.map { v in
        if CFGetTypeID(v as CFTypeRef) == AXValueGetTypeID(), let av = Optional(v as! AXValue), AXValueGetType(av) == .axError { return nil }
        return (v as CFTypeRef)
    }
}
func search(_ roots: [(AXUIElement, Bool)], _ query: String, role: String? = nil, limit: Int = 12000, budget: TimeInterval = 2.5, maxHits: Int = 8) -> [Hit] {
    let q = norm(query), qt = tokens(query)
    let wantRole = role.map { r in r.hasPrefix("AX") ? r : "AX" + r }
    var hits: [Hit] = []
    var seen = 0
    let end = Date().addingTimeInterval(budget)
    func walk(_ e: AXUIElement, _ d: Int, _ inMenu: Bool) {
        if seen > limit || d > 40 || Date() > end { return }
        seen += 1
        let v = multi(e)
        func s(_ i: Int) -> String? { v.count > i ? (v[i] as? String).flatMap { $0.isEmpty ? nil : $0 } : nil }
        let r = s(0) ?? ""
        let title = s(1) ?? "", desc = s(2) ?? "", ident = s(5) ?? ""
        let val = (v.count > 3 ? v[3] as? String : nil) ?? ""
        let help = s(4) ?? ""
        let rdesc = s(8) ?? ""
        var best = 0
        for (txt, w) in [(title, 100), (desc, 95), (ident, 85), (rdesc.isEmpty ? "" : rdesc, 0), (val.count > 120 ? "" : val, 55), (help, 45)] where w > 0 && !txt.isEmpty {
            let sc = textScore(txt, q, qt) * w / 100
            if sc > best { best = sc }
        }
        // a pressable element whose child StaticText has the label (common in custom UIs)
        if best > 0 {
            if pressRoles.contains(r) { best += 12 }
            if r == "AXStaticText" || r == "AXImage" || r == "AXGroup" { best -= 8 }
            if inMenu { best -= 4 }
            if v.count > 7, let en = v[7] as? Bool, !en { best -= 10 }
            if wantRole == nil || wantRole == r {
                hits.append(Hit(el: e, role: r, title: title.isEmpty ? (val.isEmpty ? desc : String(val.prefix(60))) : title, desc: desc, ident: ident, score: best, f: frame(e), inMenu: inMenu))
            }
        }
        let ch = (v.count > 6 ? v[6] as? [AXUIElement] : nil) ?? []
        for c in ch { walk(c, d + 1, inMenu || r == "AXMenuBar") }
    }
    for (root, m) in roots { walk(root, 0, m) }
    hits.sort { a, b in
        if a.score != b.score { return a.score > b.score }
        let aa = (a.f?[2] ?? 0) * (a.f?[3] ?? 0) > 0, bb = (b.f?[2] ?? 0) * (b.f?[3] ?? 0) > 0
        return aa && !bb
    }
    // dedupe identical frames+titles
    var uniq: [Hit] = []
    for h in hits where !uniq.contains(where: { $0.title == h.title && $0.role == h.role && $0.f == h.f }) { uniq.append(h); if uniq.count >= maxHits { break } }
    return uniq
}
func searchRoots(_ app: AXUIElement, menuToo: Bool = true) -> [(AXUIElement, Bool)] {
    var r: [(AXUIElement, Bool)] = windowsOf(app).map { ($0, false) }
    if menuToo, let bar = attr(app, kAXMenuBarAttribute) { r.append((bar as! AXUIElement, true)) }
    return r
}
func center(_ f: [Int]) -> CGPoint { CGPoint(x: f[0] + f[2] / 2, y: f[1] + f[3] / 2) }
func hitJSON(_ h: Hit) -> [String: Any] {
    var d: [String: Any] = ["role": h.role.replacingOccurrences(of: "AX", with: ""), "title": h.title, "frame": h.f ?? [], "score": h.score]
    if !h.desc.isEmpty && h.desc != h.title { d["desc"] = h.desc }
    if !h.ident.isEmpty { d["id"] = h.ident }
    if h.inMenu { d["menu"] = true }
    return d
}

func tree(_ e: AXUIElement, _ depth: Int, _ budget: inout Int) -> [String: Any] {
    budget -= 1
    var n: [String: Any] = ["r": (str(e, kAXRoleAttribute) ?? "?").replacingOccurrences(of: "AX", with: "")]
    if let t = str(e, kAXTitleAttribute) ?? str(e, kAXDescriptionAttribute) { n["t"] = t }
    else if let v = attr(e, kAXValueAttribute) as? String, !v.isEmpty { n["v"] = String(v.prefix(80)) }
    if let i = str(e, kAXIdentifierAttribute) { n["i"] = i }
    if let f = frame(e) { n["f"] = f }
    if depth > 0, budget > 0 {
        var c: [[String: Any]] = []
        for k in kids(e) where budget > 0 { c.append(tree(k, depth - 1, &budget)) }
        if !c.isEmpty { n["c"] = c }
    }
    return n
}

// MARK: app launching
func appPath(_ name: String) -> URL? {
    let ws = NSWorkspace.shared
    if let id = ws.urlForApplication(withBundleIdentifier: name) { return id }
    if let p = ws.fullPath(forApplication: name) { return URL(fileURLWithPath: p) }
    let n = norm(name)
    for dir in ["/Applications", "/System/Applications", "/System/Applications/Utilities", "/Applications/Utilities", "/System/Cryptexes/App/System/Applications", NSHomeDirectory() + "/Applications"] {
        if let items = try? FileManager.default.contentsOfDirectory(atPath: dir) {
            let apps = items.filter { $0.hasSuffix(".app") }
            if let m = apps.first(where: { norm(String($0.dropLast(4))) == n }) ?? apps.first(where: { norm($0).hasPrefix(n) }) ?? apps.first(where: { norm($0).contains(n) }) {
                return URL(fileURLWithPath: dir + "/" + m)
            }
        }
    }
    return nil
}
/// open via /usr/bin/open (works when NSWorkspace refuses, e.g. cryptex symlinks)
func shOpen(_ a: [String]) -> Bool {
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/open"); p.arguments = a
    p.standardError = FileHandle.nullDevice; p.standardOutput = FileHandle.nullDevice
    do { try p.run(); p.waitUntilExit(); return p.terminationStatus == 0 } catch { return false }
}
func launchApp(_ name: String, raise: Bool = false) -> String {
    let raise = raise || !useBG
    if let a = findRunning(name) {
        if raise { activate(a, force: true); _ = waitFront(a, 1.0) }
        return a.localizedName ?? name
    }
    guard let url = appPath(name) else {
        if shOpen((raise ? [] : ["-g"]) + ["-a", name]) { return name }
        fail("app not found: \(name)")
    }
    let sem = DispatchSemaphore(value: 0)
    var err: String?
    let cfg = NSWorkspace.OpenConfiguration(); cfg.activates = raise
    NSWorkspace.shared.openApplication(at: url, configuration: cfg) { _, e in err = e?.localizedDescription; sem.signal() }
    _ = sem.wait(timeout: .now() + 6)
    if err != nil {
        // NSWorkspace can refuse apps that `open` launches fine; retry the plain way, then by resolved path
        let g = raise ? [] : ["-g"]
        if !shOpen(g + ["-a", url.path]) && !shOpen(g + ["-a", name]) { fail(err!) }
    }
    let n = url.deletingPathExtension().lastPathComponent
    // wait briefly until it is running and frontmost
    let end = Date().addingTimeInterval(4)
    while Date() < end {
        if let a = findRunning(n) ?? findRunning(name) { if raise { activate(a, force: true); _ = waitFront(a, 1.0) }; break }
        usleep(60000)
    }
    return n
}

func frontInfo() -> [String: Any] {
    let a = runningApp(nil)
    var d: [String: Any] = ["app": a.localizedName ?? "?", "pid": Int(a.processIdentifier)]
    if AXIsProcessTrusted() {
        let e = AXUIElementCreateApplication(a.processIdentifier)
        AXUIElementSetMessagingTimeout(e, 0.4)
        if let w = windowsOf(e).first {
            d["title"] = str(w, kAXTitleAttribute) ?? ""
            if let f = frame(w) { d["frame"] = f }
            return d
        }
    }
    if let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]],
       let w = list.first(where: { ($0[kCGWindowOwnerPID as String] as? Int32) == a.processIdentifier && ($0[kCGWindowLayer as String] as? Int) == 0 }),
       let b = w[kCGWindowBounds as String] as? [String: CGFloat] {
        d["title"] = w[kCGWindowName as String] as? String ?? ""
        d["frame"] = [Int(b["X"] ?? 0), Int(b["Y"] ?? 0), Int(b["Width"] ?? 0), Int(b["Height"] ?? 0)]
    }
    if !AXIsProcessTrusted() { d["note"] = "NO_ACCESSIBILITY: title/frame may be missing" }
    return d
}

func normalizeMenu(_ s: String) -> String { norm(s).replacingOccurrences(of: "…", with: "...") }

// MARK: screen geometry (AX uses top-left origin on the primary screen)
func screenFor(_ rect: CGRect) -> NSScreen {
    let h = NSScreen.screens.first?.frame.height ?? 0
    var best: NSScreen = NSScreen.main ?? NSScreen.screens[0]
    var area: CGFloat = -1
    for s in NSScreen.screens {
        let f = s.frame
        let tl = CGRect(x: f.minX, y: h - f.maxY, width: f.width, height: f.height)
        let i = tl.intersection(rect)
        let a = i.isNull ? 0 : i.width * i.height
        if a > area { area = a; best = s }
    }
    return best
}
/// visible area (minus menu bar and Dock) of a screen, in AX top-left coordinates
func visibleTL(_ s: NSScreen) -> CGRect {
    let h = NSScreen.screens.first?.frame.height ?? 0
    let v = s.visibleFrame
    return CGRect(x: v.minX, y: h - v.maxY, width: v.width, height: v.height)
}

// MARK: screenshots (ScreenCaptureKit, no shelling out)
func writeImage(_ img: CGImage, _ path: String) -> Bool {
    let lower = path.lowercased()
    let type: CFString = (lower.hasSuffix(".jpg") || lower.hasSuffix(".jpeg")) ? UTType.jpeg.identifier as CFString : UTType.png.identifier as CFString
    guard let dst = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, type, 1, nil) else { return false }
    CGImageDestinationAddImage(dst, img, nil)
    return CGImageDestinationFinalize(dst)
}
func sckShot(path: String, pid: pid_t?, retina: Bool) -> (Bool, String, Int, Int) {
    var result: CGImage?, errMsg = ""
    let sem = DispatchSemaphore(value: 0)
    SCShareableContent.getExcludingDesktopWindows(false, onScreenWindowsOnly: true) { content, error in
        guard let content else { errMsg = error?.localizedDescription ?? "no shareable content"; sem.signal(); return }
        let conf = SCStreamConfiguration()
        conf.showsCursor = false
        let filter: SCContentFilter
        if let pid {
            let wins = content.windows.filter { $0.owningApplication?.processID == pid && $0.windowLayer == 0 && $0.frame.width > 40 }
            guard let w = wins.max(by: { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }) else {
                errMsg = "no window to capture"; sem.signal(); return
            }
            filter = SCContentFilter(desktopIndependentWindow: w)
            let sc = retina ? 2.0 : 1.0
            conf.width = Int(w.frame.width * sc); conf.height = Int(w.frame.height * sc)
        } else {
            let main = CGMainDisplayID()
            guard let d = content.displays.first(where: { $0.displayID == main }) ?? content.displays.first else { errMsg = "no display"; sem.signal(); return }
            filter = SCContentFilter(display: d, excludingWindows: [])
            let sc = retina ? 2.0 : 1.0
            conf.width = Int(Double(d.width) * sc); conf.height = Int(Double(d.height) * sc)
        }
        SCScreenshotManager.captureImage(contentFilter: filter, configuration: conf) { img, e in
            result = img; if img == nil { errMsg = e?.localizedDescription ?? "capture failed" }
            sem.signal()
        }
    }
    if sem.wait(timeout: .now() + 8) == .timedOut { return (false, "timeout", 0, 0) }
    guard let img = result else { return (false, errMsg, 0, 0) }
    return (writeImage(img, path), "", img.width, img.height)
}

// MARK: commands
switch cmd {
case "help", "-h", "--help":
    ok(["usage": usage])

case "click":
    let right = flag("--right"), dbl = flag("--double")
    guard args.count >= 2 else { fail("usage: click X Y [--right|--double]") }
    requireMouse("click")
    click(CGPoint(x: num(args[0], "X"), y: num(args[1], "Y")), right: right, double: dbl)
    ok()
case "double":
    guard args.count >= 2 else { fail("usage: double X Y") }
    requireMouse("double-click")
    click(CGPoint(x: num(args[0], "X"), y: num(args[1], "Y")), double: true); ok()
case "right":
    guard args.count >= 2 else { fail("usage: right X Y") }
    requireMouse("right-click")
    click(CGPoint(x: num(args[0], "X"), y: num(args[1], "Y")), right: true); ok()
case "move":
    guard args.count >= 2 else { fail("usage: move X Y") }
    requireMouse("moving the cursor")
    mouse(.mouseMoved, CGPoint(x: num(args[0], "X"), y: num(args[1], "Y"))); ok()
case "type":
    let tgt = opt("--app")
    guard !args.isEmpty else { fail("usage: type \"text\" [--app Name]  (--app sends the text to that app without raising it)") }
    if tgt == nil { requireMouse("typing into the front app") }
    typeText(args.joined(separator: " "), pid: tgt.map { runningApp($0).processIdentifier }); ok()
case "key":
    let tgt = opt("--app")
    guard args.first != nil else { fail("usage: key cmd+shift+4 [--app Name]  (--app sends the key to that app without raising it)") }
    if tgt == nil { requireMouse("a keystroke to the front app") }
    let tpid = tgt.map { runningApp($0).processIdentifier }
    for part in args { pressKey(part, pid: tpid); if args.count > 1 { usleep(40000) } }
    ok()
case "scroll":
    guard args.count >= 2 else { fail("usage: scroll DX DY") }
    requireMouse("scrolling")
    let e = CGEvent(scrollWheelEvent2Source: src, units: .pixel, wheelCount: 2, wheel1: Int32(num(args[1], "DY")), wheel2: Int32(num(args[0], "DX")), wheel3: 0)
    e?.post(tap: .cghidEventTap); ok()

case "open-app":
    guard let name = args.first else { fail("usage: open-app Name") }
    let n = launchApp(name)
    var d: [String: Any] = ["app": n]
    if let a = findRunning(n) { d["front"] = NSWorkspace.shared.frontmostApplication?.processIdentifier == a.processIdentifier }
    ok(d)
case "focus":
    guard let name = args.first else { fail("usage: focus Name") }
    if let a = findRunning(name) {
        activate(a, force: true)  // focus is an explicit request to raise
        ok(["app": a.localizedName ?? name, "front": waitFront(a, 1.2)])
    }
    let n = launchApp(name, raise: true)
    ok(["app": n, "launched": true])
case "open-url":
    let app = opt("--app")
    guard let s = args.first, let u = URL(string: s) ?? URL(string: s.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "") else { fail("usage: open-url URL [--app Name]") }
    if let app, let appURL = appPath(app) {
        let sem = DispatchSemaphore(value: 0)
        var err: String?
        let cfg = NSWorkspace.OpenConfiguration(); cfg.activates = !useBG
        NSWorkspace.shared.open([u], withApplicationAt: appURL, configuration: cfg) { _, e in err = e?.localizedDescription; sem.signal() }
        _ = sem.wait(timeout: .now() + 6)
        if err != nil && !shOpen((useBG ? ["-g"] : []) + ["-a", appURL.path, u.absoluteString]) { fail(err!) }
    } else if useBG { _ = shOpen(["-g", u.absoluteString]) }
    else if !NSWorkspace.shared.open(u) { _ = shOpen([u.absoluteString]) }
    ok(["url": u.absoluteString])
case "open-file":
    let app = opt("--app")
    guard let p = args.first else { fail("usage: open-file PATH [--app Name]") }
    let path = (p as NSString).expandingTildeInPath
    guard FileManager.default.fileExists(atPath: path) else { fail("no such file: \(path)") }
    let g = useBG ? ["-g"] : []
    if let app { if !shOpen(g + ["-a", app, path]) { fail("cannot open with \(app)") } } else if !shOpen(g + [path]) { fail("cannot open \(path)") }
    ok(["path": path])
case "quit":
    guard let name = args.first else { fail("usage: quit Name") }
    guard let a = findRunning(name) else { ok(["note": "not running"]) }
    a.terminate()
    var end = Date().addingTimeInterval(1.2)
    while Date() < end && alive(a) { usleep(80000) }
    if alive(a), let bid = a.bundleIdentifier {
        // NSRunningApplication.terminate() is ignored by some apps from a CLI: ask with a real quit Apple Event
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        p.arguments = ["-e", "tell application id \"\(bid)\" to quit"]
        p.standardError = FileHandle.nullDevice; p.standardOutput = FileHandle.nullDevice
        try? p.run(); p.waitUntilExit()
        end = Date().addingTimeInterval(2.0)
        while Date() < end && alive(a) { usleep(80000) }
    }
    // an app with unsaved work shows a save sheet instead of quitting: report it so Alfred can choose "Don't Save"/"Cancel" with press
    ok(["app": a.localizedName ?? name, "quit": !alive(a), "note": !alive(a) ? "" : "still running: probably asking to save. Use press \"Don't Save\" (only if the work is disposable) or press \"Cancel\"."])
case "apps":
    let list = NSWorkspace.shared.runningApplications.filter { $0.activationPolicy == .regular }.map { ["name": $0.localizedName ?? "?", "pid": Int($0.processIdentifier), "front": $0.isActive] as [String: Any] }
    ok(["apps": list])

case "front":
    out(frontInfo().merging(["ok": true]) { a, _ in a })

case "windows":
    let (app, a) = axApp(opt("--app"), timeout: 0.6)
    var ws: [[String: Any]] = []
    for w in windowsOf(app) { ws.append(["title": str(w, kAXTitleAttribute) ?? "", "frame": frame(w) ?? [], "min": (attr(w, kAXMinimizedAttribute) as? Bool) ?? false]) }
    ok(["app": a.localizedName ?? "?", "windows": ws])

case "window":
    guard args.count >= 2 else { fail("usage: window Name X Y W H | window Name left|right|full|center|top-left|…") }
    let (app, a) = axApp(args[0])
    guard let w = windowsOf(app).first else { fail("no window for \(args[0])") }
    if (attr(w, kAXMinimizedAttribute) as? Bool) == true { AXUIElementSetAttributeValue(w, kAXMinimizedAttribute as CFString, kCFBooleanFalse) }
    var target: CGRect
    if args.count >= 5 {
        target = CGRect(x: num(args[1], "X"), y: num(args[2], "Y"), width: num(args[3], "W"), height: num(args[4], "H"))
    } else {
        let cur = frame(w).map { CGRect(x: $0[0], y: $0[1], width: $0[2], height: $0[3]) } ?? CGRect(x: 0, y: 0, width: 800, height: 600)
        let v = visibleTL(screenFor(cur))
        let hw = (v.width / 2).rounded(), hh = (v.height / 2).rounded()
        switch args[1].lowercased() {
        case "left", "left-half": target = CGRect(x: v.minX, y: v.minY, width: hw, height: v.height)
        case "right", "right-half": target = CGRect(x: v.minX + hw, y: v.minY, width: hw, height: v.height)
        case "top", "top-half": target = CGRect(x: v.minX, y: v.minY, width: v.width, height: hh)
        case "bottom", "bottom-half": target = CGRect(x: v.minX, y: v.minY + hh, width: v.width, height: hh)
        case "top-left": target = CGRect(x: v.minX, y: v.minY, width: hw, height: hh)
        case "top-right": target = CGRect(x: v.minX + hw, y: v.minY, width: hw, height: hh)
        case "bottom-left": target = CGRect(x: v.minX, y: v.minY + hh, width: hw, height: hh)
        case "bottom-right": target = CGRect(x: v.minX + hw, y: v.minY + hh, width: hw, height: hh)
        case "full", "max", "maximize", "fill": target = v
        case "center", "centre": target = CGRect(x: v.minX + v.width * 0.15, y: v.minY + v.height * 0.1, width: v.width * 0.7, height: v.height * 0.8)
        default: fail("unknown position '\(args[1])' (left right top bottom top-left top-right bottom-left bottom-right full center)")
        }
    }
    var p = target.origin, s = target.size
    // size first, then position, then size again (some apps clamp at screen edges)
    AXUIElementSetAttributeValue(w, kAXSizeAttribute as CFString, AXValueCreate(.cgSize, &s)!)
    AXUIElementSetAttributeValue(w, kAXPositionAttribute as CFString, AXValueCreate(.cgPoint, &p)!)
    AXUIElementSetAttributeValue(w, kAXSizeAttribute as CFString, AXValueCreate(.cgSize, &s)!)
    activate(a)
    ok(["frame": frame(w) ?? [], "wanted": [Int(target.minX), Int(target.minY), Int(target.width), Int(target.height)]])

case "find", "press":
    let name = opt("--app")
    let role = opt("--role")
    let index = Int(opt("--index") ?? "0") ?? 0
    let forceClick = flag("--click")
    guard let q = args.first else { fail("usage: \(cmd) \"title\" [--app Name] [--role Button] [--index N]") }
    let (app, a) = axApp(name)
    // the target app must be able to answer: bring it forward for a press so windows exist
    var hits = search(searchRoots(app), q, role: role)
    if hits.isEmpty, name != nil, cmd == "press" { activate(a); usleep(200000); hits = search(searchRoots(app), q, role: role) }
    guard !hits.isEmpty else {
        var near: [String] = []
        let all = windowsOf(app)
        if let w = all.first { var b = 60; let t = tree(w, 3, &b); if let c = t["c"] as? [[String: Any]] { near = c.compactMap { $0["t"] as? String }.prefix(8).map { $0 } } }
        fail("not found: \(q)", ["app": a.localizedName ?? "?", "hint": "try another wording, alfred-ctl ui --app \"\(a.localizedName ?? "")\" --depth 5, or alfred-ctl menu", "seen": near])
    }
    let list = hits.map(hitJSON)
    if cmd == "find" { ok(["match": list[0], "matches": list, "app": a.localizedName ?? "?"]) }
    let target = hits[min(index, hits.count - 1)]
    let acts = actions(target.el)
    if !forceClick {
        if textRoles.contains(target.role) {
            // focus the field instead of clicking into it
            if AXUIElementSetAttributeValue(target.el, kAXFocusedAttribute as CFString, kCFBooleanTrue) == .success {
                ok(["method": "AXFocus", "title": target.title, "role": target.role])
            }
        } else if acts.contains(kAXPressAction) {
            if AXUIElementPerformAction(target.el, kAXPressAction as CFString) == .success { ok(["method": "AXPress", "title": target.title, "role": target.role]) }
        } else if acts.contains("AXPick"), AXUIElementPerformAction(target.el, "AXPick" as CFString) == .success {
            ok(["method": "AXPick", "title": target.title])
        } else if acts.contains(kAXConfirmAction), AXUIElementPerformAction(target.el, kAXConfirmAction as CFString) == .success {
            ok(["method": "AXConfirm", "title": target.title])
        }
    }
    guard let f = target.f, f[2] > 0, f[3] > 0 else { fail("found but cannot press or locate: \(q)", ["match": hitJSON(target)]) }
    if target.inMenu { fail("menu item is hidden and cannot be pressed: use alfred-ctl menu \"…\"", ["match": hitJSON(target)]) }
    requireMouse("pressing \"\(target.title)\" (no AX action available)")
    activate(a); usleep(60000)
    click(center(f))
    ok(["method": "click", "title": target.title, "at": [Int(center(f).x), Int(center(f).y)]])

case "fill":
    let name = opt("--app")
    guard args.count >= 2 else { fail("usage: fill \"field title\" \"text\" [--app Name]") }
    let (app, a) = axApp(name)
    let hits = search(searchRoots(app, menuToo: false), args[0]).filter { textRoles.contains($0.role) }
    guard let t = hits.first else { fail("text field not found: \(args[0])") }
    AXUIElementSetAttributeValue(t.el, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    if AXUIElementSetAttributeValue(t.el, kAXValueAttribute as CFString, args[1] as CFString) != .success {
        requireMouse("filling \"\(t.title)\" (AX value not settable)")
        activate(a)
        if let f = t.f, f[2] > 0 { click(center(f)); usleep(80000); pressKey("cmd+a"); typeText(args[1]) } else { fail("cannot set field") }
        ok(["method": "type", "title": t.title])
    }
    ok(["method": "AXValue", "title": t.title])

case "wait":
    let name = opt("--app")
    let timeout = Double(opt("--timeout") ?? "5") ?? 5
    guard let q = args.first else { fail("usage: wait \"title\" [--app Name] [--timeout 5]") }
    let (app, a) = axApp(name)
    let end = Date().addingTimeInterval(timeout)
    let t0 = Date()
    repeat {
        let hits = search(searchRoots(app), q, budget: 1.0, maxHits: 3)
        if let h = hits.first, h.score >= 50 { ok(["match": hitJSON(h), "waited": Int(Date().timeIntervalSince(t0) * 1000)]) }
        usleep(150000)
    } while Date() < end
    fail("timeout waiting for: \(q)", ["app": a.localizedName ?? "?"])

case "ui":
    let name = opt("--app")
    let depth = Int(opt("--depth") ?? "4") ?? 4
    let (app, a) = axApp(name)
    var budget = 600
    var wins: [[String: Any]] = []
    for w in windowsOf(app).prefix(1) { wins.append(tree(w, depth, &budget)) }
    ok(["app": a.localizedName ?? "?", "windows": wins, "truncated": budget <= 0])

case "screenshot":
    let win = flag("--window"), retina = flag("--retina")
    let appName = opt("--app")
    guard let path = args.first else { fail("usage: screenshot PATH [--window] [--app Name] [--retina]") }
    var pid: pid_t?
    if win || appName != nil { pid = runningApp(appName).processIdentifier }
    let t0 = Date()
    let (good, err, w, h) = sckShot(path: path, pid: pid, retina: retina)
    if good, FileManager.default.fileExists(atPath: path) { ok(["path": path, "w": w, "h": h, "ms": Int(Date().timeIntervalSince(t0) * 1000), "via": "ScreenCaptureKit", "note": retina ? "pixels = 2x points" : "pixels = screen points, so image x,y can be clicked directly"]) }
    // fallback: the system tool
    var a = ["-x", path]
    if let pid, let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]],
       let wn = list.first(where: { ($0[kCGWindowOwnerPID as String] as? Int32) == pid && ($0[kCGWindowLayer as String] as? Int) == 0 }),
       let wid = wn[kCGWindowNumber as String] as? CGWindowID { a = ["-x", "-o", "-l", String(wid), path] }
    let proc = Process(); proc.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture"); proc.arguments = a
    try? proc.run(); proc.waitUntilExit()
    guard FileManager.default.fileExists(atPath: path) else {
        fail("NO_SCREEN_RECORDING: screenshot failed (\(err)). the user must enable Screen Recording for Alfred in System Settings > Privacy & Security > Screen & System Audio Recording.")
    }
    ok(["path": path, "via": "screencapture", "note": "fallback used: \(err)"])

case "point":
    guard args.count >= 3 else { fail("usage: point X Y \"label\" [\"hint\"] [--step N --of M]") }
    let step = opt("--step"), of = opt("--of")
    var ev: [String: Any] = ["t": Date().timeIntervalSince1970, "type": "point", "x": num(args[0], "X"), "y": num(args[1], "Y"), "label": args[2]]
    if args.count > 3 { ev["hint"] = args[3] }
    if let step, let n = Int(step) { ev["step"] = n }
    if let of, let n = Int(of) { ev["of"] = n }
    let dir = alfredHome + "/data/ui"
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    let path = dir + "/events.jsonl"
    guard let data = try? JSONSerialization.data(withJSONObject: ev), let h = FileHandle(forWritingAtPath: path) ?? {
        FileManager.default.createFile(atPath: path, contents: nil); return FileHandle(forWritingAtPath: path) }() else { fail("cannot write events.jsonl") }
    h.seekToEndOfFile(); h.write(data); h.write(Data([10])); try? h.close()
    ok()

case "menu", "menus":
    let name = opt("--app")
    let (app, a) = axApp(name)
    guard let bar = attr(app, kAXMenuBarAttribute) else { fail("app has no menu bar (is it frontmost / has windows?)", ["app": a.localizedName ?? "?"]) }
    func titleN(_ e: AXUIElement) -> String { normalizeMenu(str(e, kAXTitleAttribute) ?? "") }
    func subItems(_ item: AXUIElement) -> [AXUIElement] {
        if let m = kids(item).first(where: { str($0, kAXRoleAttribute) == "AXMenu" }) { return kids(m) }
        return []
    }
    if cmd == "menus" {
        let tops = kids(bar as! AXUIElement)
        if let which = args.first {
            guard let t = tops.first(where: { titleN($0).contains(normalizeMenu(which)) }) else { fail("no top menu \(which)") }
            let items = subItems(t).compactMap { str($0, kAXTitleAttribute) }
            ok(["menu": str(t, kAXTitleAttribute) ?? which, "items": items])
        }
        ok(["menus": tops.compactMap { str($0, kAXTitleAttribute) }])
    }
    guard let pathStr = args.first else { fail("usage: menu \"File>Export>File…\" [--app Name]") }
    var parts = pathStr.split(separator: ">").map { normalizeMenu(String($0).trimmingCharacters(in: .whitespaces)) }
    let tops = kids(bar as! AXUIElement)
    // tolerate a leading app name ("Safari>File>New Window"): drop it when the app menu has no item with the next name
    if parts.count > 1, let an = a.localizedName, normalizeMenu(an) == parts[0] || parts[0] == "app" {
        let appMenu = tops.first(where: { titleN($0) == parts[0] }) ?? tops.dropFirst().first
        let hasNext = appMenu.map { subItems($0).contains(where: { titleN($0) == parts[1] }) } ?? false
        if !hasNext { parts.removeFirst() }
    }
    func pickItem(_ items: [AXUIElement], _ part: String) -> AXUIElement? {
        let cand = items.filter { str($0, kAXRoleAttribute) != "AXMenuSeparator" && !titleN($0).isEmpty }
        return cand.first(where: { titleN($0) == part })
            ?? cand.first(where: { titleN($0).hasPrefix(part) })
            ?? cand.first(where: { titleN($0).contains(part) })
            ?? cand.map({ ($0, textScore(titleN($0), part, tokens(part))) }).filter({ $0.1 >= 30 }).max(by: { $0.1 < $1.1 })?.0
    }
    var cur: AXUIElement = bar as! AXUIElement
    var items = tops
    var leaf: AXUIElement?
    for (i, part) in parts.enumerated() {
        guard let item = pickItem(items, part) else {
            // last resort: look the leaf up anywhere in the menu bar
            let found = search([(bar as! AXUIElement, true)], parts.last ?? part, role: "MenuItem", maxHits: 3)
            if let h = found.first, h.score >= 70 { leaf = h.el; break }
            fail("menu item not found: \(part)", ["options": items.compactMap { str($0, kAXTitleAttribute) }.filter { !$0.isEmpty }.prefix(25).map { $0 }])
        }
        cur = item
        if i == parts.count - 1 { leaf = item; break }
        var sub = subItems(item)
        if sub.isEmpty { // lazily-built menu: open it once so the items exist
            _ = AXUIElementPerformAction(item, kAXPressAction as CFString); usleep(150000); sub = subItems(item)
        }
        items = sub
    }
    guard let target = leaf else { fail("menu item not found") }
    if (attr(target, kAXEnabledAttribute) as? Bool) == false { fail("menu item is disabled: \(pathStr)", ["title": str(target, kAXTitleAttribute) ?? ""]) }
    activate(a)
    if AXUIElementPerformAction(target, kAXPressAction as CFString) != .success { fail("cannot press menu item: \(pathStr)") }
    ok(["menu": pathStr, "title": str(target, kAXTitleAttribute) ?? ""])

case "do":
    // run steps sequentially: each step is a quoted command line like  "key cmd+n"  or  "type \"hello world\""
    func words(_ line: String) -> [String] {
        var out: [String] = [], cur = "", q: Character? = nil, has = false
        var it = Array(line)
        var i = 0
        while i < it.count {
            let c = it[i]
            if let qq = q {
                if c == "\\", i + 1 < it.count, it[i + 1] == qq || it[i + 1] == "\\" { cur.append(it[i + 1]); i += 2; continue }
                if c == qq { q = nil } else { cur.append(c) }
            } else if c == "\"" || c == "'" { q = c; has = true }
            else if c == " " { if !cur.isEmpty || has { out.append(cur); cur = ""; has = false } }
            else { cur.append(c) }
            i += 1
        }
        if !cur.isEmpty || has { out.append(cur) }
        it = []
        return out
    }
    guard !args.isEmpty else { fail("usage: do \"open-app TextEdit\" \"key cmd+n\" \"sleep 0.5\" \"type hi\" \"front\"") }
    let me = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL.path
    var results: [[String: Any]] = []
    var allOK = true
    for step in args {
        let w = words(step)
        guard let c0 = w.first else { continue }
        if c0 == "sleep" { usleep(UInt32((Double(w.dropFirst().first ?? "0.5") ?? 0.5) * 1_000_000)); continue }
        let p = Process(); p.executableURL = URL(fileURLWithPath: me); p.arguments = w
        if !useBG { var env = ProcessInfo.processInfo.environment; env["ALFRED_BG"] = "0"; p.environment = env }
        let pipe = Pipe(); p.standardOutput = pipe
        do { try p.run() } catch { results.append(["step": step, "ok": false, "error": "spawn failed"]); allOK = false; break }
        let data = pipe.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
        var r = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? ["ok": p.terminationStatus == 0]
        r["step"] = step
        results.append(r)
        if (r["ok"] as? Bool) != true { allOK = false; break }
    }
    out(["ok": allOK, "steps": results], code: allOK ? 0 : 1)

case "doctor":
    var d: [String: Any] = ["accessibility": AXIsProcessTrusted(), "screen_recording": CGPreflightScreenCaptureAccess(), "pid": Int(getpid()), "ppid": Int(getppid())]
    if let parent = NSRunningApplication(processIdentifier: getppid()) { d["parent"] = parent.localizedName ?? "?" }
    if !AXIsProcessTrusted() { d["fix"] = "System Settings > Privacy & Security > Accessibility > enable Alfred" }
    if !CGPreflightScreenCaptureAccess() { d["fix_screen"] = "System Settings > Privacy & Security > Screen & System Audio Recording > enable Alfred" }
    ok(d)

default:
    fail("unknown command '\(cmd)'. Run: alfred-ctl help")
}
