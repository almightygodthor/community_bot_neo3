#!/usr/bin/env python3
"""Realme GT Neo 3 OTA Community Bot."""

import asyncio
import html
import logging
import os
import time
import json
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import requests

from ota_engine import (
    VARIANTS,
    REGIONS,
    get_latest,
    get_generation,
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GH_TOKEN = os.getenv("GITHUB_TOKEN", "")
GH_REPO = os.getenv("GITHUB_REPOSITORY", "almightygodthor/community_bot_neo3")
GH_REF = os.getenv("GITHUB_REF_NAME") or os.getenv("GITHUB_REF", "main").removeprefix("refs/heads/")
BOT_WORKFLOW = "telegram-bot.yml"
WORKER_SECONDS = 60 * 60 * 5 + 40 * 60
BOT_NAME = os.getenv("BOT_NAME", "GT Neo 3 OTA")
VERSION = os.getenv("BOT_VERSION", "1.0.0")
PORT = int(os.getenv("PORT", "8080"))
HEALTH_PORT = int(os.getenv("HEALTH_PORT", str(PORT)))

API = f"https://api.telegram.org/bot{TOKEN}"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "GTNeo3-OTA-Community-Bot/1.0"})
SESSIONS = {}
CACHE = {}
LOG = logging.getLogger("neo3bot")

DOWNGRADE_FILE = os.path.join(os.path.dirname(__file__), "data", "downgrades.json")
try:
    with open(DOWNGRADE_FILE, "r", encoding="utf-8") as fh:
        DOWNGRADES = json.load(fh)
except (OSError, json.JSONDecodeError):
    DOWNGRADES = {}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ok","service":"gt-neo3-ota-bot"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def start_health():
    server = HTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
    Thread(target=server.serve_forever, daemon=True).start()


def tg(method, payload=None, timeout=35):
    for attempt in range(3):
        try:
            r = SESSION.post(f"{API}/{method}", json=payload or {}, timeout=timeout)
            data = r.json()
            if r.status_code == 429:
                retry = int(data.get("parameters", {}).get("retry_after", 3))
                time.sleep(min(retry, 15))
                continue
            if not data.get("ok"):
                raise RuntimeError(data.get("description", "Telegram API error"))
            return data["result"]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 + attempt * 2)


def send(chat_id, text, keyboard=None, reply_markup=None):
    markup = reply_markup
    if keyboard is not None:
        markup = {"inline_keyboard": keyboard}
    return tg("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        **({"reply_markup": markup} if markup else {}),
    })


def edit(chat_id, message_id, text, keyboard=None):
    return tg("editMessageText", {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        **({"reply_markup": {"inline_keyboard": keyboard}} if keyboard else {}),
    })


def answer_callback(callback_id, text=None):
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = False
    try:
        tg("answerCallbackQuery", payload)
    except Exception:
        pass


def button(text, data):
    return {"text": text, "callback_data": data}


def home_keyboard():
    return [
        [button("GT Neo 3 • 80W", "variant:80"), button("GT Neo 3 • 150W", "variant:150")],
        [button("🔄 Refresh", "home:refresh"), button("ℹ️ About", "home:about")],
    ]


def variant_keyboard(v):
    return [
        [button("Latest OTA", f"latest:{v}"), button("Regions", f"regions:{v}")],
        [button("RUI 3 • Android 12", f"generation:{v}:3")],
        [button("RUI 4 • Android 13", f"generation:{v}:4")],
        [button("RUI 5 • Android 14", f"generation:{v}:5")],
        [button("Downgrades", f"down:{v}")],
        [button("Home", "home:main")],
    ]


def region_keyboard(v):
    rows = []
    current = []
    for code, name in REGIONS[v]:
        current.append(button(name, f"latest:{v}:{code}"))
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append([button("⬅️ Back", f"variant:{v}")])
    return rows


def generation_region_keyboard(v, generation):
    rows = []
    current = []
    for code, name in REGIONS[v]:
        current.append(button(name, f"generation_run:{v}:{generation}:{code}"))
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append([button("Back", f"variant:{v}")])
    return rows


