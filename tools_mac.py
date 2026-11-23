"""Руки Alfred: всё, что он умеет делать на Mac."""
import base64
import datetime as dt
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

DANGER_SH = re.compile(
    r"(\brm\b|rmdir|\bmv\b|\bsudo\b|shutdown|reboot|\bhalt\b|killall|\bkill\b|pkill|diskutil|chmod|chown|"
    r"launchctl|defaults\s+write|\bdd\b|mkfs|>\s*/(?!tmp)|curl[^|]*\|\s*(ba|z)?sh|\bsecurity\b|"
    r"brew\s+(uninstall|remove)|osascript.*(delete|send|empty|erase))", re.I)
DANGER_AS = re.compile(
    r"(delete|\bsend\b|empty|erase|\bquit\b|shut down|restart|log out|trash|do shell script|keystroke|"
    r"key code|remove|password|purchase|buy)", re.I)


def esc(s) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def osa(script: str, timeout: int = 60) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "ошибка AppleScript").strip()[:800])
    return r.stdout.strip()


def as_date(var: str, when: dt.datetime) -> str:
    """Дата для AppleScript без зависимости от языка системы."""
    return (
        f"set {var} to current date\n"
        f"set day of {var} to 1\n"
        f"set year of {var} to {when.year}\n"
        f"set month of {var} to {when.month}\n"
        f"set day of {var} to {when.day}\n"
        f"set hours of {var} to {when.hour}\n"
        f"set minutes of {var} to {when.minute}\n"
        f"set seconds of {var} to 0\n"
    )


