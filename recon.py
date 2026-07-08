"""
recon.py — ПАССИВНЫЙ рекордер ЛЮБОГО сайта.

Одна кнопка: запускаешь → браузер открыт → ТЫ САМ кликаешь и ходишь как человек,
скрипт молча пишет ВСЁ. Скрипт НИЧЕГО не автоматизирует (не кликает, не обновляет) —
поэтому для сайта это невидимо и безопасно даже на свежих аккаунтах.

Собирает СЫРЬЁ, по которому потом можно сымитировать работу сайта:
  • traffic.har   — весь сетевой трафик (API/GraphQL/XHR ответы).
  • timeline.jsonl — компактный лог: КОГДА какие данные/запросы приходили
                     (тайминги — из них выводится поведение: «данные раз в N сек»,
                     «появляется на релоаде» и т.п.). Работает для любого сайта.
  • NNN_*.html / _text.txt / *.png — снимки РЕНДЕРА страниц (SPA рисует на клиенте,
                     в HAR этого нет), снимаются САМИ при каждом изменении и по всем
                     открытым вкладкам/окнам.

Всё пишется автоматически — жать ничего не надо. Можно опционально вписать метку
+ Enter, чтобы пометить важный момент своим названием.

Использование:
    python3 recon.py <URL> [--profile DIR] [--out DIR] [--headless]

Пример:
    python3 recon.py https://example.com/app

По умолчанию:
    профиль браузера → ~/.site-recon/profile   (сессия сохраняется между запусками)
    сырьё            → ~/.site-recon/captures/<timestamp>/

Зависимость:  pip install patchright  &&  patchright install chromium
(patchright — стелс-форк Playwright; можно заменить на playwright, поменяв импорт.)
"""
import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path

try:
    from patchright.async_api import async_playwright
except ImportError:               # запасной вариант — обычный playwright
    from playwright.async_api import async_playwright


# ── Захват снимков страниц (DOM + текст + скриншот) ──────────

_last_sig = {}
_snap_n = 0


async def _capture_page(page, out_dir, label):
    global _snap_n
    try:
        url = page.url
        if not url or url.startswith("about:"):
            return
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        return

    sig = (url, len(text), hash(text))
    if label == "auto" and _last_sig.get(page) == sig:
        return                              # не изменилось — не дублируем
    _last_sig[page] = sig

    _snap_n += 1
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in label).strip() or "snap"
    ts = datetime.now().strftime("%H%M%S")
    stem = out_dir / f"{_snap_n:03d}_{ts}_{safe}"
    try:
        stem.with_suffix(".html").write_text(await page.content(), encoding="utf-8")
        stem.with_name(stem.name + "_text.txt").write_text(
            f"URL: {url}\n\n{text}", encoding="utf-8")
        await page.screenshot(path=str(stem.with_suffix(".png")))
        print(f"💾 снимок #{_snap_n} [{label}]: {url[:60]}", flush=True)
    except Exception as e:
        print(f"снять не удалось: {e}", flush=True)


# ── Таймлайн (generic: все API/JSON/XHR ответы + навигация) ──

def _looks_like_data(url, ctype):
    u = url.lower()
    return ("application/json" in ctype or "graphql" in u
            or "/api" in u or u.endswith(".json"))


class Timeline:
    """Лог событий с ЯВНЫМИ дельтами таймингов — сырьё для восстановления поведения.

    К каждому событию пишем:
      ts            — абсолютное время (ISO, мс);
      t_rel         — секунд от старта записи;
      delta_ms      — сколько прошло с ЛЮБОГО предыдущего события;
      delta_same_ms — сколько прошло с предыдущего события ТОГО ЖЕ типа.
    delta_same_ms между 'data' → периодичность данных («заказы раз в N мин»);
    от 'navigate' до следующего 'data' → подтверждает «приходит на релоаде».
    """
    def __init__(self, path):
        self.f = path.open("a", encoding="utf-8")
        self._t0 = time.time()
        self._last = None
        self._last_by_kind = {}

    def write(self, event):
        now = time.time()
        event["ts"] = datetime.now().isoformat(timespec="milliseconds")
        event["t_rel"] = round(now - self._t0, 3)
        event["delta_ms"] = None if self._last is None else int((now - self._last) * 1000)
        kind = event.get("event", "?")
        prev = self._last_by_kind.get(kind)
        event["delta_same_ms"] = None if prev is None else int((now - prev) * 1000)
        self._last = now
        self._last_by_kind[kind] = now
        self.f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.f.flush()

    def close(self):
        self.f.close()


