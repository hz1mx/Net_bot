"""
Telegram bot that watches the Net Academy booking page and alerts you when
new sessions appear for a given trainer (default: محمد الداعج).

Two ways to read the sessions:
    * API mode (recommended): set API_URL to the site's own data endpoint; plain HTTP, fast and exact.
    * Browser mode: fallback that renders the page with headless Chromium and searches it.

Modes:
    python bot.py             # long-running: checks periodically + answers /start, /check, /status
    python bot.py --once      # single check then exit (for cron / GitHub Actions)
    python bot.py --dump      # single check, prints result and saves raw data to ./debug (no Telegram)
    python bot.py --find-api  # opens the booking page and lists the API requests that mention the trainer
    python bot.py --probe     # replays the site's booking server action for the coming days (debugging)
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TARGET_URL = os.getenv("TARGET_URL", "https://netacademy.sa/book?activity=tennis&type=trainer")
TRAINER_KEYWORDS = [
    k.strip()
    for k in os.getenv("TRAINER_KEYWORDS", "الداعج,داعج,aldaaj,daaj,daej,daij,da3j").split(",")
    if k.strip()
]
TRAINER_LABEL = os.getenv("TRAINER_LABEL", "محمد الداعج")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "120"))
# The academy releases new sessions every night at midnight (Riyadh time); check much more often around then.
RELEASE_TIME = os.getenv("RELEASE_TIME", "00:00")
RELEASE_WINDOW_BEFORE_MIN = int(os.getenv("RELEASE_WINDOW_BEFORE_MIN", "2"))
RELEASE_WINDOW_AFTER_MIN = int(os.getenv("RELEASE_WINDOW_AFTER_MIN", "15"))
FAST_CHECK_INTERVAL = int(os.getenv("FAST_CHECK_INTERVAL", "10"))
CLICK_TRAINER = os.getenv("CLICK_TRAINER", "1") == "1"
PAGE_TIMEOUT_MS = int(os.getenv("PAGE_TIMEOUT_MS", "45000"))

# API mode. API_URL / API_BODY may contain {date}; it is filled with each day from today to today+DAYS_AHEAD.
API_URL = os.getenv("API_URL", "").strip()
API_METHOD = os.getenv("API_METHOD", "GET").upper()
API_HEADERS = json.loads(os.getenv("API_HEADERS") or "{}")
API_BODY = os.getenv("API_BODY", "")
DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", "3"))
BROWSER_FALLBACK = os.getenv("BROWSER_FALLBACK", "1") == "1"
USE_SERVER_ACTION = os.getenv("USE_SERVER_ACTION", "1") == "1"
RIYADH = timezone(timedelta(hours=3))  # Saudi Arabia has no DST


def today() -> date:
    return datetime.now(RIYADH).date()


def in_release_window(now: datetime | None = None) -> bool:
    now = now or datetime.now(RIYADH)
    h, m = (int(x) for x in RELEASE_TIME.split(":"))
    minutes_since_release = (now.hour * 60 + now.minute - (h * 60 + m)) % (24 * 60)
    return (minutes_since_release < RELEASE_WINDOW_AFTER_MIN
            or minutes_since_release >= 24 * 60 - RELEASE_WINDOW_BEFORE_MIN)


def current_interval() -> int:
    """Seconds until the next check: short inside the release window, never sleeping past its start."""
    if in_release_window():
        return FAST_CHECK_INTERVAL
    now = datetime.now(RIYADH)
    h, m = (int(x) for x in RELEASE_TIME.split(":"))
    window_start = now.replace(hour=h, minute=m, second=0, microsecond=0) - timedelta(minutes=RELEASE_WINDOW_BEFORE_MIN)
    if window_start <= now:
        window_start += timedelta(days=1)
    return max(1, min(CHECK_INTERVAL, int((window_start - now).total_seconds()) + 1))

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
DEBUG_DIR = Path("debug")
FAILURE_ALERT_AFTER = 3

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ENV_CHAT_IDS = [c.strip() for c in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("net_bot")

TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*(?:AM|PM|am|pm)\b|\d{1,2}\s*(?:ص|م)\b")
SLOT_KEY_TOKENS = {"time", "date", "datetime", "start", "starts", "end", "ends", "from", "to", "slot", "hour", "day"}
DATE_OR_TIME_RE = re.compile(r"\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}")
UNAVAILABLE_STATUS = {"booked", "full", "unavailable", "closed", "reserved", "cancelled", "canceled", "past"}


# --------------------------------------------------------------------------- text helpers

_ARABIC_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")


def normalize(text: str) -> str:
    text = _ARABIC_DIACRITICS.sub("", text)
    text = re.sub("[إأآٱ]", "ا", text)
    text = text.replace("ة", "ه").replace("ى", "ي")
    return text.lower()


NORMALIZED_KEYWORDS = [normalize(k) for k in TRAINER_KEYWORDS]


def has_keyword(text: str) -> bool:
    t = normalize(text)
    return any(k in t for k in NORMALIZED_KEYWORDS)


# --------------------------------------------------------------------------- JSON extraction


def _is_slot_key(key) -> bool:
    tokens = re.split(r"[_\-\s]+|(?<=[a-z])(?=[A-Z])", str(key))
    return any(t.lower() in SLOT_KEY_TOKENS for t in tokens)


def _looks_like_slot(d: dict) -> bool:
    return any(
        _is_slot_key(k) and isinstance(v, str) and DATE_OR_TIME_RE.search(v)
        for k, v in d.items()
    )


def _is_unavailable(d: dict) -> bool:
    for key, val in d.items():
        k = str(key).lower()
        if isinstance(val, bool):
            if k in {"available", "is_available", "isavailable", "bookable", "is_bookable"} and not val:
                return True
            if k in {"booked", "is_booked", "isbooked", "full", "is_full", "isfull", "disabled"} and val:
                return True
        elif isinstance(val, (int, float)) and k in {"remaining", "available_seats", "seats_left", "capacity_left", "spots"}:
            if val <= 0:
                return True
        elif isinstance(val, str) and k in {"status", "state"} and val.lower() in UNAVAILABLE_STATUS:
            return True
    return False


def _contains_keyword(node, trainer_ids: frozenset = frozenset()) -> bool:
    if isinstance(node, str):
        return node in trainer_ids or has_keyword(node)
    if isinstance(node, dict):
        return any(_contains_keyword(v, trainer_ids) for v in node.values())
    if isinstance(node, list):
        return any(_contains_keyword(v, trainer_ids) for v in node)
    return False


def _direct_keyword(d: dict) -> bool:
    return any(isinstance(v, str) and has_keyword(v) for v in d.values())


def _slot_summary(d: dict) -> str:
    parts = []
    for k, v in d.items():
        if isinstance(v, (str, int, float)) and _is_slot_key(k):
            parts.append(f"{k}: {v}")
    if not parts:
        parts = [json.dumps(d, ensure_ascii=False, sort_keys=True)[:200]]
    return " | ".join(parts)


def extract_slots_from_json(data) -> list[str]:
    """Find slot-like objects that belong to the trainer.

    Handles both shapes:
      * a list of slots where each slot references the trainer, and
      * a trainer object that contains its own list of slots.
    """
    found: list[dict] = []

    # Slots often point at the coach by id (e.g. "staffIds": [...]) instead of by name.
    trainer_ids: set[str] = set()

    def collect_ids(node):
        if isinstance(node, dict):
            if _direct_keyword(node):
                trainer_ids.update(
                    v for k, v in node.items()
                    if isinstance(v, str) and len(v) >= 4 and str(k).lower() in {"id", "_id", "uuid"}
                )
            for v in node.values():
                collect_ids(v)
        elif isinstance(node, list):
            for v in node:
                collect_ids(v)

    collect_ids(data)
    frozen_ids = frozenset(trainer_ids)

    def walk(node, owned_by_trainer: bool):
        if isinstance(node, dict):
            owned = owned_by_trainer or _direct_keyword(node)
            if _looks_like_slot(node) and (owned or _contains_keyword(node, frozen_ids)):
                found.append(node)
            for v in node.values():
                walk(v, owned)
        elif isinstance(node, list):
            for v in node:
                walk(v, owned_by_trainer)

    walk(data, False)

    # Keep only the most specific matches (drop ones that contain another match).
    ids = {id(d) for d in found}

    def contains_other(node, root=True) -> bool:
        if not root and isinstance(node, dict) and id(node) in ids:
            return True
        children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else []
        return any(contains_other(c, False) for c in children)

    leaves = [d for d in found if not contains_other(d) and not _is_unavailable(d)]
    return sorted({_slot_summary(d) for d in leaves})


# --------------------------------------------------------------------------- DOM extraction

DOM_JS = r"""
(keywords) => {
  const norm = (t) => t
    .replace(/[ؐ-ًؚ-ٰٟۖ-ۭـ]/g, '')
    .replace(/[إأآٱ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي').toLowerCase();
  const kws = keywords.map(norm);
  const match = (t) => { const n = norm(t || ''); return kws.some(k => n.includes(k)); };
  const all = Array.from(document.querySelectorAll('body *')).filter(el =>
      !['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName) && el.getClientRects().length);
  // smallest elements whose text mentions the trainer
  const hits = all.filter(el => match(el.innerText) &&
      !Array.from(el.children).some(c => match(c.innerText)));
  return hits.map(el => {
    let box = el;
    for (let i = 0; i < 6 && box.parentElement; i++) {
      const p = box.parentElement;
      if ((p.innerText || '').length > 3000) break;
      box = p;
      if (/\d{1,2}:\d{2}/.test(box.innerText || '')) break;
    }
    return box.innerText || '';
  });
}
"""


def extract_slots_from_dom(blocks: list[str]) -> tuple[list[str], bool]:
    slots, present = set(), False
    for block in dict.fromkeys(blocks):
        present = True
        for line in block.splitlines():
            line = line.strip()
            if line and TIME_RE.search(line):
                slots.add(line)
    return sorted(slots), present


# --------------------------------------------------------------------------- page check


def check_page(dump: bool = False) -> dict:
    from playwright.sync_api import sync_playwright

    json_payloads: list[tuple[str, object]] = []

    with sync_playwright() as p:
        launch_kwargs = {"headless": True, "args": ["--no-sandbox"]}
        exe = os.getenv("CHROMIUM_PATH")
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(locale="ar-SA", viewport={"width": 1280, "height": 2000})

        def on_response(resp):
            try:
                if "json" in (resp.headers.get("content-type") or ""):
                    json_payloads.append((resp.url, resp.json()))
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        blocks = page.evaluate(DOM_JS, TRAINER_KEYWORDS)

        if CLICK_TRAINER and blocks:
            # Many booking pages only reveal the trainer's slots after selecting them.
            try:
                for kw in TRAINER_KEYWORDS:
                    loc = page.get_by_text(kw, exact=False).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=5000)
                        try:
                            page.wait_for_load_state("networkidle", timeout=15000)
                        except Exception:
                            pass
                        page.wait_for_timeout(2000)
                        blocks = blocks + page.evaluate(DOM_JS, TRAINER_KEYWORDS)
                        break
            except Exception as e:
                log.info("Could not click trainer: %s", e)

        if dump:
            DEBUG_DIR.mkdir(exist_ok=True)
            page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)
            (DEBUG_DIR / "page.html").write_text(page.content(), encoding="utf-8")
            (DEBUG_DIR / "responses.json").write_text(
                json.dumps([{"url": u, "data": d} for u, d in json_payloads], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (DEBUG_DIR / "dom_blocks.txt").write_text("\n\n-----\n\n".join(blocks), encoding="utf-8")

        browser.close()

    json_slots: set[str] = set()
    for _, data in json_payloads:
        json_slots.update(extract_slots_from_json(data))
    dom_slots, present = extract_slots_from_dom(blocks)

    slots = sorted(json_slots) if json_slots else dom_slots
    return {
        "slots": slots,
        "trainer_present": present or bool(json_slots),
        "source": "api" if json_slots else "page",
        "json_responses": len(json_payloads),
    }


# --------------------------------------------------------------------------- API check

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
    "Referer": TARGET_URL,
}


def _api_requests() -> list[tuple[str, str]]:
    """(url, body) pairs to fetch; one per day when {date} is used, otherwise just one."""
    if "{date}" not in API_URL and "{date}" not in API_BODY:
        return [(API_URL, API_BODY)]
    days = [(today() + timedelta(days=i)).isoformat() for i in range(DAYS_AHEAD + 1)]
    return [(API_URL.replace("{date}", d), API_BODY.replace("{date}", d)) for d in days]


def check_api(dump: bool = False) -> dict:
    headers = {**DEFAULT_HEADERS, **API_HEADERS}
    session = requests.Session()
    payloads, slots = [], set()
    for url, body in _api_requests():
        resp = session.request(API_METHOD, url, headers=headers, data=body.encode("utf-8") if body else None, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        payloads.append({"url": url, "data": data})
        slots.update(extract_slots_from_json(data))

    if dump:
        DEBUG_DIR.mkdir(exist_ok=True)
        (DEBUG_DIR / "api_responses.json").write_text(json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8")

    present = any(_contains_keyword(p["data"]) for p in payloads)
    return {"slots": sorted(slots), "trainer_present": present, "source": "api-direct", "json_responses": len(payloads)}


def check(dump: bool = False) -> dict:
    direct = check_api if API_URL else check_action if USE_SERVER_ACTION else None
    if direct:
        try:
            return direct(dump)
        except Exception as e:
            if not BROWSER_FALLBACK:
                raise
            log.warning("Direct check failed (%s); falling back to the browser", e)
    return check_page(dump)


def find_api() -> None:
    """Open the booking page, record every data request it makes and report which ones mention the trainer.

    Covers plain JSON APIs as well as Next.js data (server-rendered HTML, RSC payloads, server actions).
    Also saves a screenshot and the visible page text to ./debug.
    """
    from playwright.sync_api import sync_playwright

    found = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(locale="ar-SA", viewport={"width": 1280, "height": 2000})

        def on_response(resp):
            req = resp.request
            if req.resource_type not in {"document", "fetch", "xhr"} or "sentry" in (req.post_data or ""):
                return
            try:
                text = resp.text()
            except Exception:
                return
            ctype = (resp.headers.get("content-type") or "").split(";")[0]
            slots = []
            if "json" in ctype:
                try:
                    slots = extract_slots_from_json(json.loads(text))
                except Exception:
                    pass
            found.append({
                "method": req.method,
                "url": resp.url,
                "type": req.resource_type,
                "ctype": ctype,
                "size": len(text),
                "body": req.post_data or "",
                "next_action": req.headers.get("next-action", ""),
                "mentions_trainer": has_keyword(text),
                "slots": slots,
            })

        page.on("response", on_response)
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
        except Exception:
            pass
        page.wait_for_timeout(3000)

        DEBUG_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)
        page_text = page.inner_text("body")
        (DEBUG_DIR / "page_text.txt").write_text(page_text, encoding="utf-8")
        on_page = has_keyword(page_text)

        clicked = False
        if CLICK_TRAINER and on_page:
            for kw in TRAINER_KEYWORDS:
                loc = page.get_by_text(kw, exact=False).first
                try:
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=5000)
                        page.wait_for_timeout(4000)
                        page.screenshot(path=str(DEBUG_DIR / "after_click.png"), full_page=True)
                        (DEBUG_DIR / "after_click_text.txt").write_text(page.inner_text("body"), encoding="utf-8")
                        clicked = True
                        break
                except Exception:
                    pass
        browser.close()

    print(f"Trainer name visible on the page: {'YES' if on_page else 'NO'}" + (" (clicked it)" if clicked else ""))
    print(f"Saw {len(found)} page/data request(s). Ones whose response mentions the trainer are marked with ★\n")
    for r in sorted(found, key=lambda r: not r["mentions_trainer"]):
        mark = "★" if r["mentions_trainer"] else " "
        print(f"{mark} {r['method']} [{r['type']}, {r['ctype'] or '?'}, {r['size']} chars] {r['url']}")
        if r["next_action"]:
            print(f"    next-action: {r['next_action']}")
        if r["body"]:
            print(f"    body: {r['body'][:300]}")
        if r["slots"]:
            print(f"    sessions found: {len(r['slots'])}, e.g. {r['slots'][0]}")
    print(f"\nScreenshot and page text saved in {DEBUG_DIR.resolve()}")
    preview = "\n".join(line for line in page_text.splitlines() if line.strip())[:1500]
    print("\n----- page text (first 1500 chars) -----\n" + preview)


# --------------------------------------------------------------------------- Next.js server action

ACTION_FILE = Path(os.getenv("ACTION_FILE", "action.json"))
DATE_ARG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RSC_LINE_RE = re.compile(r"^([0-9a-f]+):(.*)$")
STAFF_RE = re.compile(r"(?:المدرب|المدربة|الكابتن|كابتن|Coach)[^\"\\\n]{1,60}")


def discover_action() -> dict:
    """Load the booking page in a browser and record the server action it calls to fetch a day's times."""
    from playwright.sync_api import sync_playwright

    captured = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(locale="ar-SA")

        def on_request(req):
            action_id = req.headers.get("next-action")
            if not action_id or captured:
                return
            try:
                args = json.loads(req.post_data or "")
            except Exception:
                return
            if isinstance(args, list) and any(isinstance(a, str) and DATE_ARG_RE.match(a) for a in args):
                keep = {"next-action", "next-router-state-tree", "content-type", "accept"}
                captured.update({
                    "url": req.url,
                    "headers": {k: v for k, v in req.headers.items() if k.lower() in keep},
                    "args": args,
                })

        page.on("request", on_request)
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        browser.close()

    if not captured:
        raise RuntimeError("Could not find the booking server action on the page")
    ACTION_FILE.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
    return captured


def load_action(refresh: bool = False) -> dict:
    if not refresh and ACTION_FILE.exists():
        return json.loads(ACTION_FILE.read_text(encoding="utf-8"))
    return discover_action()


def parse_rsc(text: str) -> list:
    """Split a React Server Components response into its JSON rows."""
    rows = []
    for line in text.splitlines():
        m = RSC_LINE_RE.match(line)
        if not m:
            continue
        try:
            rows.append(json.loads(m.group(2)))
        except Exception:
            pass
    return rows


def call_action(action: dict, day: str) -> str:
    args = [day if isinstance(a, str) and DATE_ARG_RE.match(a) else a for a in action["args"]]
    headers = {**DEFAULT_HEADERS, **action["headers"], "Origin": "https://netacademy.sa"}
    headers.setdefault("content-type", "text/plain;charset=UTF-8")
    headers["accept"] = "text/x-component"
    resp = requests.post(action["url"], headers=headers, data=json.dumps(args, ensure_ascii=False).encode("utf-8"), timeout=30)
    resp.raise_for_status()
    if "x-component" not in resp.headers.get("content-type", ""):
        raise RuntimeError(f"Unexpected response type {resp.headers.get('content-type')}")
    resp.encoding = "utf-8"  # RSC is always UTF-8; requests would otherwise guess Latin-1
    return resp.text


def _fmt_time(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":")[:2])
    return f"{(h % 12) or 12}:{m:02d} {'ص' if h < 12 else 'م'}"


def extract_booking_slots(rows: list) -> list[str] | None:
    """Read the academy's booking slots: [{booking_date, start_time, end_time, is_available, resource_names}].

    Returns None when the response does not have that shape, so the generic extractor can take over.
    """
    slots, recognised = [], False

    def walk(node):
        nonlocal recognised
        if isinstance(node, dict):
            if "resource_names" in node and "start_time" in node:
                recognised = True
                names = node.get("resource_names") or []
                if node.get("is_available", True) and any(has_keyword(str(n)) for n in names):
                    day = node.get("booking_date", "")
                    start, end = node.get("start_time", ""), node.get("end_time", "")
                    try:
                        when = f"{_fmt_time(start)} – {_fmt_time(end)}" if end else _fmt_time(start)
                    except ValueError:
                        when = f"{start} – {end}"
                    label = f"{_weekday_ar(day)} {day}" if day else ""
                    slots.append(f"{label} • {when}".strip(" •"))
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(rows)
    return slots if recognised else None


def check_action(dump: bool = False) -> dict:
    """Ask the site's booking server action for each of the coming days and collect the trainer's times."""
    action, refreshed = load_action(), False
    slots, present_days = [], []  # in date/time order
    for i in range(DAYS_AHEAD + 1):
        day = (today() + timedelta(days=i)).isoformat()
        try:
            text = call_action(action, day)
        except Exception as e:
            if refreshed:
                raise
            # The action id changes whenever the site is redeployed; look it up again once.
            log.info("Server action call failed (%s); rediscovering it", e)
            action, refreshed = load_action(refresh=True), True
            text = call_action(action, day)
        if dump:
            DEBUG_DIR.mkdir(exist_ok=True)
            (DEBUG_DIR / f"day-{day}.txt").write_text(text, encoding="utf-8")
        if not has_keyword(text):
            continue
        rows = parse_rsc(text)
        day_slots = extract_booking_slots(rows)
        if day_slots is not None:
            # Known response shape: trust it, including "no free times for this coach".
            slots.extend(day_slots)
            if day_slots:
                present_days.append(day)
            continue
        present_days.append(day)
        day_slots = extract_slots_from_json(rows)
        if day_slots:
            slots.extend(s if day in s else f"{day} | {s}" for s in day_slots)
        else:
            # Unknown shape: the coach is mentioned for this day but the times could not be
            # matched to them, so report the day itself.
            slots.append(f"{day} ({_weekday_ar(day)}): فيه حصص متاحة")
    return {"slots": list(dict.fromkeys(slots)), "trainer_present": bool(present_days), "source": "server-action",
            "json_responses": DAYS_AHEAD + 1}


_WEEKDAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def _weekday_ar(day: str) -> str:
    return _WEEKDAYS_AR[date.fromisoformat(day).weekday()]


def probe() -> None:
    """Replay the booking server action for the coming days and save the raw responses for inspection."""
    action = load_action(refresh=True)
    print(f"Server action found: {action['headers'].get('next-action')}\nargs: {json.dumps(action['args'], ensure_ascii=False)}\n")
    DEBUG_DIR.mkdir(exist_ok=True)
    sample_shown = False
    for i in range(DAYS_AHEAD + 1):
        day = (today() + timedelta(days=i)).isoformat()
        try:
            text = call_action(action, day)
        except Exception as e:
            print(f"{day}: FAILED {e}")
            continue
        (DEBUG_DIR / f"day-{day}.txt").write_text(text, encoding="utf-8")
        staff = sorted({s.strip() for s in STAFF_RE.findall(text)})
        mark = "★" if has_keyword(text) else " "
        print(f"{mark} {day}: {len(text)} chars, {len(parse_rsc(text))} rows, staff: {', '.join(staff) or '-'}")
        if not sample_shown and staff:
            sample_shown = True
            sample = text
    if sample_shown:
        print(f"\n----- raw response sample (first 2500 chars) -----\n{sample[:2500]}")
    print(f"\nRaw responses saved in {DEBUG_DIR.resolve()}")


# --------------------------------------------------------------------------- state + telegram


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"seen": [], "chat_ids": [], "failures": 0, "last_check": None, "last_slots": [], "update_offset": 0}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def fingerprint(slot: str) -> str:
    return hashlib.sha1(slot.encode("utf-8")).hexdigest()[:16]


class TelegramError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def tg(method: str, **params):
    # Errors are re-raised without the request URL, because the URL contains the bot token.
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=params, timeout=60)
    except requests.RequestException as e:
        raise TelegramError(f"{method}: {str(e).replace(BOT_TOKEN, '***')}") from None
    try:
        data = r.json()
    except ValueError:
        data = {}
    if not r.ok or not data.get("ok"):
        raise TelegramError(f"{method}: HTTP {r.status_code} {data.get('description', '')}".strip(), r.status_code)
    return data


def broadcast(state: dict, text: str) -> None:
    chat_ids = set(ENV_CHAT_IDS) | {str(c) for c in state.get("chat_ids", [])}
    if not chat_ids:
        log.warning("No chat id configured; send /start to the bot or set TELEGRAM_CHAT_ID.")
    for chat_id in chat_ids:
        try:
            tg("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True)
        except Exception as e:
            log.error("Telegram send to %s failed: %s", chat_id, e)


def format_slots(slots: list[str], limit: int = 30) -> str:
    lines = [f"• {s}" for s in slots[:limit]]
    if len(slots) > limit:
        lines.append(f"… و {len(slots) - limit} غيرها")
    return "\n".join(lines)


def run_check(state: dict, notify: bool = True) -> dict:
    try:
        result = check()
    except Exception as e:
        state["failures"] = state.get("failures", 0) + 1
        log.error("Check failed (%d in a row): %s", state["failures"], e)
        if notify and state["failures"] == FAILURE_ALERT_AFTER:
            broadcast(state, f"⚠️ فشل فتح صفحة الحجز {FAILURE_ALERT_AFTER} مرات متتالية.\n{e}")
        save_state(state)
        return {"error": str(e)}

    state["failures"] = 0
    state["last_check"] = datetime.now().isoformat(timespec="seconds")
    state["last_slots"] = result["slots"]

    seen = set(state.get("seen", []))
    current = {fingerprint(s): s for s in result["slots"]}
    new = [s for fp, s in current.items() if fp not in seen]

    # A trainer with no visible times but now present on the page is also worth flagging.
    if result["trainer_present"] and not result["slots"]:
        current = {"__present__": "present"}
        if "__present__" not in seen and notify:
            broadcast(state, f"🎾 ظهر اسم المدرب {TRAINER_LABEL} في صفحة الحجز (ما قدرت أحدد الأوقات، افتح الرابط):\n{TARGET_URL}")

    if new and notify:
        broadcast(state, f"🎾 نزلت حصص جديدة للمدرب {TRAINER_LABEL}:\n\n{format_slots(new)}\n\nاحجز الآن:\n{TARGET_URL}")

    # Only remember what is currently visible, so a slot that reappears is announced again.
    state["seen"] = list(current.keys())
    save_state(state)
    log.info("Check done: %d slot(s), %d new, source=%s", len(result["slots"]), len(new), result["source"])
    return {**result, "new": new}


def handle_updates(state: dict, timeout: int) -> None:
    try:
        resp = tg("getUpdates", offset=state.get("update_offset", 0), timeout=timeout)
    except Exception as e:
        log.error("getUpdates failed: %s", e)
        time.sleep(min(timeout, 10))
        return

    for upd in resp.get("result", []):
        state["update_offset"] = upd["update_id"] + 1
        msg = upd.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip().split("@")[0]
        if not chat_id:
            continue

        if text == "/start":
            if chat_id not in state["chat_ids"]:
                state["chat_ids"].append(chat_id)
            tg("sendMessage", chat_id=chat_id, text=(
                f"✅ تم الاشتراك. بنبهك أول ما تنزل حصص للمدرب {TRAINER_LABEL}.\n"
                f"الفحص كل {CHECK_INTERVAL // 60} دقيقة.\n\n"
                "/check فحص الآن\n/status آخر نتيجة\n/stop إيقاف التنبيهات"
            ))
        elif text == "/stop":
            state["chat_ids"] = [c for c in state["chat_ids"] if c != chat_id]
            tg("sendMessage", chat_id=chat_id, text="🛑 تم إيقاف التنبيهات لهذه المحادثة.")
        elif text == "/status":
            slots = state.get("last_slots", [])
            body = format_slots(slots) if slots else "لا توجد حصص متاحة حالياً."
            tg("sendMessage", chat_id=chat_id, text=f"آخر فحص: {state.get('last_check') or '—'}\n\n{body}")
        elif text == "/check":
            tg("sendMessage", chat_id=chat_id, text="⏳ جاري الفحص…")
            res = run_check(state)
            if "error" in res:
                reply = f"❌ فشل الفحص: {res['error']}"
            elif res["slots"]:
                reply = f"الحصص المتاحة الآن:\n\n{format_slots(res['slots'])}"
            else:
                reply = "لا توجد حصص متاحة حالياً."
            tg("sendMessage", chat_id=chat_id, text=reply)
    save_state(state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run a single check and exit")
    parser.add_argument("--dump", action="store_true", help="save debug files to ./debug and print results")
    parser.add_argument("--find-api", action="store_true", help="list the page's API requests that mention the trainer")
    parser.add_argument("--probe", action="store_true", help="replay the booking server action for the coming days")
    args = parser.parse_args()

    if args.probe:
        probe()
        return

    if args.find_api:
        find_api()
        return

    if args.dump:
        result = check(dump=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"Debug files written to {DEBUG_DIR.resolve()}")
        return

    if not BOT_TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN is not set (see .env.example)")

    try:
        me = tg("getMe")["result"]
    except TelegramError as e:
        if e.status in (401, 404):
            sys.exit(
                f"Telegram rejected the bot token ({e}).\n"
                "Check TELEGRAM_BOT_TOKEN in .env: it must be the full token from @BotFather, "
                "like 123456789:AA..., with no spaces or quotes."
            )
        sys.exit(f"Could not reach Telegram: {e}")
    log.info("Logged in to Telegram as @%s - send it /start", me.get("username"))

    state = load_state()
    state.setdefault("chat_ids", [])

    if args.once:
        res = run_check(state)
        sys.exit(1 if "error" in res else 0)

    mode = "custom API" if API_URL else "server action" if USE_SERVER_ACTION else "browser"
    log.info("Watching %s for %s every %ss, every %ss around %s (%s mode)", TARGET_URL, TRAINER_LABEL,
             CHECK_INTERVAL, FAST_CHECK_INTERVAL, RELEASE_TIME, mode)
    next_check = 0.0
    while True:
        if time.time() >= next_check:
            run_check(state)
            next_check = time.time() + current_interval()
        handle_updates(state, timeout=int(max(1, min(30, next_check - time.time()))))


if __name__ == "__main__":
    main()
