"""Голограмма Alfred: прозрачное окно с 3D-лицом (robot.html) и голографическими панелями.

Появляется эффектно, когда зовёте «Alfred», и испаряется по «стоп» / в конце разговора —
в остальное время на экране её нет и она не мешает окнам.
Когда Alfred показывает таблицу, график, картинку или видео, окно раздвигается влево
и панели вылетают рядом с лицом.

Мышь по лицу: перетащить — переместить; клик — позвать Alfred; двойной клик — показать окно Терминала.
"""
import json
import os
import time

from AppKit import (NSBackingStoreBuffered, NSColor, NSEvent, NSMakeRect, NSPanel, NSScreen, NSView)
from Foundation import NSURL

BORDERLESS = 0
NONACTIVATING_PANEL = 1 << 7
FLOATING_LEVEL = 3
JOIN_ALL_SPACES, STATIONARY, FULLSCREEN_AUX = 1 << 0, 1 << 4, 1 << 8
PANEL_W, PANEL_H = 560, 600   # область панелей слева от лица


class _Overlay(NSView):
    """Прозрачный слой поверх лица: перетаскивание и клики."""

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        self._down = NSEvent.mouseLocation()
        self._orig = self.window().frame().origin
        self._moved = False
        if event.clickCount() == 2:
            cb = getattr(self, "on_double", None)
            if cb:
                cb()

    def mouseDragged_(self, event):
        p = NSEvent.mouseLocation()
        dx, dy = p.x - self._down.x, p.y - self._down.y
        if abs(dx) + abs(dy) > 3:
            self._moved = True
        self.window().setFrameOrigin_((self._orig.x + dx, self._orig.y + dy))

    def mouseUp_(self, event):
        if not getattr(self, "_moved", False) and event.clickCount() == 1:
            cb = getattr(self, "on_click", None)
            if cb:
                cb()


