"""The silent-mode answer card: a glowing glass card at the top right, above every window
(full-screen apps too), click-through so it never gets in the way. It dissolves after enough time to read it.
Main thread only (menubar's timer calls tick()).
"""
import json
import os
import time

from AppKit import NSBackingStoreBuffered, NSColor, NSMakeRect, NSPanel, NSScreen
from Foundation import NSURL

BORDERLESS, NONACTIVATING_PANEL = 0, 1 << 7
STATUS_LEVEL = 25  # above normal and floating windows
JOIN_ALL_SPACES, STATIONARY, FULLSCREEN_AUX = 1 << 0, 1 << 4, 1 << 8
W = 460
DISSOLVE = 1.3


class Card:
    def __init__(self, html_path):
        from WebKit import WKWebView, WKWebViewConfiguration
        scr = NSScreen.mainScreen().visibleFrame()
        h = int(scr.size.height * 0.75)
        x = scr.origin.x + scr.size.width - W - 8
        y = scr.origin.y + scr.size.height - h - 4
        w = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, W, h), BORDERLESS | NONACTIVATING_PANEL, NSBackingStoreBuffered, False)
        w.setOpaque_(False)
        w.setBackgroundColor_(NSColor.clearColor())
        w.setHasShadow_(False)
        w.setLevel_(STATUS_LEVEL)
        w.setCollectionBehavior_(JOIN_ALL_SPACES | STATIONARY | FULLSCREEN_AUX)
        w.setHidesOnDeactivate_(False)
        w.setIgnoresMouseEvents_(True)  # click-through: never blocks what's underneath
        conf = WKWebViewConfiguration.alloc().init()
        wv = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, W, h), conf)
        try:
            wv.setValue_forKey_(False, "drawsBackground")
        except Exception:
            pass
        wv.setAutoresizingMask_(18)
        url = NSURL.fileURLWithPath_(os.path.abspath(html_path))
        wv.loadFileURL_allowingReadAccessToURL_(url, url.URLByDeletingLastPathComponent())
        w.setContentView_(wv)
        self.w, self.wv = w, wv
        self.visible = False
        self.hide_at = None
        self.dissolving = False
        self.chars = 0

    def _js(self, code):
        try:
            self.wv.evaluateJavaScript_completionHandler_(code, None)
        except Exception:
            pass

    def show(self, kind, text):
        now = time.time()
        if not self.visible or self.dissolving:
            self.chars = 0
            self._js("reset()")
            self.w.orderFrontRegardless()
            self.visible, self.dissolving = True, False
        self._js(f"addText({json.dumps(kind)}, {json.dumps(text)})")
        self.chars += len(text)
        # ~15 characters a second of reading, at least 6 s, at most 60 s, counted from the newest piece
        self.hide_at = now + min(60.0, max(6.0, 3.0 + self.chars / 15.0)) + DISSOLVE

    def dismiss(self):
        if self.visible and not self.dissolving:
            self.hide_at = time.time() + DISSOLVE

    def tick(self):
        if not self.visible or self.hide_at is None:
            return
        now = time.time()
        if not self.dissolving and now >= self.hide_at - DISSOLVE:
            self.dissolving = True
            self._js("dissolve()")
        if now >= self.hide_at:
            self.w.orderOut_(None)
            self.visible, self.dissolving, self.hide_at = False, False, None