def format_variant(v):
    x = VARIANTS[v]
    return (
        f"<b>{html.escape(x['name'])}</b>\n"
        f"Model: <code>{x['model']}</code>  •  China: <code>{x['cn_model']}</code>"
    )


def format_size(value):
    try:
        size = float(value)
        if size <= 0:
            return "N/A"
        return f"{size / 1_000_000_000:.2f} GB"
    except (TypeError, ValueError):
        return "N/A"


def _box_line(text, width=30):
    text = str(text)
    if len(text) > width:
        text = text[: max(0, width - 1)] + "…"
    return f"│ {text.ljust(width)} │"


def _box_wrapped(label, value, width=30):
    import textwrap

    value = str(value)
    prefix = f"{label:<9}"
    available = max(1, width - len(prefix))
    chunks = textwrap.wrap(value, width=available, break_long_words=True, break_on_hyphens=False) or [""]
    lines = [f"{prefix}{chunks[0]}"]
    lines.extend(f"{'':9}{chunk}" for chunk in chunks[1:])
    return [_box_line(line, width) for line in lines]


def format_result(result, v, region, generation=None):
    x = VARIANTS[v]
    rname = dict(REGIONS[v]).get(region, region.upper())
    family = None
    if generation:
        family = {
            "3": "RUI 3 • Android 12",
            "4": "RUI 4 • Android 13",
            "5": "RUI 5 • Android 14",
        }[generation]

    build = result.get("ota_version", "N/A")
    software = result.get("version", "N/A")
    patch = result.get("security_patch", "N/A")
    released = str(result.get("published_time", "N/A")).split(" ")[0]
    size = format_size(result.get("size")) if result.get("size") else "N/A"

    width = 30
    border = "─" * (width + 2)
    lines = [
        f"┌{border}┐",
        _box_line(x["name"], width),
        f"├{border}┤",
        _box_line(rname, width),
    ]

    if family:
        lines.append(_box_line(family, width))

    lines.extend([
        f"├{border}┤",
        _box_line("BUILD", width),
    ])
    lines.extend(_box_wrapped("", build, width))

    lines.extend([
        f"├{border}┤",
    ])
    lines.extend(_box_wrapped("SOFTWARE", software, width))
    lines.extend(_box_wrapped("PATCH", patch, width))
    lines.extend(_box_wrapped("RELEASED", released, width))
    lines.extend(_box_wrapped("SIZE", size, width))
    lines.extend([
        f"├{border}┤",
        _box_line("OFFICIAL STOCK OTA", width),
        f"└{border}┘",
    ])

    return "<pre>" + "\n".join(lines) + "</pre>\n\n<b>🚨 Contains preloader_raw.img</b>"


def result_keyboard(result, v, region, generation=None):
    rows = []
    if result.get("link", "").startswith("http"):
        rows.append([{"text": "Download OTA", "url": result["link"]}])
    if result.get("original_link", "").startswith("http") and result["original_link"] != result.get("link"):
        rows.append([{"text": "Original OTA", "url": result["original_link"]}])
    refresh = f"generation_run:{v}:{generation}:{region}" if generation else f"latest:{v}:{region}"
    rows.append([button("Refresh", refresh), button("Regions", f"regions:{v}")])
    rows.append([button("Back", f"variant:{v}"), button("Home", "home:main")])
    return rows


def run_generation(chat_id, message_id, v, region, generation):
    key = f"{v}:{region}:rui{generation}"
    now = time.time()
    if key in CACHE and now - CACHE[key][0] < 300:
        result = CACHE[key][1]
    else:
        result = get_generation(v, region, generation)
        CACHE[key] = (now, result)

    if not result:
        edit(chat_id, message_id, "No matching stock OTA was returned.", [
            [button("Try Again", f"generation_run:{v}:{generation}:{region}")],
            [button("Back", f"variant:{v}")],
        ])
        return

    if isinstance(result, dict) and result.get("error"):
        edit(chat_id, message_id, f"<b>OTA query failed</b>\n\n<code>{html.escape(result['error'])}</code>", [
            [button("Try Again", f"generation_run:{v}:{generation}:{region}")],
            [button("Back", f"variant:{v}")],
        ])
        return

    edit(
        chat_id,
        message_id,
        format_result(result, v, region, generation),
        result_keyboard(result, v, region, generation),
    )


