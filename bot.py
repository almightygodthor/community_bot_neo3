#!/usr/bin/env python3
"""Realme GT Neo 3 OTA Community Bot."""

import asyncio
import html
import logging
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import requests

from ota_engine import (
    VARIANTS,
    REGIONS,
    get_latest,
    get_version,
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
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
        [button("📦 Latest OTA", f"latest:{v}"), button("🌍 Regions", f"regions:{v}")],
        [button("🔎 Version Lookup", f"lookup:{v}"), button("📚 Version Guide", f"guide:{v}")],
        [button("⬇️ Downgrades", f"down:{v}")],
        [button("🏠 Home", "home:main")],
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


def lookup_region_keyboard(v):
    rows = []
    current = []
    for code, name in REGIONS[v]:
        current.append(button(name, f"lookup_region:{v}:{code}"))
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append([button("⬅️ Back", f"variant:{v}")])
    return rows


def format_variant(v):
    x = VARIANTS[v]
    return f"<b>{html.escape(x['name'])}</b>\nModel: <code>{x['model']}</code>\nChina model: <code>{x['cn_model']}</code>\nCodename: <code>{x['codename']}</code>"


def format_result(result, v, region):
    x = VARIANTS[v]
    rname = dict(REGIONS[v]).get(region, region.upper())
    lines = [
        f"<b>{html.escape(x['name'])}</b> • {html.escape(rname)}",
        "",
        f"📦 <b>OTA:</b> <code>{html.escape(result['ota_version'])}</code>",
        f"📱 <b>Software:</b> {html.escape(result.get('version','N/A'))}",
        f"🔐 <b>Security patch:</b> {html.escape(result.get('security_patch','N/A'))}",
    ]
    if result.get("published_time"):
        lines.append(f"🗓 <b>Published:</b> {html.escape(result['published_time'])}")
    if result.get("size"):
        lines.append(f"💾 <b>Size:</b> {html.escape(result['size'])}")
    if result.get("md5") and result["md5"] != "N/A":
        lines.append(f"🔑 <b>MD5:</b> <code>{html.escape(result['md5'])}</code>")
    if result.get("expires_time"):
        lines.append(f"⏳ <b>Link expiry:</b> {html.escape(result['expires_time'])}")
    lines += ["", "Official package queried from the OPlus OTA service."]
    return "\n".join(lines)


def result_keyboard(result, v, region):
    rows = []
    if result.get("link", "").startswith("http"):
        rows.append([{"text": "⬇️ Download OTA", "url": result["link"]}])
    if result.get("original_link", "").startswith("http") and result["original_link"] != result.get("link"):
        rows.append([{"text": "🔗 Original OTA Gate", "url": result["original_link"]}])
    rows.append([
        button("🔄 Refresh", f"latest:{v}:{region}"),
        button("🌍 Regions", f"regions:{v}"),
    ])
    rows.append([button("⬅️ Back", f"variant:{v}"), button("🏠 Home", "home:main")])
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

    if text.startswith("/start"):
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

    send(chat_id, "Use <b>/start</b> to open the menu.", [[button("🏠 Open Menu", "home:main")]])


def poll():
    offset = 0
    tg("deleteWebhook", {"drop_pending_updates": True})
    tg("setMyCommands", {"commands": [{"command": "start", "description": "Open the GT Neo 3 OTA menu"}]})

    while True:
        try:
            updates = tg("getUpdates", {"timeout": 25, "offset": offset}, timeout=35)
            for u in updates:
                offset = u["update_id"] + 1
                if "callback_query" in u:
                    handle_callback(u["callback_query"])
                elif "message" in u:
                    handle_message(u["message"])
        except Exception:
            LOG.exception("polling failure")
            time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    start_health()
    poll()
