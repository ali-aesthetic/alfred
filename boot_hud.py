#!/usr/bin/env python3
"""Full-screen, transparent, click-through boot HUD for the wake-up protocol. Exits by itself."""
import json
import os
import sys

from AppKit import NSApplication, NSBackingStoreBuffered, NSColor, NSMakeRect, NSPanel, NSScreen, NSApplicationActivationPolicyAccessory
from Foundation import NSURL, NSTimer, NSObject

HOME = os.path.dirname(os.path.abspath(__file__))
args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
secs = float(args.get("seconds", 11))


class Quit(NSObject):
    def fire_(self, t):
        NSApplication.sharedApplication().terminate_(None)


app = NSApplication.sharedApplication()
app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
from WebKit import WKWebView, WKWebViewConfiguration  # noqa: E402
fr = NSScreen.mainScreen().frame()
w = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(fr, 0 | (1 << 7), NSBackingStoreBuffered, False)
w.setOpaque_(False)
w.setBackgroundColor_(NSColor.clearColor())
w.setHasShadow_(False)
w.setLevel_(25)
w.setIgnoresMouseEvents_(True)
w.setCollectionBehavior_((1 << 0) | (1 << 4) | (1 << 8))
conf = WKWebViewConfiguration.alloc().init()
try:
    conf.setMediaTypesRequiringUserActionForPlayback_(0)  # let the core film play by itself
except Exception:
    pass
wv = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, fr.size.width, fr.size.height), conf)
wv.setValue_forKey_(False, "drawsBackground")
url = NSURL.fileURLWithPath_(os.path.join(HOME, "boot.html"))
q = "lines=" + __import__("urllib.parse").parse.quote(json.dumps(args.get("lines", []))) + f"&secs={secs}"
wv.loadFileURL_allowingReadAccessToURL_(NSURL.URLWithString_(url.absoluteString() + "?" + q), url.URLByDeletingLastPathComponent())
w.setContentView_(wv)
w.orderFrontRegardless()
q_ = Quit.alloc().init()
NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(secs + 1.5, q_, "fire:", None, False)
app.run()