def parse_dt(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    if d.tzinfo is not None:
        d = d.astimezone().replace(tzinfo=None)
    return d


def short(x, n=300) -> str:
    if isinstance(x, list):
        return "[изображение/список]"
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + "…"


def _p(desc, **props):
    return {"type": "object", "properties": props, "required": desc}


S = lambda d: {"type": "string", "description": d}  # noqa: E731
B = lambda d: {"type": "boolean", "description": d}  # noqa: E731
N = lambda d: {"type": "number", "description": d}  # noqa: E731
RISK = B("true, если действие что-то удаляет, перемещает, отправляет, закрывает приложения, меняет системные настройки или тратит деньги")
SUMMARY = S("Очень короткое описание действия для голосового подтверждения, на языке сэра, например «удалить три файла с рабочего стола»")

TOOL_DEFS = [
    {"name": "open_app", "description": "Открыть приложение на Mac по имени (Safari, Telegram, Music, Finder, DaVinci Resolve…).",
     "input_schema": _p(["name"], name=S("Имя приложения"))},
    {"name": "open_url", "description": "Открыть сайт или ссылку в браузере по умолчанию.",
     "input_schema": _p(["url"], url=S("Полный адрес https://…"))},
    {"name": "run_applescript", "description": "Выполнить произвольный AppleScript. Универсальный инструмент для всего, чего нет в других: управление приложениями, Finder, Музыкой, окнами, системой.",
     "input_schema": _p(["script", "risky", "summary"], script=S("Код AppleScript"), risky=RISK, summary=SUMMARY)},
    {"name": "run_shell", "description": "Выполнить команду zsh на Mac (в домашней папке). Вывод обрезается до 4000 символов.",
     "input_schema": _p(["command", "risky", "summary"], command=S("Команда"), risky=RISK, summary=SUMMARY)},
    {"name": "set_volume", "description": "Установить громкость звука Mac от 0 до 100.",
     "input_schema": _p(["level"], level=N("0–100"))},
    {"name": "media_control", "description": "Управление воспроизведением: play, pause, playpause, next, previous.",
     "input_schema": _p(["action"], action={"type": "string", "enum": ["play", "pause", "playpause", "next", "previous"]},
                        app={"type": "string", "enum": ["Music", "Spotify"], "description": "По умолчанию Music"})},
    {"name": "look_at_screen", "description": "Сделать снимок экрана и посмотреть на него, чтобы ответить на вопрос о том, что сейчас на экране.",
     "input_schema": _p([])},
    {"name": "take_screenshot", "description": "Сохранить скриншот экрана на рабочий стол.",
     "input_schema": _p([])},
    {"name": "create_note", "description": "Создать заметку в приложении «Заметки».",
     "input_schema": _p(["title", "body"], title=S("Заголовок"), body=S("Текст заметки"))},
    {"name": "create_reminder", "description": "Создать напоминание в приложении «Напоминания», при желании со временем.",
     "input_schema": _p(["title"], title=S("Что напомнить"), due=S("Когда, ISO 8601 местного времени, например 2026-11-05T18:30"))},
    {"name": "create_calendar_event", "description": "Создать событие в календаре.",
     "input_schema": _p(["title", "start"], title=S("Название"), start=S("Начало ISO 8601 местного времени"),
                        end=S("Конец ISO 8601; по умолчанию через час"))},
    {"name": "get_calendar_events", "description": "Получить события календаря на сегодня и ближайшие дни.",
     "input_schema": _p([], days=N("Сколько дней, начиная с сегодня; по умолчанию 1"))},
    {"name": "get_weather", "description": "Погода сейчас и прогноз на сегодня.",
     "input_schema": _p([], city=S("City in Latin letters; empty = detect from the network"))},
    {"name": "find_files", "description": "Найти файлы на Mac по имени (через Spotlight).",
     "input_schema": _p(["query"], query=S("Часть имени файла"), folder=S("Папка для поиска, например ~/Desktop; по умолчанию весь домашний каталог"))},
    {"name": "set_timer", "description": "Поставить таймер; по окончании Alfred скажет об этом голосом.",
     "input_schema": _p(["seconds"], seconds=N("Через сколько секунд"), label=S("О чём напомнить"))},
    {"name": "remember", "description": "Запомнить надолго факт о сэре: предпочтения, привычки, имена близких, рабочие детали. Не для паролей и номеров карт.",
     "input_schema": _p(["fact"], fact=S("Факт одной фразой"))},
    {"name": "forget", "description": "Забыть факты, содержащие указанный текст.",
     "input_schema": _p(["text"], text=S("Что забыть"))},
    {"name": "create_skill", "description": "Создать или обновить свой навык на Python, когда нашёл рабочий способ сделать то, чего не было в инструментах. Код определяет функцию run(**kwargs) -> str; можно subprocess, osascript, urllib и любые установленные пакеты. Навык с тем же именем перезаписывается.",
     "input_schema": _p(["name", "description", "input_schema", "code", "summary"],
                        name=S("Имя латиницей: lower_snake_case"), description=S("Что делает навык, одной фразой"),
                        input_schema={"type": "object", "description": "JSON-схема аргументов run(), type=object"},
                        code=S("Полный код Python с функцией run(**kwargs)"), summary=SUMMARY)},
    {"name": "self_review", "description": "Проанализировать свои недавние ошибки и обновить уроки. Вызывай, когда сэр просит разобрать ошибки или стать лучше.",
     "input_schema": _p([])},
    {"name": "get_usage_stats", "description": "Сколько запросов и примерно сколько денег потрачено на мозг Alfred сегодня и за месяц.",
     "input_schema": _p([])},
]


class Hands:
    def __init__(self, cfg, mouth, memory, skills, log, confirm_fn):
        self.cfg = cfg
        self.mouth = mouth
        self.memory = memory
        self.skills = skills
        self.log = log
        self.confirm_fn = confirm_fn
        self.brain = None  # подключается позже

    def tool_defs(self):
        return TOOL_DEFS + self.skills.tool_defs()

    def execute(self, name, args):
        args = args or {}
        try:
            if name.startswith("skill_"):
                out = self.skills.run(name[len("skill_"):], args)
            else:
                fn = getattr(self, "t_" + name, None)
                if fn is None:
                    return f"Нет такого инструмента: {name}"
                out = fn(**args)
            self.log.add("tool", name=name, args=short(args), ok=True, result=short(out))
            return out
        except Exception as e:
            self.log.add("tool", name=name, args=short(args, 600), ok=False, error=str(e)[:600])
            return f"ОШИБКА: {e}"

    def _confirm(self, summary):
        ok = self.confirm_fn(summary or "выполнить действие")
        self.log.add("confirm", summary=summary, approved=ok)
        return ok

    # ---------- приложения и сайты
    def t_open_app(self, name):
        r = subprocess.run(["open", "-a", name], capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"не нашёл приложение {name}")
        return f"Открыл {name}."

    def t_open_url(self, url):
        if not re.match(r"^https?://", url):
            url = "https://" + url
        subprocess.run(["open", url], timeout=20, check=True)
        return "Открыл."

    # ---------- универсальные
    def t_run_applescript(self, script, risky=False, summary=""):
        if risky or DANGER_AS.search(script):
            if not self._confirm(summary):
                return "Сэр не подтвердил. Действие отменено."
        return osa(script, timeout=90) or "Готово."

    def t_run_shell(self, command, risky=False, summary=""):
        if risky or DANGER_SH.search(command):
            if not self._confirm(summary):
                return "Сэр не подтвердил. Действие отменено."
        r = subprocess.run(["/bin/zsh", "-lc", command], capture_output=True, text=True,
                           timeout=120, cwd=str(Path.home()))
        out = (r.stdout + ("\n" + r.stderr if r.stderr else "")).strip()
        if r.returncode != 0:
            return f"Код выхода {r.returncode}. {out[-3000:]}"
        return out[-4000:] or "Готово."

    # ---------- звук и музыка
    def t_set_volume(self, level):
        level = max(0, min(100, int(level)))
        osa(f"set volume output volume {level}")
        return f"Громкость {level}."

    def t_media_control(self, action, app="Music"):
        cmd = {"play": "play", "pause": "pause", "playpause": "playpause",
               "next": "next track", "previous": "previous track"}[action]
        osa(f'tell application "{esc(app)}" to {cmd}')
        return "Готово."

    # ---------- экран
    def _capture(self, path):
        r = subprocess.run(["screencapture", "-x", "-t", "jpg", path], capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or not os.path.exists(path) or os.path.getsize(path) == 0:
            raise RuntimeError("Нет доступа к экрану. Включите: Настройки → Конфиденциальность → Запись экрана → Терминал.")

    def t_look_at_screen(self):
        fd, path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        try:
            self._capture(path)
            subprocess.run(["sips", "-Z", "1568", path], capture_output=True, timeout=20)
            data = base64.b64encode(Path(path).read_bytes()).decode()
        finally:
            if os.path.exists(path):
                os.remove(path)
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
            {"type": "text", "text": "Это текущий снимок экрана."},
        ]

    def t_take_screenshot(self):
        name = dt.datetime.now().strftime("Alfred %Y-%m-%d %H.%M.%S.jpg")
        path = str(Path.home() / "Desktop" / name)
        self._capture(path)
        return f"Скриншот сохранён на рабочий стол: {name}"

    # ---------- заметки, напоминания, календарь
    def t_create_note(self, title, body=""):
        html = f"<h1>{esc(title)}</h1><div>{esc(body).replace(chr(10), '<br>')}</div>"
        osa(f'tell application "Notes" to tell default account to make new note at folder 1 '
            f'with properties {{name:"{esc(title)}", body:"{html}"}}')
        return "Заметка создана."

    def t_create_reminder(self, title, due=None):
        if due:
            when = parse_dt(due)
            script = (as_date("d", when) +
                      f'tell application "Reminders"\n'
                      f'  set r to make new reminder with properties {{name:"{esc(title)}"}}\n'
                      f'  set due date of r to d\n'
                      f'  set remind me date of r to d\n'
                      f'end tell')
        else:
            script = f'tell application "Reminders" to make new reminder with properties {{name:"{esc(title)}"}}'
        osa(script)
        return "Напоминание создано."

    def t_create_calendar_event(self, title, start, end=None):
        s = parse_dt(start)
        e = parse_dt(end) if end else s + dt.timedelta(hours=1)
        script = (as_date("d1", s) + as_date("d2", e) +
                  'tell application "Calendar"\n'
                  '  set cal to first calendar whose writable is true\n'
                  f'  make new event at end of events of cal with properties {{summary:"{esc(title)}", start date:d1, end date:d2}}\n'
                  'end tell')
        osa(script, timeout=60)
        return "Событие добавлено в календарь."

    def t_get_calendar_events(self, days=1):
        days = max(1, min(14, int(days or 1)))
        script = (
            "set d0 to current date\nset hours of d0 to 0\nset minutes of d0 to 0\nset seconds of d0 to 0\n"
            f"set d1 to d0 + ({days} * days)\nset out to \"\"\n"
            'tell application "Calendar"\n'
            "  repeat with c in calendars\n"
            "    try\n"
            "      set evs to (every event of c whose start date >= d0 and start date < d1)\n"
            "      repeat with e in evs\n"
            '        set out to out & (summary of e) & " | " & ((start date of e) as string) & linefeed\n'
            "      end repeat\n"
            "    end try\n"
            "  end repeat\n"
            "end tell\nreturn out"
        )
        out = osa(script, timeout=90)
        return out or "Событий нет."

    # ---------- погода
    def t_get_weather(self, city=None):
        city = city or self.cfg.get("city") or ""
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1&lang=ru"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=15) as r:
            j = json.loads(r.read().decode())
        cur = j["current_condition"][0]
        today = j["weather"][0]
        desc = (cur.get("lang_ru") or cur.get("weatherDesc"))[0]["value"]
        rain = max(int(h.get("chanceofrain", 0)) for h in today["hourly"])
        return (f"{city}: сейчас {cur['temp_C']}°C, ощущается как {cur['FeelsLikeC']}°C, {desc}. "
                f"Сегодня от {today['mintempC']} до {today['maxtempC']}°C, вероятность дождя до {rain}%, "
                f"ветер {cur['windspeedKmph']} км/ч.")

    # ---------- файлы
    def t_find_files(self, query, folder=None):
        cmd = ["mdfind", "-name", query]
        if folder:
            cmd[1:1] = ["-onlyin", os.path.expanduser(folder)]
        else:
            cmd[1:1] = ["-onlyin", str(Path.home())]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines = [l for l in r.stdout.splitlines() if "/Library/" not in l][:25]
        return "\n".join(lines) or "Ничего не нашёл."

    # ---------- таймер
    def t_set_timer(self, seconds, label=""):
        seconds = max(1, int(seconds))
        addr = self.cfg.get("address", "сэр")

        def ring():
            from voice import chime
            chime("Glass")
            self.mouth.say(f"{addr.capitalize()}, время вышло. {label}".strip())

        t = threading.Timer(seconds, ring)
        t.daemon = True
        t.start()
        m, s = divmod(seconds, 60)
        return f"Таймер на {m} мин {s} с запущен." if m else f"Таймер на {s} с запущен."

    # ---------- память и самоулучшение
    def t_remember(self, fact):
        return self.memory.add(fact)

    def t_forget(self, text):
        return self.memory.forget(text)

    def t_create_skill(self, name, description, input_schema, code, summary=""):
        # Безопасные навыки Alfred добавляет сам; опасный код — только с «да» сэра.
        if DANGER_SH.search(code) or re.search(r"(delete|send|отправ|удал|rmtree|os\.remove|unlink)", code, re.I):
            if not self._confirm(summary or f"создать навык «{description}», он может удалять или отправлять"):
                return "Сэр не подтвердил создание навыка."
        return self.skills.create(name, description, input_schema, code)

    def t_self_review(self):
        if not self.brain:
            return "Модуль самоанализа недоступен."
        return self.brain.reflect(force=True)

    def t_get_usage_stats(self):
        now = dt.datetime.now()
        day0 = dt.datetime(now.year, now.month, now.day).timestamp()
        mon0 = dt.datetime(now.year, now.month, 1).timestamp()
        pin = self.cfg.get("price_input_per_million_usd", 3.0)
        pout = self.cfg.get("price_output_per_million_usd", 15.0)

        def agg(ts):
            ins = outs = n = 0
            for r in self.log.since(ts):
                if r.get("type") == "usage":
                    ins += r.get("input", 0) + r.get("cache_write", 0) * 1.25 + r.get("cache_read", 0) * 0.1
                    outs += r.get("output", 0)
                elif r.get("type") == "request":
                    n += 1
            return n, (ins * pin + outs * pout) / 1e6

        dn, dc = agg(day0)
        mn, mc = agg(mon0)
        return (f"Сегодня запросов: {dn}, примерно ${dc:.2f}. За месяц: {mn}, примерно ${mc:.2f}. "
                f"Плюс веб-поиски, если были.")