def run_latest(chat_id, message_id, v, region=None):
    key = f"{v}:{region or 'all'}"
    now = time.time()
    if key in CACHE and now - CACHE[key][0] < 300:
        result = CACHE[key][1]
    else:
        result = get_latest(v, region)
        CACHE[key] = (now, result)

    if not result:
        text = "⚠️ <b>No stock OTA was returned.</b>\n\nThe official server may be rate-limiting the query or that region may have no currently queryable package."
        edit(chat_id, message_id, text, [
            [button("🔄 Try Again", f"latest:{v}:{region}" if region else f"latest:{v}")],
            [button("⬅️ Back", f"variant:{v}")],
        ])
        return

    if isinstance(result, dict) and result.get("error"):
        edit(chat_id, message_id, f"⚠️ <b>OTA query failed</b>\n\n<code>{html.escape(result['error'])}</code>", [
            [button("🔄 Try Again", f"latest:{v}:{region}" if region else f"latest:{v}")],
            [button("⬅️ Back", f"variant:{v}")],
        ])
        return

    edit(chat_id, message_id, format_result(result, v, region or result["region"]), result_keyboard(result, v, region or result["region"]))


def handle_callback(q):
    callback_id = q["id"]
    data = q.get("data", "")
    msg = q.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    if not chat_id or not message_id:
        return

    answer_callback(callback_id)
    try:
        if data == "home:main" or data == "home:refresh":
            edit(chat_id, message_id, f"👋 <b>{html.escape(BOT_NAME)}</b>\n\nOfficial stock OTA finder for the <b>realme GT Neo 3</b> community.\n\nChoose your variant:", home_keyboard())
            return

        if data == "home:about":
            edit(chat_id, message_id,
                 f"ℹ️ <b>{html.escape(BOT_NAME)} {html.escape(VERSION)}</b>\n\n"
                 "Built for the realme GT Neo 3 80W / 150W community.\n"
                 "• Official OTA query\n• Region-aware model mapping\n• RUI generation lookup\n• Refreshable download links\n• Downgrade catalog\n\n"
                 "Dynamic download URLs can expire; use <b>Refresh</b> to obtain a fresh link.",
                 [[button("⬅️ Back", "home:main")]])
            return

        if data.startswith("variant:"):
            v = data.split(":", 1)[1]
            edit(chat_id, message_id, format_variant(v) + "\n\nChoose an action:", variant_keyboard(v))
            SESSIONS[chat_id] = {"variant": v}
            return

        if data.startswith("regions:"):
            v = data.split(":", 1)[1]
            edit(chat_id, message_id, f"🌍 <b>{html.escape(VARIANTS[v]['name'])}</b>\n\nSelect a region:", region_keyboard(v))
            return

        if data.startswith("latest:"):
            parts = data.split(":")
            v = parts[1]
            region = parts[2].lower() if len(parts) > 2 else None
            if not region:
                edit(chat_id, message_id, f"🌍 <b>{html.escape(VARIANTS[v]['name'])}</b>\n\nSelect the region to query:", region_keyboard(v))
                return
            edit(chat_id, message_id, "⏳ <b>Querying the official OTA service…</b>\n\nThis can take a few seconds.", [
                [button("⬅️ Cancel", f"variant:{v}")]
            ])
            Thread(target=run_latest, args=(chat_id, message_id, v, region), daemon=True).start()
            return

        if data.startswith("generation:"):
            _, v, generation = data.split(":")
            labels = {"3": "RUI 3 • Android 12", "4": "RUI 4 • Android 13", "5": "RUI 5 • Android 14"}
            edit(
                chat_id,
                message_id,
                f"<b>{html.escape(labels[generation])}</b>\n\n"
                f"{html.escape(VARIANTS[v]['name'])}\n"
                "Select your region. The bot will fetch the latest matching build automatically.",
                generation_region_keyboard(v, generation),
            )
            return

        if data.startswith("generation_run:"):
            _, v, generation, region = data.split(":")
            labels = {"3": "RUI 3 • Android 12", "4": "RUI 4 • Android 13", "5": "RUI 5 • Android 14"}
            edit(
                chat_id,
                message_id,
                f"<b>{html.escape(labels[generation])}</b>\n"
                f"{html.escape(dict(REGIONS[v]).get(region, region.upper()))}\n\n"
                "Fetching the latest matching stock OTA…",
                [[button("Cancel", f"variant:{v}")]],
            )
            Thread(target=run_generation, args=(chat_id, message_id, v, region, generation), daemon=True).start()
            return

        if data.startswith("down:"):
            v = data.split(":", 1)[1]
            packages = DOWNGRADES.get(v, {}).get("packages", [])
            rows = []
            lines = [
                f"<b>Downgrade packages — {html.escape(VARIANTS[v]['name'])}</b>",
                "",
                "Direct links are provided below. The bot does not fetch or validate these files.",
            ]
            for package in packages:
                title = html.escape(package.get("title", "Downgrade package"))
                region = html.escape(package.get("region", ""))
                version = html.escape(package.get("version", ""))
                lines.append(f"\n<b>{title}</b>\n{region}\n<code>{version}</code>")
                url = package.get("url", "")
                if url.startswith("http"):
                    button_text = f"{package.get('title', 'Download')} • {package.get('region', 'Unknown region')}"
                    rows.append([{"text": button_text, "url": url}])
            if not packages:
                lines = [
                    f"<b>Downgrade packages — {html.escape(VARIANTS[v]['name'])}</b>",
                    "",
                    "No downgrade packages are configured.",
                ]
            rows.append([button("Back", f"variant:{v}"), button("Home", "home:main")])
            edit(chat_id, message_id, "\n".join(lines), rows)
            return
    except Exception as e:
        LOG.exception("callback failed")
        try:
            edit(chat_id, message_id, "⚠️ Something went wrong. Please use <b>Refresh</b> or return to Home.", [[button("🏠 Home", "home:main")]])
        except Exception:
            pass


