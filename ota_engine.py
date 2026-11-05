"""GT Neo 3 OTA query adapter.

The query engine uses OPlus-Tracker (JerryTse-OSS) vendored locally with dynamic
fallback to official OPlus OTA endpoints.
No OTA download URLs are hard-coded because official package links can expire.
"""

import importlib.util
import os
import re
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

PIN = os.getenv("OPLUS_TRACKER_COMMIT", "bfc1e9780ece1bd17d8c43d592f5c32707b4c179")
BASE = f"https://raw.githubusercontent.com/JerryTse-OSS/OPlus-Tracker/{PIN}"
TRACKER_DIR = os.path.join(os.path.dirname(__file__), "tracker")
ROOT = os.path.join(os.path.dirname(__file__), ".runtime_oplus")
_LOCK = threading.Lock()
_ENGINE = None

VARIANTS = {
    "80": {"name": "realme GT Neo 3 80W", "model": "RMX3561", "cn_model": "RMX3560", "codename": "lisa-a"},
    "150": {"name": "realme GT Neo 3 150W", "model": "RMX3563", "cn_model": "RMX3562", "codename": "lisa-b"},
}

REGIONS = {
    "80": [
        ("in", "🇮🇳 India"),
        ("ru", "🇷🇺 Russia"),
        ("eu", "🇪🇺 Europe"),
        ("id", "🇮🇩 Indonesia"),
        ("tw", "🇹🇼 Taiwan"),
        ("my", "🇲🇾 Malaysia"),
        ("th", "🇹🇭 Thailand"),
        ("mea", "🌍 MEA"),
        ("cn", "🇨🇳 China"),
    ],
    "150": [
        ("in", "🇮🇳 India"),
        ("eu", "🇪🇺 Europe"),
        ("id", "🇮🇩 Indonesia"),
        ("cn", "🇨🇳 China"),
    ],
}

RUI_FAMILIES = {
    "3": {"name": "RUI 3", "android": "Android 12", "suffix": "A"},
    "4": {"name": "RUI 4", "android": "Android 13", "suffix": "C"},
    "5": {"name": "RUI 5", "android": "Android 14", "suffix": "F"},
}


