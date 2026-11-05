#!/usr/bin/env python3
"""Realme GT Neo 3 OTA Community Bot."""

import html
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import requests

from ota_engine import (
    REGIONS,
    VARIANTS,
    get_generation,
    get_latest,
    get_version,
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GH_TOKEN = os.getenv("GITHUB_TOKEN", "")
GH_REPO = os.getenv("GITHUB_REPOSITORY", "almightygodthor/community_bot_neo3")
GH_REF = os.getenv("GITHUB_REF_NAME") or os.getenv("GITHUB_REF", "main").removeprefix("refs/heads/")
BOT_WORKFLOW = "telegram-bot.yml"
WORKER_SECONDS = 60 * 60 * 5 + 40 * 60
BOT_NAME = os.getenv("BOT_NAME", "GT Neo 3 OTA")
VERSION = os.getenv("BOT_VERSION", "1.2.0")
PORT = int(os.getenv("PORT", "8080"))
HEALTH_PORT = int(os.getenv("HEALTH_PORT", str(PORT)))

API = f"https://api.telegram.org/bot{TOKEN}"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "GTNeo3-OTA-Community-Bot/1.2"})
CACHE = {}
LOG = logging.getLogger("neo3bot")
EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="neo3_bot")

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
                desc = data.get("description", "Telegram API error")
                if "message is not modified" in desc.lower():
                    raise RuntimeError(desc)
                raise RuntimeError(desc)
            return data["result"]
        except RuntimeError:
            raise
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
    try:
        return tg("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            **({"reply_markup": {"inline_keyboard": keyboard}} if keyboard is not None else {}),
        })
    except RuntimeError as e:
        if "message is not modified" in str(e).lower():
            return None
        raise


def answer_callback(callback_id, text=None, alert=False):
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = alert
    try:
        tg("answerCallbackQuery", payload)
    except Exception:
        pass


def button(text, data):
    return {"text": text, "callback_data": data}


def home_keyboard():
    return [
        [button("⚡ GT Neo 3 • 80W", "variant:80"), button("⚡ GT Neo 3 • 150W", "variant:150")],
        [button("🔄 Refresh", "home:refresh"), button("ℹ️ About", "home:about")],
    ]