def handle_message(message):
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    command = text.split(maxsplit=1)[0].split("@")[0].lower() if text else ""
    if command == "/stockota":
        SESSIONS[chat_id] = {}
        send(chat_id,
             f"👋 <b>Welcome to {html.escape(BOT_NAME)}</b>\n\n"
             "A clean community bot for <b>realme GT Neo 3</b> stock firmware.\n\n"
             "Everything is handled through buttons — choose your charging variant below.",
             home_keyboard())
        return

    send(chat_id, "Use <b>/stockota</b> to open the GT Neo 3 OTA menu.", [[button("Open Stock OTA", "home:main")]])


def schedule_next_worker():
    if not GH_TOKEN:
        LOG.error("GITHUB_TOKEN is not available; cannot schedule next worker")
        return
    url = f"https://api.github.com/repos/{GH_REPO}/actions/workflows/{urllib.parse.quote(BOT_WORKFLOW, safe='')}/dispatches"
    payload = json.dumps({"ref": GH_REF}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GH_TOKEN}",
            "X-GitHub-Api-Version": "2026-03-10",
            "Content-Type": "application/json",
            "User-Agent": "GTNeo3-OTA-GitHub-Worker",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            if response.status not in (200, 201, 202, 204):
                raise RuntimeError(f"GitHub returned HTTP {response.status}")
        LOG.info("Queued next Telegram worker")
    except Exception:
        LOG.exception("Failed to queue next Telegram worker")


def poll():
    offset = 0
    deadline = time.monotonic() + WORKER_SECONDS
    tg("deleteWebhook", {"drop_pending_updates": True})
    tg("setMyCommands", {"commands": [{"command": "stockota", "description": "Open the GT Neo 3 Stock OTA menu"}]})

    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()))
        timeout = min(25, remaining)
        try:
            updates = tg("getUpdates", {"timeout": timeout, "offset": offset}, timeout=timeout + 10)
            for u in updates:
                offset = u["update_id"] + 1
                if "callback_query" in u:
                    handle_callback(u["callback_query"])
                elif "message" in u:
                    handle_message(u["message"])
        except Exception:
            LOG.exception("polling failure")
            time.sleep(5)

    schedule_next_worker()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    start_health()
    poll()
