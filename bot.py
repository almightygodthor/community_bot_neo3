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
        [button("📱 GT Neo 3 80W", "variant:80"), button("⚡ GT Neo 3 150W", "variant:150")],
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
        units = ("B", "KB", "MB", "GB", "TB")
        for unit in units:
            if size < 1024 or unit == "TB":
                return f"{size:.2f} {unit}" if unit != "B" else f"{size:.0f} {unit}"
            size /= 1024
    except (TypeError, ValueError):
        return "N/A"
    return "N/A"


def format_result(result, v, region, generation=None):
    x = VARIANTS[v]
    rname = dict(REGIONS[v]).get(region, region.upper())
    lines = [
        f"<b>{html.escape(x['name'])}</b>",
        f"──────────────",
        f"{html.escape(rname)}",
        "",
        f"Version   <code>{html.escape(result.get('ota_version', 'N/A'))}</code>",
        f"Software  <code>{html.escape(result.get('version', 'N/A'))}</code>",
        f"Patch     <code>{html.escape(result.get('security_patch', 'N/A'))}</code>",
    ]
    if generation:
        family = {"3": "RUI 3 • Android 12", "4": "RUI 4 • Android 13", "5": "RUI 5 • Android 14"}[generation]
        lines.insert(2, f"<b>{family}</b>")
        lines.insert(3, "")
    if result.get("published_time"):
        lines.append(f"Released  <code>{html.escape(result['published_time'])}</code>")
    if result.get("size"):
        lines.append(f"Size      <code>{html.escape(format_size(result['size']))}</code>")
    lines += ["", "Official stock OTA"]
    return "\n".join(lines)


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
                 "• Official OTA query\n• Region-aware model mapping\n• Refreshable download links\n• Version lookup\n• Downgrade catalog\n\n"
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

        if data.startswith("lookup:"):
            v = data.split(":", 1)[1]
            edit(chat_id, message_id, f"🔎 <b>Version lookup — {html.escape(VARIANTS[v]['name'])}</b>\n\nFirst select the region:", lookup_region_keyboard(v))
            SESSIONS[chat_id] = {"variant": v, "await_region": True}
            return

        if data.startswith("lookup_region:"):
            _, v, region = data.split(":")
            SESSIONS[chat_id] = {"variant": v, "region": region, "await_version": True}
            send(chat_id, f"🔎 <b>Version lookup — {html.escape(VARIANTS[v]['name'])} / {html.escape(dict(REGIONS[v]).get(region, region.upper()))}</b>\n\nSend the full OTA version, for example:\n<code>RMX3561_11.F.38_2380_202501081908</code>\n\nI will query the official service for that exact build.") 
            return

        if data.startswith("guide:"):
            v = data.split(":", 1)[1]
            edit(chat_id, message_id,
                 f"📚 <b>Version guide</b>\n\n"
                 f"{html.escape(VARIANTS[v]['name'])} uses the official OTA naming families such as <code>_11.A</code>, <code>_11.C</code> and <code>_11.F</code>.\n"
                 "Use <b>Latest OTA</b> for the newest queryable build, or <b>Version Lookup</b> for an exact historical version.\n\n"
                 "The bot does not invent historical URLs; it only presents links returned by the OTA source.",
                 [[button("🔎 Version Lookup", f"lookup:{v}")], [button("⬅️ Back", f"variant:{v}")]])
            return

        if data.startswith("down:"):
            v = data.split(":", 1)[1]
            edit(chat_id, message_id,
                 f"⬇️ <b>Downgrade packages — {html.escape(VARIANTS[v]['name'])}</b>\n\n"
                 "The downgrade catalog is prepared in the bot, but the actual region/build links are not populated yet.\n\n"
                 "Once the community downgrade links are provided, they will appear here with the same button-based UI.",
                 [[button("🔄 Refresh", f"down:{v}")], [button("⬅️ Back", f"variant:{v}")]])
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

    if text.split()[0].split("@")[0].lower() == "/stockota":
        SESSIONS[chat_id] = {}
        send(chat_id,
             f"👋 <b>Welcome to {html.escape(BOT_NAME)}</b>\n\n"
             "A clean community bot for <b>realme GT Neo 3</b> stock firmware.\n\n"
             "Everything is handled through buttons — choose your charging variant below.",
             home_keyboard())
        return

    session = SESSIONS.get(chat_id, {})
    if session.get("await_version") and text and not text.startswith("/"):
        v = session["variant"]
        SESSIONS[chat_id] = {"variant": v}
        region = session.get("region", "in")
        send(chat_id, "⏳ <b>Checking that exact OTA version…</b>")
        try:
            result = get_version(v, region, text)
            if result.get("error"):
                send(chat_id, f"⚠️ <b>Lookup failed</b>\n\n<code>{html.escape(result['error'])}</code>", [[button("🔎 Try another", f"lookup:{v}")], [button("⬅️ Back", f"variant:{v}")]])
            else:
                send(chat_id, format_result(result, v, region), result_keyboard(result, v, region))
        except Exception as e:
            send(chat_id, f"⚠️ <b>Lookup failed</b>\n\n<code>{html.escape(str(e))}</code>")
        return

    send(chat_id, "Use <b>/stockota</b> to open the GT Neo 3 OTA menu.", [[button("📦 Open Stock OTA", "home:main")]])


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