class Hologram:
    def __init__(self, html_path, size=280, on_click=None, on_double=None):
        from WebKit import WKWebView, WKWebViewConfiguration
        self.size = size
        scr = NSScreen.mainScreen().visibleFrame()
        x = scr.origin.x + scr.size.width - size - 18
        y = scr.origin.y + 18
        w = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, size, size), BORDERLESS | NONACTIVATING_PANEL, NSBackingStoreBuffered, False)
        w.setOpaque_(False)
        w.setBackgroundColor_(NSColor.clearColor())
        w.setHasShadow_(False)
        w.setLevel_(FLOATING_LEVEL)
        w.setCollectionBehavior_(JOIN_ALL_SPACES | STATIONARY | FULLSCREEN_AUX)
        w.setHidesOnDeactivate_(False)
        w.setFloatingPanel_(True)
        w.setBecomesKeyOnlyIfNeeded_(True)
        w.setFrameAutosaveName_("AlfredHologram")  # macOS запомнит, куда вы его перетащили
        f = w.frame()
        if f.size.width != size or f.size.height != size:  # после сбоя могло запомниться раздвинутым
            w.setFrame_display_(NSMakeRect(f.origin.x + f.size.width - size, f.origin.y, size, size), False)

        conf = WKWebViewConfiguration.alloc().init()
        try:
            conf.setMediaTypesRequiringUserActionForPlayback_(0)  # let the core film play by itself
        except Exception:
            pass
        try:
            conf.preferences().setValue_forKey_(True, "allowFileAccessFromFileURLs")
        except Exception:
            pass
        wv = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, size, size), conf)
        try:
            wv.setValue_forKey_(False, "drawsBackground")
        except Exception:
            pass
        url = NSURL.fileURLWithPath_(os.path.abspath(html_path))
        # доступ на чтение ко всему диску — чтобы показывать на панелях фото и видео сэра из любых папок
        wv.loadFileURL_allowingReadAccessToURL_(url, NSURL.fileURLWithPath_("/"))

        box = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, size, size))
        wv.setAutoresizingMask_(18)  # ширина и высота тянутся
        box.addSubview_(wv)
        ov = _Overlay.alloc().initWithFrame_(NSMakeRect(0, 0, size, size))
        ov.setAutoresizingMask_(1 | 32)  # всегда в правом нижнем углу, поверх лица
        ov.on_click = on_click
        ov.on_double = on_double
        box.addSubview_(ov)
        w.setContentView_(box)
        self.w, self.wv, self.ov = w, wv, ov
        self.state = None
        self.visible = False   # окно на экране
        self.hide_at = None    # когда убрать окно после анимации испарения
        self.panels = []       # что сейчас должно быть на панелях
        self.expanded = False
        self.shrink_at = None

    def _js(self, code):
        try:
            self.wv.evaluateJavaScript_completionHandler_(code, None)
        except Exception:
            pass

    @property
    def showing(self):
        return self.visible and self.hide_at is None

    # ---------- размер окна ----------
    def _resize(self, expanded, animate=True):
        if expanded == self.expanded:
            return
        f = self.w.frame()
        right, bottom = f.origin.x + f.size.width, f.origin.y
        if expanded:
            scr = (self.w.screen() or NSScreen.mainScreen()).visibleFrame()
            wdt = self.size + PANEL_W
            hgt = max(self.size, min(PANEL_H, scr.origin.y + scr.size.height - bottom - 8))
            x = max(scr.origin.x, right - wdt)
            rect = NSMakeRect(x, bottom, right - x, hgt)
        else:
            rect = NSMakeRect(right - self.size, bottom, self.size, self.size)
        self.w.setFrame_display_animate_(rect, True, bool(animate and self.visible))
        self.expanded = expanded

    def set_panels(self, items):
        """Новый список панелей (из data/panels-<пользователь>.json)."""
        self.panels = list(items or [])
        if not self.showing:
            return
        if self.panels:
            self.shrink_at = None
            self._resize(True)
        else:
            self.shrink_at = time.monotonic() + 0.55  # дать панелям красиво свернуться
        self._js(f"window.setPanels&&setPanels({json.dumps(self.panels)});")

    # ---------- появление / исчезновение ----------
    def show(self):
        """Эффектное появление: вспышка, ударная волна, частицы слетаются в лицо."""
        if self.showing:
            return
        self.hide_at = None
        self.state = None
        self._js("window.appear&&appear();")
        if self.panels:
            self._resize(True, animate=False)
            self._js(f"window.setPanels&&setPanels({json.dumps(self.panels)});")
        self.w.orderFrontRegardless()
        self.visible = True

    def hide(self):
        """Эффектное испарение, затем окно убирается с экрана."""
        if not self.showing:
            return
        self._js("window.vanish&&vanish();")
        self.hide_at = time.monotonic() + 2.1

    def push(self, state, level, look=None):
        """Вызывается ~30 раз в секунду в главном потоке."""
        now = time.monotonic()
        if self.hide_at is not None and now >= self.hide_at:
            self.w.orderOut_(None)
            self.visible = False
            self.hide_at = None
            self._resize(False, animate=False)
        if self.shrink_at is not None and now >= self.shrink_at:
            self.shrink_at = None
            if not self.panels:
                self._resize(False)
        if not self.visible:
            return
        f = self.w.frame()
        cx, cy = f.origin.x + f.size.width - self.size / 2, f.origin.y + self.size / 2
        if look is not None:  # камера видит сэра — смотрим ему в глаза
            lx, ly = look
        else:
            m = NSEvent.mouseLocation()
            scr = NSScreen.mainScreen().frame()
            lx = max(-1.0, min(1.0, (m.x - cx) / (scr.size.width * 0.35)))
            ly = max(-1.0, min(1.0, (m.y - cy) / (scr.size.height * 0.35)))
        js = ""
        if state != self.state:
            js += f"window.setState&&setState('{state}');"
            self.state = state
        js += f"window.upd&&upd({level:.3f},{lx:.3f},{ly:.3f});"
        self._js(js)
