# site-recon — record any website and play it back exactly

A tool for those who write automation (bots, scrapers, tests) and want to
**debug it against an exact copy of the website, without touching the original** (and without risking a ban).

## Principle: FIDELITY, not paraphrasing

The copy must be **byte-for-byte**: same IDs, classes, attributes, names, response bodies.
Then a bot written for the original works against the copy **with the exact same key** — just like
a plastic key opens the same door. Therefore, we **do not generate or
adapt anything** — we replay exactly what was RECORDED.

## Flow

```
1. RECORD          recon.py <url>      → you browse manually, it records EVERYTHING (exactly)
        ↓ raw material: full DOM + HAR (response bodies) + timeline (timings)
2. REPLAY          replay.py           → routeFromHAR serves recorded content byte-for-byte
        ↓
3. Run your bot against the copy — offline, safely, accurately.
```

## 1. Recording (`recon.py`) — passive and safe

```bash
pip install patchright && patchright install chromium
python3 recon.py https://site.com/app
```

The script **clicks NOTHING** — YOU browse manually like a regular human (important for
fresh accounts: you get banned for auto-clicking, but not for passive recording). It saves AUTOMATICALLY:

- `traffic.har` — all traffic, response bodies **byte-for-byte**;
- `NNN_*.html` — **full DOM** of each state (all IDs/classes/attributes), captured
  automatically upon every change and across all tabs;
- `NNN_*_text.txt`, `*.png` — text and screenshot (for human review);
- `timeline.jsonl` — when data/navigation arrived + **explicit timing deltas**:
  `ts` (absolute), `t_rel` (sec from start), `delta_ms` (from previous
  event), `delta_same_ms` (from previous event of the same type). `delta_same_ms`
  between `data` = data frequency ("appears every N seconds"); from `Maps` to
  `data` = confirmation "arrives on reload". This is the raw material for restoring the BEHAVIOR of the site, not just its look.

Browse the site thoroughly, reload (Ctrl-R) many times — the richer the recording, the more complete
the copy. Raw material → `~/.site-recon/captures/<timestamp>/`.

## 2. Exact Replay (`replay.py`) — fidelity-first

```bash
python3 replay.py ~/.site-recon/captures/<timestamp> https://site.com/app
```

Serves **recorded** responses via built-in Playwright `routeFromHAR` — DOM and API
are identical to the original because they are the original data. It does not hit the live website.

### Integrating into your bot (main scenario)

```python
from replay import attach_replay
ctx = await browser.new_context()
await attach_replay(ctx, "~/.site-recon/captures/<timestamp>/traffic.har")
# then the bot navigates real URLs — and receives recorded responses, byte-for-byte
```

## 3. (Optional) Mock Skeleton via LLM — `build_mock.py`

```bash
python3 build_mock.py ~/.site-recon/captures/<timestamp> -o mock_server.py
```

Generates a **draft** editable mock server based on the raw data (via Gemini web2api).
⚠️ This is an **adaptation** (LLM rewrites the layout), so it is **NOT for an exact copy** —
only when you need a lightweight, modifiable environment and differences are acceptable. For fidelity —
use `replay.py`.

## Limitations Honestly

`routeFromHAR` replays a recorded **snapshot**. Pure dynamics (a new element
after N minutes, "appears only on reload") are served exactly as recorded — to
model them as a process, a thin stateful layer is needed on top of the recorded responses
(choosing which RECORDED response to serve) without changing their content.