def variant_keyboard(v):
    return [
        [button("⚡ Latest OTA", f"latest:{v}"), button("🌍 Select Region", f"regions:{v}")],
        [button("🏷️ RUI 3 • Android 12", f"generation:{v}:3")],
        [button("🏷️ RUI 4 • Android 13", f"generation:{v}:4")],
        [button("🏷️ RUI 5 • Android 14", f"generation:{v}:5")],
        [button("📦 Downgrade Packages", f"down:{v}")],
        [button("🔍 Search Exact Build", f"lookup_prompt:{v}")],
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
    rows.append([button("⬅️ Back", f"variant:{v}")])
    return rows


def format_variant(v):
    x = VARIANTS[v]
    return (
        f"📱 <b><u>{html.escape(x['name'])}</u></b>\n\n"
        f"<blockquote>"
        f"• <b>Global Model:</b> <code>{x['model']}</code>\n"
        f"• <b>China Model:</b> <code>{x['cn_model']}</code>\n"
        f"• <b>Device Codename:</b> <code>{x['codename']}</code>\n"
        f"• <b>Chipset:</b> MediaTek Dimensity 8100 (5nm)"
        f"</blockquote>\n\n"
        f"👇 <i>Select an option below to fetch official stock firmware:</i>"
    )


def format_size(value):
    try:
        size = float(value)
        if size <= 0:
            return "N/A"
        return f"{size / 1_000_000_000:.2f} GB"
    except (TypeError, ValueError):
        return "N/A"


def format_result(result, v, region, generation=None):
    x = VARIANTS[v]
    rname = dict(REGIONS[v]).get(region, region.upper())
    family = None
    if generation:
        family = {
            "3": "Realme UI 3.0 • Android 12",
            "4": "Realme UI 4.0 • Android 13",
            "5": "Realme UI 5.0 • Android 14",
        }.get(str(generation))

    raw_build = str(result.get("ota_version", "N/A"))
    match = re.match(r"^(.*?[._][A-Z][._]\d+)(?:_|$)", raw_build)
    build = html.escape(match.group(1) if match else raw_build)
    software = html.escape(str(result.get("version", "N/A")))
    patch = html.escape(str(result.get("security_patch", "N/A")))
    released = html.escape(str(result.get("published_time", "N/A")).split(" ")[0])
    size = html.escape(format_size(result.get("size")) if result.get("size") else "N/A")
    md5 = html.escape(str(result.get("md5") or ""))

    lines = [
        f"📦 <b><u>{html.escape(x['name'])} — Official Stock OTA</u></b>",
        f"<blockquote>🌍 <b>Region:</b> {html.escape(rname)}",
    ]
    if family:
        lines.append(f"🏷️ <b>Generation:</b> {html.escape(family)}")
    lines.append("</blockquote>")

    lines.extend([
        "",
        "📋 <b><u>FIRMWARE SPECIFICATIONS</u></b>",
        f"<blockquote>"
        f"• <b>Build Tag:</b> <code>{build}</code>\n"
        f"• <b>Full Version:</b> <code>{software}</code>\n"
        f"• <b>Security Patch:</b> <code>{patch}</code>\n"
        f"• <b>Release Date:</b> <code>{released}</code>\n"
        f"• <b>Package Size:</b> <code>{size}</code>"
    ])

    if md5:
        lines.append(f"• <b>MD5 Checksum:</b> <code>{md5}</code>")

    lines.extend([
        "</blockquote>",
        "",
        "<blockquote>⚠️ <b>Preloader Notice:</b> Full packages include <code>preloader_raw.img</code>. Ensure you flash packages strictly intended for your hardware variant.</blockquote>"
    ])

    return "\n".join(lines)


def result_keyboard(result, v, region, generation=None):
    rows = []
    link = result.get("link", "")
    orig_link = result.get("original_link", "")

    if link.startswith("http"):
        rows.append([{"text": "⬇️ Download Full OTA", "url": link}])
    if orig_link.startswith("http") and orig_link != link:
        rows.append([{"text": "🔗 Alternate CDN Link", "url": orig_link}])

    refresh_data = f"refresh_gen:{v}:{generation}:{region}" if generation else f"refresh_latest:{v}:{region}"
    rows.append([
        button("🔄 Refresh Link", refresh_data),
        button("🌍 Change Region", f"regions:{v}"),
    ])
    rows.append([
        button("⬅️ Back", f"variant:{v}"),
        button("🏠 Home", "home:main"),
    ])
    return rows


def run_generation(chat_id, message_id, v, region, generation, force=False):
    key = f"{v}:{region}:rui{generation}"
    now = time.time()
    if not force and key in CACHE and (now - CACHE[key][0] < 300):
        result = CACHE[key][1]
    else:
        result = get_generation(v, region, generation)
        if result and isinstance(result, dict) and not result.get("error"):
            CACHE[key] = (now, result)
        elif force and key in CACHE:
            CACHE.pop(key, None)

    if not result:
        edit(
            chat_id,
            message_id,
            "⚠️ <b><u>No Stock OTA Found</u></b>\n\n"
            "<blockquote>The official server did not return a package for this generation and region combination.</blockquote>",
            [
                [button("🔄 Try Again", f"refresh_gen:{v}:{generation}:{region}")],
                [button("⬅️ Back", f"variant:{v}")],
            ]
        )
        return

    if isinstance(result, dict) and result.get("error"):
        edit(
            chat_id,
            message_id,
            f"⚠️ <b><u>OTA Query Failed</u></b>\n\n"
            f"<blockquote><code>{html.escape(result['error'])}</code></blockquote>",
            [
                [button("🔄 Try Again", f"refresh_gen:{v}:{generation}:{region}")],
                [button("⬅️ Back", f"variant:{v}")],
            ]
        )
        return

    edit(
        chat_id,
        message_id,
        format_result(result, v, region, generation),
        result_keyboard(result, v, region, generation),
    )


def run_latest(chat_id, message_id, v, region, force=False):
    key = f"{v}:{region}"
    now = time.time()
    if not force and key in CACHE and (now - CACHE[key][0] < 300):
        result = CACHE[key][1]
    else:
        result = get_latest(v, region)
        if result and isinstance(result, dict) and not result.get("error"):
            CACHE[key] = (now, result)
        elif force and key in CACHE:
            CACHE.pop(key, None)

    if not result:
        text = (
            "⚠️ <b><u>No Stock OTA Returned</u></b>\n\n"
            "<blockquote>The official server may be rate-limiting queries or that region has no currently active package.</blockquote>"
        )
        edit(chat_id, message_id, text, [
            [button("🔄 Try Again", f"refresh_latest:{v}:{region}")],
            [button("⬅️ Back", f"variant:{v}")],
        ])
        return

    if isinstance(result, dict) and result.get("error"):
        edit(
            chat_id,
            message_id,
            f"⚠️ <b><u>OTA Query Failed</u></b>\n\n"
            f"<blockquote><code>{html.escape(result['error'])}</code></blockquote>",
            [
                [button("🔄 Try Again", f"refresh_latest:{v}:{region}")],
                [button("⬅️ Back", f"variant:{v}")],
            ]
        )
        return

    edit(
        chat_id,
        message_id,
        format_result(result, v, region),
        result_keyboard(result, v, region)
    )


def run_lookup(chat_id, message_id, v, region, query_str):
    result = get_version(v, region, query_str)
    if not result or (isinstance(result, dict) and result.get("error")):
        err_msg = result.get("error", "No package found.") if isinstance(result, dict) else "No package found."
        edit(
            chat_id,
            message_id,
            f"⚠️ <b><u>Lookup Notice</u></b>\n\n"
            f"<blockquote>{html.escape(err_msg)}</blockquote>\n\n"
            "💡 <i>Tip: Query builds like <code>RMX3561_11.C.15</code> or <code>11.C.15</code>.</i>",
            [
                [button("🔍 Try Another Build", f"lookup_prompt:{v}")],
                [button("⬅️ Back", f"variant:{v}")],
            ]
        )
        return

    edit(
        chat_id,
        message_id,
        format_result(result, v, region),
        result_keyboard(result, v, region)
    )


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
        if data in ("home:main", "home:refresh"):
            edit(
                chat_id,
                message_id,
                f"⚡ <b><u>{html.escape(BOT_NAME)}</u></b>\n"
                "<blockquote>Official Stock OTA & Rollback Hub for realme GT Neo 3</blockquote>\n\n"
                "Welcome! This bot resolves <b>direct, unexpired stock OTA packages</b> directly from official OPlus update infrastructure.\n\n"
                "<b><u>Key Highlights:</u></b>\n"
                "• Official OPlus live query engine (no broken/expired URLs)\n"
                "• RUI 3, 4 & 5 generational search\n"
                "• Exact build lookup with verified <b>MD5 checksums</b>\n"
                "• Verified community rollback & downgrade packages\n\n"
                "🔘 <b>Select your charging variant to begin:</b>",
                home_keyboard()
            )
            return

        if data == "home:about":
            edit(
                chat_id,
                message_id,
                f"ℹ️ <b><u>About {html.escape(BOT_NAME)}</u></b> <i>v{html.escape(VERSION)}</i>\n\n"
                f"<blockquote>Dedicated community utility for the realme GT Neo 3 80W / 150W (MediaTek Dimensity 8100).</blockquote>\n\n"
                f"<b><u>Core Capabilities:</u></b>\n"
                f"• <b>Official Live Queries:</b> Direct resolution via official OPlus update infrastructure.\n"
                f"• <b>Realme UI Generations:</b> Instant lookups for RUI 3 (A12), RUI 4 (A13), & RUI 5 (A14).\n"
                f"• <b>Exact Build Search:</b> Query any historical build tag.\n"
                f"• <b>Integrity Checksums:</b> Official MD5 hashes for verified, brick-free downloads.\n"
                f"• <b>Community Rollbacks:</b> Direct downgrade packages with step-by-step local install manual.\n\n"
                f"<blockquote>💡 <i>Official download links are dynamically signed and expire after several hours. Tap <b>Refresh Link</b> anytime to generate an active URL.</i></blockquote>",
                [[button("⬅️ Back to Menu", "home:main")]]
            )
            return

        if data.startswith("variant:"):
            v = data.split(":", 1)[1]
            edit(chat_id, message_id, format_variant(v), variant_keyboard(v))
            return

        if data.startswith("regions:"):
            v = data.split(":", 1)[1]
            edit(
                chat_id,
                message_id,
                f"🌍 <b><u>Region Selector — {html.escape(VARIANTS[v]['name'])}</u></b>\n\n"
                f"<blockquote>Official Realme OTA servers deliver different regional builds depending on region code.</blockquote>\n\n"
                f"Select your target region to view the latest firmware:",
                region_keyboard(v)
            )
            return

        if data.startswith("latest:"):
            parts = data.split(":")
            v = parts[1]
            region = parts[2].lower() if len(parts) > 2 else None
            if not region:
                edit(
                    chat_id,
                    message_id,
                    f"🌍 <b><u>Region Selector — {html.escape(VARIANTS[v]['name'])}</u></b>\n\n"
                    f"<blockquote>Select the region to query the latest available stock OTA:</blockquote>",
                    region_keyboard(v)
                )
                return
            edit(
                chat_id,
                message_id,
                "⏳ <b><u>Querying Official OTA Infrastructure…</u></b>\n\n"
                "<blockquote>Connecting to official OPlus update endpoints. This takes 2–4 seconds…</blockquote>",
                [[button("⬅️ Cancel", f"variant:{v}")]]
            )
            EXECUTOR.submit(run_latest, chat_id, message_id, v, region, False)
            return

        if data.startswith("refresh_latest:"):
            _, v, region = data.split(":")
            edit(
                chat_id,
                message_id,
                "🔄 <b><u>Refreshing Download URL…</u></b>\n\n"
                "<blockquote>Generating an active, unexpired CDN token from the server…</blockquote>",
                [[button("⬅️ Cancel", f"variant:{v}")]]
            )
            EXECUTOR.submit(run_latest, chat_id, message_id, v, region, True)
            return

        if data.startswith("generation:"):
            _, v, generation = data.split(":")
            labels = {"3": "Realme UI 3.0 • Android 12", "4": "Realme UI 4.0 • Android 13", "5": "Realme UI 5.0 • Android 14"}
            edit(
                chat_id,
                message_id,
                f"🏷️ <b><u>{html.escape(labels[generation])}</u></b>\n\n"
                f"<blockquote>Device: <b>{html.escape(VARIANTS[v]['name'])}</b></blockquote>\n\n"
                f"Select your region below. The bot will automatically locate the latest matching official build:",
                generation_region_keyboard(v, generation),
            )
            return

        if data.startswith("generation_run:"):
            _, v, generation, region = data.split(":")
            labels = {"3": "Realme UI 3.0 • Android 12", "4": "Realme UI 4.0 • Android 13", "5": "Realme UI 5.0 • Android 14"}
            edit(
                chat_id,
                message_id,
                f"🏷️ <b><u>{html.escape(labels[generation])}</u></b>\n\n"
                f"<blockquote>🌍 Region: <b>{html.escape(dict(REGIONS[v]).get(region, region.upper()))}</b></blockquote>\n\n"
                f"⏳ <i>Fetching the latest matching stock OTA from server…</i>",
                [[button("⬅️ Cancel", f"variant:{v}")]],
            )
            EXECUTOR.submit(run_generation, chat_id, message_id, v, region, generation, False)
            return

        if data.startswith("refresh_gen:"):
            _, v, generation, region = data.split(":")
            edit(
                chat_id,
                message_id,
                "🔄 <b><u>Refreshing Download URL…</u></b>\n\n"
                "<blockquote>Generating an active, unexpired CDN token from the server…</blockquote>",
                [[button("⬅️ Cancel", f"variant:{v}")]]
            )
            EXECUTOR.submit(run_generation, chat_id, message_id, v, region, generation, True)
            return

        if data.startswith("lookup_prompt:"):
            v = data.split(":", 1)[1]
            edit(
                chat_id,
                message_id,
                f"🔍 <b><u>Exact Build Search — {html.escape(VARIANTS[v]['name'])}</u></b>\n\n"
                f"<blockquote>Send any OTA build number directly in this chat.</blockquote>\n\n"
                f"<b><u>Accepted Formats:</u></b>\n"
                f"• Full build tag: <code>{VARIANTS[v]['model']}_11.C.15</code>\n"
                f"• Short version: <code>11.C.15</code> or <code>C.15</code>\n"
                f"• China model tag: <code>{VARIANTS[v]['cn_model']}_11.C.15</code>\n\n"
                f"<b><u>Command Syntax:</u></b>\n"
                f"<code>/lookup {VARIANTS[v]['model']}_11.C.15 [region]</code>\n\n"
                f"<i>👉 Or simply type the version code into this chat!</i>",
                [[button("⬅️ Back", f"variant:{v}")]]
            )
            return

        if data.startswith("guide:rollback:"):
            v = data.split(":", 2)[2]
            edit(
                chat_id,
                message_id,
                "📖 <b><u>Realme UI Rollback & Downgrade Manual</u></b>\n\n"
                "<blockquote>⚠️ <b>CRITICAL SAFETY RULES:</b>\n"
                "• Downgrading <u>ERASES ALL USER DATA</u>. Perform a complete local or cloud backup before starting.\n"
                "• Device battery must be at least <b>60%</b>.\n"
                "• <b>Do NOT rename or unpack</b> the downloaded <code>.zip</code> package.</blockquote>\n\n"
                "🛠️ <b><u>Installation Steps:</u></b>\n\n"
                "1️⃣ <b>Download Package:</b> Download the exact rollback package for your region using the buttons below.\n"
                "2️⃣ <b>Move to Root:</b> Copy the <code>.zip</code> to the root directory of your device's <b>Internal Storage</b> (not inside Download).\n"
                "3️⃣ <b>Unlock Developer Mode:</b> Go to <i>Settings > About device > Version > Tap 'Build number' 7 times</i>.\n"
                "4️⃣ <b>Access Local Update:</b> Open <i>Settings > About device > Up to date (realme UI) > Tap 3 dots (top right) > Local install</i>.\n"
                "5️⃣ <b>Confirm & Install:</b> Choose the <code>.zip</code> package, tap <i>Verify</i>, and let the system complete installation and reboot.\n\n"
                "<blockquote>💡 <i>Note: If the 3 dots menu lacks 'Local install', ensure Developer Options are enabled, or install the official Realme Local Update APK.</i></blockquote>",
                [
                    [button("📦 Back to Downgrades", f"down:{v}")],
                    [button("⬅️ Variant Menu", f"variant:{v}")]
                ]
            )
            return

        if data.startswith("down:"):
            v = data.split(":", 1)[1]
            packages = DOWNGRADES.get(v, {}).get("packages", [])
            rows = []
            lines = [
                f"📦 <b><u>Official Rollback Packages</u></b>",
                f"<blockquote>Device: <b>{html.escape(VARIANTS[v]['name'])}</b></blockquote>\n",
                "Verified rollback packages from Realme to revert to an earlier Android / RUI version.\n",
                "<blockquote>⚠️ <b>Crucial Warning:</b> Downgrading <u>wipes all internal user data</u>. Back up all personal files before proceeding!</blockquote>\n",
                "<b><u>Available Packages:</u></b>"
            ]
            for package in packages:
                title = html.escape(package.get("title", "Downgrade package"))
                region = html.escape(package.get("region", ""))
                version = html.escape(package.get("version", ""))
                lines.append(f"• <b>{title}</b> ({region}): <code>{version}</code>")
                url = package.get("url", "")
                if url.startswith("http"):
                    button_text = f"⬇️ {package.get('title', 'Download')} • {package.get('region', '')}"
                    rows.append([{"text": button_text, "url": url}])

            if not packages:
                lines.append("<i>No downgrade packages configured yet.</i>")

            rows.append([button("📖 Rollback Guide", f"guide:rollback:{v}")])
            rows.append([button("⬅️ Back", f"variant:{v}"), button("🏠 Home", "home:main")])
            edit(chat_id, message_id, "\n".join(lines), rows)
            return

    except Exception:
        LOG.exception("callback failed")
        try:
            edit(chat_id, message_id, "⚠️ <b><u>Error Notice</u></b>\n\n<blockquote>Something went wrong. Please return to Home or try again.</blockquote>", [[button("🏠 Home", "home:main")]])
        except Exception:
            pass


def handle_message(message):
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()
    if not text:
        return

    tokens = text.split()
    cmd = tokens[0].split("@")[0].lower()

    if cmd in ("/start", "/stockota", "/menu"):
        send(
            chat_id,
            f"⚡ <b><u>{html.escape(BOT_NAME)}</u></b>\n"
            "<blockquote>Official Stock OTA & Rollback Hub for realme GT Neo 3</blockquote>\n\n"
            "Welcome! This bot resolves <b>direct, unexpired stock OTA packages</b> directly from official OPlus update infrastructure.\n\n"
            "<b><u>Key Highlights:</u></b>\n"
            "• Official OPlus live query engine (no broken/expired URLs)\n"
            "• RUI 3, 4 & 5 generational search\n"
            "• Exact build lookup with verified <b>MD5 checksums</b>\n"
            "• Verified community rollback & downgrade packages\n\n"
            "🔘 <b>Select your charging variant to begin:</b>",
            home_keyboard()
        )
        return

    if cmd in ("/help", "/commands"):
        send(
            chat_id,
            f"ℹ️ <b><u>{html.escape(BOT_NAME)} — Command & Usage Guide</u></b>\n\n"
            f"<blockquote>Realme GT Neo 3 80W / 150W (MediaTek Dimensity 8100)</blockquote>\n\n"
            f"<b><u>Available Commands:</u></b>\n"
            f"• <code>/start</code> — Open the interactive main menu\n"
            f"• <code>/stockota</code> — Quick menu shortcut\n"
            f"• <code>/lookup &lt;build&gt; [region]</code> — Look up an exact build\n"
            f"• <code>/help</code> — Open this usage guide\n"
            f"• <code>/about</code> — Bot specs, codenames & credits\n\n"
            f"<b><u>Quick Lookup Examples:</u></b>\n"
            f"• <code>/lookup RMX3561_11.C.15 in</code>\n"
            f"• <code>/lookup 11.C.15</code>\n"
            f"• Or send <code>11.F.07</code> directly as a chat message!",
            home_keyboard()
        )
        return

    if cmd == "/about":
        send(
            chat_id,
            f"ℹ️ <b><u>About {html.escape(BOT_NAME)}</u></b> <i>v{html.escape(VERSION)}</i>\n\n"
            f"<blockquote>Dedicated community utility for the realme GT Neo 3 80W / 150W (MediaTek Dimensity 8100).</blockquote>\n\n"
            f"<b><u>Core Capabilities:</u></b>\n"
            f"• <b>Official Live Queries:</b> Direct resolution via official OPlus update infrastructure.\n"
            f"• <b>Realme UI Generations:</b> Instant lookups for RUI 3 (A12), RUI 4 (A13), & RUI 5 (A14).\n"
            f"• <b>Exact Build Search:</b> Query any historical build tag.\n"
            f"• <b>Integrity Checksums:</b> Official MD5 hashes for verified, brick-free downloads.\n"
            f"• <b>Community Rollbacks:</b> Direct downgrade packages with step-by-step local install manual.\n\n"
            f"<blockquote>💡 <i>Official download links are dynamically signed and expire after several hours. Tap <b>Refresh Link</b> anytime to generate an active URL.</i></blockquote>",
            home_keyboard()
        )
        return

    # Handle /lookup command or direct build string input (e.g. RMX3561_11.C.15 or 11.C.15)
    query_build = None
    target_region = "in"

    if cmd in ("/lookup", "/find") and len(tokens) > 1:
        query_build = tokens[1].strip()
        if len(tokens) > 2:
            target_region = tokens[2].strip().lower()
    elif text.upper().startswith(("RMX3561", "RMX3563", "RMX3560", "RMX3562", "11.C", "11.A", "11.F", "C.", "A.", "F.")):
        query_build = text.strip()

    if query_build:
        v = "150" if any(m in query_build.upper() for m in ("3563", "3562")) else "80"
        m = send(
            chat_id,
            f"⏳ <b><u>Querying Build</u></b> <code>{html.escape(query_build)}</code>\n\n"
            f"<blockquote>Device: <b>{VARIANTS[v]['name']}</b>\nConnecting to official OPlus servers…</blockquote>"
        )
        if m and "message_id" in m:
            EXECUTOR.submit(run_lookup, chat_id, m["message_id"], v, target_region, query_build)
        return


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
    tg("setMyCommands", {
        "commands": [
            {"command": "start", "description": "Open GT Neo 3 Stock OTA menu"},
            {"command": "stockota", "description": "Interactive Stock OTA & Rollback menu"},
            {"command": "lookup", "description": "Look up an exact build version"},
            {"command": "help", "description": "Usage guide & rollback instructions"},
            {"command": "about", "description": "Device specs, codenames & credits"},
        ]
    })

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
