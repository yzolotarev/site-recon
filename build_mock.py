"""
build_mock.py — собрать КАРКАС мок-сайта из сырья разведки через LLM (Gemini web2api).

Берёт папку, записанную recon.py (снимки страниц + timeline таймингов), скармливает
локальным «бесплатным мозгам» (http://localhost:8081, web2api) и просит сгенерировать
черновой mock-сервер на stdlib, повторяющий структуру и поведение сайта.

Это КАРКАС, а не финал: LLM хорошо воспроизводит СТРУКТУРУ (верстка, эндпоинты, форма
JSON-ответов, селекторы) и черновые ПРАВИЛА ТАЙМИНГА из timeline; тонкую логику
состояний человек дошлифовывает. Чем богаче разведка (больше релоадов в timeline),
тем точнее восстановятся тайминги.

Использование:
    python3 build_mock.py <папка_разведки> [-o server.py] [--model MODEL]
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

GEMINI_URL = "http://localhost:8081/v1/chat/completions"
DEFAULT_MODEL = "gemini-3.5-flash-thinking"

SYSTEM = """Ты генерируешь локальный МОК-СЕРВЕР на Python (только stdlib, http.server) —
имитацию реального сайта для тестов браузерной автоматизации/бота.

Тебе дают СЫРЬЁ разведки любого сайта: innerText страниц, фрагменты HTML, и timeline
наблюдений (какие данные/запросы приходили и КОГДА — с метками времени).

Сгенерируй server.py так, чтобы автоматизация, написанная под реальный сайт, работала
и против мока. Требования:
- воспроизведи те же URL-пути и HTTP-методы, что видны в timeline/HTML;
- если в timeline есть повторяющиеся data-ответы (напр. лента/список) — воспроизведи
  форму их JSON и, если по меткам времени видна периодичность появления новых элементов,
  смоделируй это (элементы «капают» со временем, видны при перезапросе);
- сохрани ключевые селекторы, class-атрибуты, плейсхолдеры и тексты кнопок из HTML —
  за них цепляется автоматизация;
- сделай сервер запускаемым: `python3 server.py [--port N]`.

Верни ТОЛЬКО код одного файла server.py. Без markdown-ограждения, без пояснений."""


def _read(p, limit):
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def gather(recon_dir):
    d = Path(recon_dir).expanduser()
    if not d.is_dir():
        sys.exit(f"нет папки: {d}")
    parts = []
    tl = d / "timeline.jsonl"
    if tl.exists():
        parts.append("=== TIMELINE (тайминги данных/навигации) ===\n" + _read(tl, 9000))
    for t in sorted(d.glob("*_text.txt"))[:8]:
        parts.append(f"=== INNERTEXT {t.name} ===\n" + _read(t, 2500))
    for h in sorted(d.glob("*.html"))[:4]:
        parts.append(f"=== HTML {h.name} ===\n" + _read(h, 3500))
    if not parts:
        sys.exit(f"в {d} нет сырья (recon.py его не создал?)")
    return "\n\n".join(parts)


def ask_llm(raw, model):
    payload = json.dumps({"model": model, "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "СЫРЬЁ:\n\n" + raw + "\n\nСгенерируй server.py."},
    ]}).encode()
    req = urllib.request.Request(GEMINI_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def strip_fence(code):
    c = code.strip()
    if c.startswith("```"):
        c = c.split("\n", 1)[1] if "\n" in c else c
        if c.endswith("```"):
            c = c.rsplit("```", 1)[0]
    return c.strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recon_dir")
    ap.add_argument("-o", "--out", default="mock_server.py")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    raw = gather(args.recon_dir)
    print(f"→ сырья: {len(raw)} символов. Прошу LLM собрать каркас мока...")
    try:
        code = strip_fence(ask_llm(raw, args.model))
    except Exception as e:
        sys.exit(f"LLM не ответил: {e}. web2api на :8081 поднят?")
    Path(args.out).write_text(code, encoding="utf-8")
    print(f"✅ каркас: {args.out} ({len(code)} символов). Это ЧЕРНОВИК — проверь и дошлифуй.")


if __name__ == "__main__":
    main()