def _load():
    """Load the tracker engine, prioritizing local tracker files over remote fetch."""
    global _ENGINE
    with _LOCK:
        if _ENGINE:
            return _ENGINE

        # 1. Try local vendored tracker module first
        if os.path.isdir(TRACKER_DIR) and os.path.exists(os.path.join(TRACKER_DIR, "tomboy_pro.py")):
            if TRACKER_DIR not in sys.path:
                sys.path.insert(0, TRACKER_DIR)
            try:
                spec = importlib.util.spec_from_file_location("neo3_tomboy", os.path.join(TRACKER_DIR, "tomboy_pro.py"))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _ENGINE = mod
                return mod
            except Exception:
                pass

        # 2. Fallback to cached / dynamically fetched runtime files
        os.makedirs(ROOT, exist_ok=True)
        for name in ("tomboy_pro.py", "config.py"):
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                req = urllib.request.Request(
                    f"{BASE}/{name}",
                    headers={"User-Agent": "GTNeo3-OTA-Community-Bot/1.0"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp, open(path, "wb") as out:
                    out.write(resp.read())

        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        spec = importlib.util.spec_from_file_location("neo3_tomboy", os.path.join(ROOT, "tomboy_pro.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ENGINE = mod
        return mod


def _query(mod, v, region, ota_prefix):
    base_model = VARIANTS[v]["cn_model"] if region == "cn" else VARIANTS[v]["model"]
    custom = base_model if region == "cn" else None
    cfg = mod.QueryConfig(
        ota_version=ota_prefix,
        model=base_model,
        region=region,
        mode="manual",
        guid="0" * 64,
        has_custom_model=bool(custom),
        original_link=1,
    )
    query_prefix = ota_prefix.replace(VARIANTS[v]["model"], base_model, 1) if region == "cn" else ota_prefix
    processed, model = mod.process_ota_version(query_prefix, region, "0", "0", custom)
    cfg.ota_version = processed
    cfg.model = model
    return mod.query_update(cfg)


def _component(result):
    if not result or not result.success:
        return None
    comps = result.components or []
    preferred = [c for c in comps if c.name.lower() in {"my_manifest", "full_ota", "ota"}]
    candidates = preferred or comps
    candidates = [c for c in candidates if c.link and c.link.startswith("http")]
    if not candidates:
        return None
    return max(candidates, key=lambda c: int(c.size) if str(c.size).isdigit() else 0)


def _convert(result, v, region):
    c = _component(result)
    if not c:
        return None
    return {
        "region": region,
        "ota_version": (result.data or {}).get("ota_version", "N/A"),
        "version": (result.data or {}).get("version", "N/A"),
        "security_patch": (result.data or {}).get("security_patch", "N/A"),
        "published_time": result.published_time,
        "link": c.link,
        "original_link": c.original_link,
        "size": c.size,
        "md5": c.md5,
        "expires_time": c.expires_time.strftime("%Y-%m-%d %H:%M:%S") if c.expires_time else None,
        "error": None,
    }


def _version_key(value):
    s = str(value).upper()
    nums = [int(x) for x in re.findall(r"\d+", s)]
    rank = {"A": 1, "C": 2, "F": 3, "H": 4, "J": 5}
    letter = 0
    m = re.search(r"_11[._]([A-Z])", s)
    if m:
        letter = rank.get(m.group(1), 0)
    return (letter, nums[2] if len(nums) > 2 else 0, nums[-1] if nums else 0)


def get_generation(v, region, generation):
    mod = _load()
    family = RUI_FAMILIES.get(str(generation))
    if not family:
        return {"error": f"Unknown generation {generation}"}
    try:
        result = _query(mod, v, region, f"{VARIANTS[v]['model']}_11.{family['suffix']}")
        item = _convert(result, v, region)
        return item or {"error": f"No {family['name']} package was returned for this region."}
    except Exception as e:
        return {"error": str(e)}


def get_latest(v, region=None):
    mod = _load()
    regions = [region] if region else [r for r, _ in REGIONS[v]]
    best = None
    errors = []
    # Search descending (newest major generation first)
    suffixes = ("F", "C", "A")

    def one(r):
        found = []
        for suffix in suffixes:
            try:
                result = _query(mod, v, r, f"{VARIANTS[v]['model']}_11.{suffix}")
                item = _convert(result, v, r)
                if item:
                    found.append(item)
                    # If latest RUI 5 (F) is found for this region, we already have the latest build
                    if suffix == "F":
                        break
            except Exception as e:
                errors.append(f"{r}: {e}")
        return found

    with ThreadPoolExecutor(max_workers=min(5, len(regions))) as pool:
        futures = {pool.submit(one, r): r for r in regions}
        for future in as_completed(futures):
            for item in future.result():
                if best is None or _version_key(item["ota_version"]) > _version_key(best["ota_version"]):
                    best = item

    if region:
        return best or {"error": "; ".join(errors[-3:]) or "No stock OTA package was returned for this region."}
    return best


def get_version(v, region, ota_version):
    """Query an exact historical build for GT Neo 3."""
    mod = _load()
    ota_version = ota_version.strip().upper().replace(" ", "")
    
    # Auto-complete partial version string if needed
    model = VARIANTS[v]["cn_model"] if region == "cn" else VARIANTS[v]["model"]
    if not ota_version.startswith(("RMX3561", "RMX3563", "RMX3560", "RMX3562")):
        if ota_version.startswith(("11.", "_11.")):
            ota_version = f"{model}_{ota_version.lstrip('_')}"
        elif ota_version.startswith(("A.", "C.", "F.", "A_", "C_", "F_")):
            ota_version = f"{model}_11.{ota_version}"
        else:
            return {"error": "Invalid format. Expected: RMX3561_11.C.15, 11.C.15, or C.15"}

    try:
        result = _query(mod, v, region, ota_version)
        item = _convert(result, v, region)
        return item or {"error": f"The official OTA service did not return build '{ota_version}' for region '{region}'."}
    except Exception as e:
        return {"error": str(e)}
