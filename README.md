# Realme GT Neo 3 OTA Community Bot

A focused, button-first Telegram bot for the **realme GT Neo 3 80W / 150W** community.

## What it does

- /start is the only command users need.
- Inline-button UI for 80W and 150W variants.
- Region selector for supported stock-OTA regions.
- Queries official OPlus OTA infrastructure instead of storing expiring CDN URLs.
- Refresh button for fresh download links.
- Exact historical-version lookup.
- OTA metadata: version, software version, security patch, publish time, size and MD5 when supplied.
- Download button for the returned package.
- Downgrade section ready for the community-provided downgrade catalog.
- Health endpoint and polling recovery.
- GitHub Actions validation.
- Deta Space deployment workflow.

## Device mapping

| Variant | Global model | China model | Codename |
| --- | --- | --- | --- |
| GT Neo 3 80W | RMX3561 | RMX3560 | lisa-a |
| GT Neo 3 150W | RMX3563 | RMX3562 | lisa-b |

The model/region catalog is based on OTA Pulse's Realme device catalog. The live query layer is pinned to a known OPlus-Tracker revision and can be updated through OPLUS_TRACKER_COMMIT.

## Configuration

Set the Telegram token in the deployed environment:

TELEGRAM_BOT_TOKEN

Optional environment variables:

BOT_NAME, BOT_VERSION, PORT, HEALTH_PORT, OPLUS_TRACKER_COMMIT.

Do not put the Telegram token in the repository.

## Deployment

The repository contains a Spacefile and .github/workflows/deploy-deta.yml.

GitHub repository secrets required:

- BOT_SPACE_ACCESS_TOKEN
- BOT_SPACE_PROJECT_ID

TELEGRAM_BOT_TOKEN must also be configured in the deployed Space environment.

## Important OTA-link behavior

Official OPlus/Realme download URLs can be short-lived. The bot therefore resolves a link when the user requests it and exposes Refresh instead of pretending a stale hard-coded URL is permanent.

The dynamic query engine is sourced from OPlus-Tracker at a pinned commit. Its upstream documentation notes support for official OTA queries and dynamic-link resolution.

## Downgrades

data/downgrades.json is intentionally empty until the community downgrade links are supplied. Once those links are provided, they can be added by region/build without changing the Telegram UI.

## Credits

- OTA Pulse — Realme device/region catalog and OTA implementation reference.
- OPlus-Tracker — official OPlus OTA query/resolution engine.