def attach_timeline(page, tl):
    async def on_resp(resp):
        try:
            url = resp.url
            ctype = (resp.headers or {}).get("content-type", "")
            if not _looks_like_data(url, ctype):
                return
            body = await resp.text()
        except Exception:
            return
        tl.write({"event": "data", "method": resp.request.method,
                  "status": resp.status, "url": url, "bytes": len(body),
                  "preview": body[:600]})

    page.on("response", lambda r: asyncio.ensure_future(on_resp(r)))
    page.on("framenavigated", lambda f: tl.write(
        {"event": "navigate", "url": f.url}) if f == page.main_frame else None)


# ── stdin без блокировки браузера ────────────────────────────

async def stdin_lines():
    loop = asyncio.get_running_loop()
    while True:
        yield await loop.run_in_executor(None, _readline)


def _readline():
    try:
        return input()
    except (EOFError, KeyboardInterrupt):
        return "q"


# ── Основной цикл ────────────────────────────────────────────

async def run(url, profile, out_dir, headless):
    out_dir.mkdir(parents=True, exist_ok=True)
    Path(profile).mkdir(parents=True, exist_ok=True)
    har = out_dir / "traffic.har"
    tl = Timeline(out_dir / "timeline.jsonl")
    print(f"[site-recon] сырьё → {out_dir}", flush=True)

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(profile),
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage"],
            ignore_default_args=["--enable-automation"],
            record_har_path=str(har),
            record_har_content="embed",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        def wire(p):
            p.on("framenavigated",
                 lambda _f: asyncio.ensure_future(_capture_page(p, out_dir, "auto")))
            attach_timeline(p, tl)

        ctx.on("page", wire)
        wire(page)
        await page.goto(url, wait_until="domcontentloaded")

        print("=" * 66)
        print("🔎  ЗАПИСЬ ИДЁТ. Скрипт НЕ кликает — ходишь по сайту ТЫ, руками.")
        print("    Всё сохраняется САМО (трафик + снимки при каждом изменении).")
        print("    Метка важного момента: впиши слово + Enter (необязательно).")
        print("    Закончить: q + Enter (или Ctrl-C).")
        print("=" * 66)

        stop = asyncio.Event()

        async def auto_loop():
            while not stop.is_set():
                for p in list(ctx.pages):
                    await _capture_page(p, out_dir, "auto")
                await asyncio.sleep(6)

        task = asyncio.create_task(auto_loop())
        async for line in stdin_lines():
            cmd = line.strip()
            if cmd.lower() in ("q", "quit", "exit"):
                break
            if cmd:
                for p in list(ctx.pages):
                    await _capture_page(p, out_dir, cmd)

        stop.set()
        task.cancel()
        print("[site-recon] закрываю браузер, дописываю HAR...", flush=True)
        await ctx.close()
    tl.close()
    print(f"✅ готово: {out_dir}", flush=True)
    print("   traffic.har + timeline.jsonl + снимки (*.html/_text.txt/*.png)", flush=True)


def main():
    home = Path.home() / ".site-recon"
    ap = argparse.ArgumentParser(description="Пассивный рекордер любого сайта.")
    ap.add_argument("url", help="стартовый URL сайта")
    ap.add_argument("--profile", default=str(home / "profile"),
                    help="папка профиля браузера (сессия сохраняется)")
    ap.add_argument("--out", default=None, help="папка вывода (по умолч. ~/.site-recon/captures/<ts>)")
    ap.add_argument("--headless", action="store_true", help="без окна (для тестов)")
    args = ap.parse_args()

    out = Path(args.out) if args.out else home / "captures" / datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        asyncio.run(run(args.url, args.profile, out, args.headless))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
