# Realme GT Neo 3 OTA Community Bot

A focused, button-first Telegram bot for the **realme GT Neo 3 80W / 150W** community.

Designed with modern Telegram HTML styling (bold, underline, monospace, and native blockquotes `<blockquote>`) for a clean, formal, and organized community experience.

---

## What It Does

- **Interactive Menu**: `/start` or `/stockota` launches the button UI.
- **80W & 150W Variants**: Full hardware support for Global and China models.
- **Regional OTA Lookups**: Query official stock ROMs across India, Europe, Russia, Indonesia, Taiwan, Malaysia, Thailand, MEA, and China.
- **Realme UI Generational Lookups**: Instant lookup for RUI 3.0 (Android 12), RUI 4.0 (Android 13), and RUI 5.0 (Android 14).
- **Exact Historical Build Search**: Use `/lookup <build> [region]` or paste a version tag (e.g. `RMX3561_11.C.15` or `11.C.15`) directly into chat.
- **Live Dynamic Queries**: Queries official OPlus OTA infrastructure in real-time.
- **Refreshable Download Links**: Bypass cache anytime to fetch a freshly signed, unexpired CDN URL.
- **Complete Firmware Cards**: Displays shortened build tag, full software version, Android security patch date, release date, package size, and tap-to-copy **MD5 checksum**.
- **Community Rollback Hub**: Verified downgrade packages with an integrated step-by-step flashing guide.
- **Flashing Safety Warning**: Warns users about packages containing `preloader_raw.img`.

---

## Device Specifications & Mapping

| Variant | Global Model | China Model | Codename | SoC |
| :--- | :--- | :--- | :--- | :--- |
| **GT Neo 3 80W** | `RMX3561` | `RMX3560` | `lisa-a` | MediaTek Dimensity 8100 (5nm) |
| **GT Neo 3 150W** | `RMX3563` | `RMX3562` | `lisa-b` | MediaTek Dimensity 8100 (5nm) |

---

## Telegram BotFather Configuration Guide

To ensure your bot looks professional and displays the command menu in Telegram, configure it in [@BotFather](https://t.me/BotFather):

### 1. Set Bot Commands (`/setcommands`)
1. Open [@BotFather](https://t.me/BotFather) and send `/setcommands`.
2. Select your bot.
3. Paste the following exact block:

```text
start - Open the GT Neo 3 Stock OTA menu
stockota - Interactive Stock OTA & Rollback menu
lookup - Look up an exact build (e.g. /lookup 11.C.15)
help - Usage guide & rollback instructions
about - Device specs, codenames & credits
```

### 2. Set Bot Description (`/setdescription`)
What users see on the intro screen before pressing "Start":
1. In [@BotFather](https://t.me/BotFather), send `/setdescription` and select your bot.
2. Send:
```text
Official Stock OTA and Downgrade package finder for the realme GT Neo 3 80W / 150W community (lisa-a / lisa-b). Powered by official live OPlus query engine.
```

### 3. Set Bot About Text (`/setabouttext`)
What appears in the bot's profile card:
1. In [@BotFather](https://t.me/BotFather), send `/setabouttext` and select your bot.
2. Send:
```text
Realme GT Neo 3 (80W / 150W) community bot for official stock OTAs, MD5 verification, and downgrade packages.
```

---

## Bot Commands Reference

| Command | Usage | Description |
| :--- | :--- | :--- |
| `/start` | `/start` | Opens the main device selection menu |
| `/stockota` | `/stockota` | Quick menu shortcut for group chats |
| `/lookup` | `/lookup <build> [region]` | Looks up an exact build (e.g., `/lookup RMX3561_11.C.15 in` or `/lookup 11.C.15`) |
| `/help` | `/help` | Displays command list, usage tips, and format guide |
| `/about` | `/about` | Shows bot version, device codenames, and engine details |

> [!TIP]
> **Direct Chat Queries**: You don't even need to use `/lookup`. Simply paste any build string like `RMX3561_11.C.15` or `11.F.07` into the chat, and the bot will immediately resolve it!

---

## Environment Variables

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | **Yes** | — | Telegram Bot API token from [@BotFather](https://t.me/BotFather) |
| `BOT_NAME` | No | `GT Neo 3 OTA` | Display name of the bot |
| `BOT_VERSION` | No | `1.2.0` | Displayed bot version |
| `PORT` / `HEALTH_PORT` | No | `8080` | Port for the HTTP health check service |
| `OPLUS_TRACKER_COMMIT`| No | `bfc1e978...` | Pinned commit for fallback engine |

> [!WARNING]
> Never commit your `TELEGRAM_BOT_TOKEN` or GitHub access tokens into repository files.

---

## Important OTA-Link Behavior

Official OPlus/Realme download URLs are dynamically signed and expire after several hours. The bot resolves the download link upon request, displays the MD5 checksum so you can verify download integrity, and exposes a **🔄 Refresh Link** button that bypasses the cache to fetch a fresh download URL directly from the official server.

---

## Credits

- **OTA Pulse** — Realme device & region catalog and OTA reference.
- **OPlus-Tracker** — Official OPlus OTA query engine by Jerry Tse.
