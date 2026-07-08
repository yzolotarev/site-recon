"""
replay.py — ТОЧНОЕ воспроизведение записанного сайта (fidelity-first).

Принцип: НИЧЕГО не генерируем и не адаптируем. Браузер отдаёт ЗАПИСАННЫЕ
ответы (из traffic.har) байт-в-байт — тот же DOM, те же id/class/атрибуты,
те же тела API. Бот, написанный под оригинал, работает против копии тем же
«ключом», потому что это ОРИГИНАЛЬНЫЕ данные, а не пересказ.

Под капотом — встроенный Playwright `route_from_har()`: перехват сетевых
запросов браузера и подстановка записанных ответов. Оффлайн, без сервера,
без похода на реальный сайт.

Два режима:
  1) demo (по умолчанию) — открыть URL из записи, сохранить отданный DOM и
     сверить с оригинальным снимком (доказательство идентичности).
  2) как БИБЛИОТЕКА — используй attach_replay(context, har) в своём боте/тесте,
     чтобы гонять автоматизацию против записанной копии:

        from replay import attach_replay
        ctx = await browser.new_context()
        await attach_replay(ctx, "~/.site-recon/captures/<ts>/traffic.har")
        # дальше твой бот ходит по реальным URL — получает записанные ответы

Использование demo:
    python3 replay.py <папка_разведки> <URL_из_записи>
"""
import argparse
import asyncio
import sys
from pathlib import Path

try:
    from patchright.async_api import async_playwright
except ImportError:
    from playwright.async_api import async_playwright


async def attach_replay(context, har_path, url_glob="**/*"):
    """Повесить точное воспроизведение HAR на контекст браузера.

    url_glob — какие запросы обслуживать из записи (по умолчанию все).
    not_found="abort" → если запроса нет в HAR, он падает (видно пробелы записи),
    а не идёт в реальную сеть (безопасно: на живой сайт не ходим).
    """
    await context.route_from_har(
        str(Path(har_path).expanduser()),
        url=url_glob,
        not_found="abort",
    )


async def demo(recon_dir, url):
    d = Path(recon_dir).expanduser()
    har = d / "traffic.har"
    if not har.exists():
        sys.exit(f"нет {har} — сначала запиши сайт через recon.py")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        await attach_replay(ctx, har)
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            print(f"⚠️ {url} нет в записи или не открылся: {e}")
            print("   (routeFromHAR отдаёт только записанное — походи по этому URL в recon.py)")
            await browser.close()
            return

        served = await page.content()
        out = d / "_replay_served.html"
        out.write_text(served, encoding="utf-8")
        print(f"✅ отдан записанный DOM для {url}")
        print(f"   сохранён: {out}  ({len(served)} символов)")

        # сверка с оригинальным снимком, если он есть
        snaps = sorted(d.glob("*.html"))
        orig = next((s for s in snaps if url.rstrip("/").split("/")[-1] in s.read_text(
            encoding="utf-8", errors="ignore")[:200]), None)
        if orig:
            same = orig.read_text(encoding="utf-8", errors="ignore") == served
            print(f"   сверка со снимком {orig.name}: "
                  f"{'ИДЕНТИЧНО ✅' if same else 'есть отличия (динамика/таймстемпы)'}")
        await browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recon_dir", help="папка разведки (recon.py)")
    ap.add_argument("url", help="URL из записи, который воспроизвести")
    args = ap.parse_args()
    asyncio.run(demo(args.recon_dir, args.url))


if __name__ == "__main__":
    main()
