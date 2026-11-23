"""Голограммы прямо на экране Mac — поверх программ, без окна и рамок (stage.html).

Слой прозрачный и пропускает мышь насквозь: можно работать, пока голограмма плавает над окнами.
Alfred кладёт спецификацию в data/holo-<пользователь>.json (через jholo.py), этот модуль её показывает.
"""
import json
import os
import time

from AppKit import NSBackingStoreBuffered, NSColor, NSMakeRect, NSPanel, NSScreen
from Foundation import NSURL

BORDERLESS, NONACTIVATING_PANEL = 0, 1 << 7
JOIN_ALL_SPACES, STATIONARY, FULLSCREEN_AUX, IGNORES_CYCLE = 1 << 0, 1 << 4, 1 << 8, 1 << 6
LEVEL = 3  # над обычными окнами, на одном уровне с лицом Alfred


class HoloStage:
    def __init__(self, html_path, spec_path):
        from WebKit import WKWebView, WKWebViewConfiguration
        self.spec_path = spec_path
        fr = NSScreen.mainScreen().frame()
        w = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            fr, BORDERLESS | NONACTIVATING_PANEL, NSBackingStoreBuffered, False)
        w.setOpaque_(False)
        w.setBackgroundColor_(NSColor.clearColor())
        w.setHasShadow_(False)
        w.setLevel_(LEVEL)
        w.setIgnoresMouseEvents_(True)  # клики проходят сквозь голограмму к вашим окнам
        w.setCollectionBehavior_(JOIN_ALL_SPACES | STATIONARY | FULLSCREEN_AUX | IGNORES_CYCLE)
        w.setHidesOnDeactivate_(False)
        conf = WKWebViewConfiguration.alloc().init()
        try:
            conf.preferences().setValue_forKey_(True, "allowFileAccessFromFileURLs")
        except Exception:
            pass
        wv = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, fr.size.width, fr.size.height), conf)
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
        self.hide_at = None     # убрать окно после анимации растворения
        self.expire_at = None   # голограмма сама гаснет через duration секунд
        self.spec_id = None
        self.mtime = None
        self.on_show = None
        try:  # старую голограмму из прошлого запуска не показываем
            self.mtime = os.path.getmtime(spec_path)
            self.spec_id = json.loads(open(spec_path, encoding="utf-8").read()).get("id")
        except Exception:
            pass

    def _js(self, code):
        try:
            self.wv.evaluateJavaScript_completionHandler_(code, None)
        except Exception:
            pass

    def show(self, spec):
        fr = (self.w.screen() or NSScreen.mainScreen()).frame()
        if not self.visible:
            self.w.setFrame_display_(fr, False)
        self._js(f"window.holo&&holo.show({json.dumps(spec, ensure_ascii=False)});")
        self.w.orderFrontRegardless()
        self.visible, self.hide_at = True, None
        self.expire_at = time.monotonic() + float(spec.get("duration") or 180)
        if self.on_show:
            self.on_show()

    def hide(self):
        if self.visible and self.hide_at is None:
            self._js("window.holo&&holo.hide();")
            self.hide_at = time.monotonic() + 1.6
        self.expire_at = None

    def tick(self):
        """Вызывается из таймера в главном потоке (~4 раза в секунду)."""
        try:
            mt = os.path.getmtime(self.spec_path)
        except OSError:
            mt = None
        if mt and mt != self.mtime:
            self.mtime = mt
            try:
                spec = json.loads(open(self.spec_path, encoding="utf-8").read())
            except Exception:
                spec = None
            if spec and spec.get("id") != self.spec_id:
                self.spec_id = spec.get("id")
                if spec.get("hide"):
                    self.hide()
                else:
                    self.show(spec)
        now = time.monotonic()
        if self.expire_at and now >= self.expire_at:
            self.hide()
        if self.hide_at and now >= self.hide_at:
            self.w.orderOut_(None)
            self.visible, self.hide_at = False, None
