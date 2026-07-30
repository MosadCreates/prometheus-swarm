from __future__ import annotations

import hashlib
from pathlib import Path

_ADJECTIVES = [
    "swift",
    "quiet",
    "bold",
    "calm",
    "keen",
    "warm",
    "cool",
    "fair",
    "kind",
    "pure",
    "brave",
    "clean",
    "deep",
    "fine",
    "glad",
    "holy",
    "just",
    "live",
    "safe",
    "soft",
    "able",
    "bald",
    "cold",
    "dark",
    "dear",
    "dull",
    "east",
    "fast",
    "flat",
    "free",
    "full",
    "gold",
    "gray",
    "hard",
    "high",
    "huge",
    "keen",
    "kind",
    "late",
    "lean",
    "light",
    "long",
    "loud",
    "low",
    "mild",
    "near",
    "neat",
    "new",
    "nice",
    "noble",
    "odd",
    "old",
    "open",
    "pale",
    "poor",
    "pure",
    "rare",
    "raw",
    "real",
    "rich",
    "ripe",
    "rough",
    "rude",
    "sad",
    "safe",
    "sane",
    "sick",
    "slim",
    "slow",
    "small",
    "smart",
    "soft",
    "sore",
    "sour",
    "spare",
    "steep",
    "still",
    "strange",
    "strict",
    "strong",
    "sudden",
    "sure",
    "sweet",
    "swift",
    "tall",
    "tame",
    "tart",
    "tender",
    "thick",
    "thin",
    "tight",
    "tough",
    "true",
    "vast",
    "vivid",
    "warm",
    "weak",
    "wet",
    "wide",
    "wild",
    "wise",
    "young",
    "eager",
    "fancy",
    "happy",
    "jolly",
    "lucky",
    "merry",
    "sunny",
    "witty",
    "zesty",
]

_NOUNS = [
    "falcon",
    "otter",
    "heron",
    "badger",
    "raven",
    "swan",
    "eagle",
    "fox",
    "wolf",
    "bear",
    "deer",
    "hawk",
    "kiwi",
    "lion",
    "lynx",
    "mole",
    "newt",
    "owl",
    "panda",
    "seal",
    "slug",
    "snake",
    "swan",
    "toad",
    "vole",
    "wren",
    "bison",
    "crane",
    "crocus",
    "dove",
    "finch",
    "gecko",
    "hyena",
    "ibis",
    "jaguar",
    "koala",
    "lemur",
    "moose",
    "newt",
    "ocelot",
    "puma",
    "quail",
    "robin",
    "shrew",
    "tiger",
    "ukari",
    "viper",
    "whale",
    "xerus",
    "yak",
    "zebra",
    "algae",
    "bloom",
    "cedar",
    "dune",
    "elm",
    "fig",
    "grove",
    "heath",
    "iris",
    "jade",
    "kelp",
    "larch",
    "moss",
    "nimbus",
    "oak",
    "pine",
    "quartz",
    "reed",
    "spruce",
    "thyme",
    "umber",
    "vale",
    "wheat",
    "yarrow",
    "zinc",
    "anvil",
    "beacon",
    "cabin",
    "docks",
    "forge",
    "gauge",
    "haven",
    "inlet",
    "jetty",
    "knoll",
    "ledge",
    "moat",
    "nook",
    "pier",
    "quarry",
    "ridge",
    "shelf",
    "tower",
    "vault",
    "wharf",
    "abbey",
    "basin",
    "cove",
    "dell",
    "edge",
    "ford",
    "glen",
    "hill",
    "isle",
    "knoll",
]

_SLUG_REDIS_KEY = "global:slug_index"


import re

_SLUG_PATTERN = re.compile(r"^[a-z]+-[a-z]+-([0-9a-f]{4})$")


def _extract_hex(mission_id: str) -> str:
    """Extract the meaningful hex portion from a mission ID.

    Handles formats:
      job-a1b2c3d4      → a1b2
      a1b2c3d4-...      → a1b2  (full UUID)
      swift-falcon-3a9c → 3a9c  (already a slug)
    """
    if mission_id.startswith("job-"):
        return mission_id[4:8]
    m = _SLUG_PATTERN.match(mission_id)
    if m:
        return m.group(1)
    raw = mission_id.replace("-", "")
    alphanum = "".join(c for c in raw if c.isalnum())
    return alphanum[:4]


def uuid_to_slug(mission_id: str) -> str:
    """Generate a deterministic human-readable slug from a mission ID.

    Format: adjective-noun-4hex  (e.g. swift-falcon-3a9c)
    Deterministic: same input always produces the same slug.
    """
    digest = hashlib.sha256(mission_id.encode()).digest()
    seed = int.from_bytes(digest[:8], "big")
    adj = _ADJECTIVES[seed % len(_ADJECTIVES)]
    noun = _NOUNS[(seed // len(_ADJECTIVES)) % len(_NOUNS)]
    hex_part = _extract_hex(mission_id)
    return f"{adj}-{noun}-{hex_part}"


def _mission_ids_from_outputs() -> list[str]:
    """Scan outputs/ for mission directories."""
    outputs = Path("outputs")
    if not outputs.exists():
        return []
    ids: list[str] = []
    for child in sorted(outputs.iterdir(), reverse=True):
        if child.is_dir() and (child / "trace.jsonl").exists():
            ids.append(child.name)
    return ids


def _mission_ids_from_redis(redis_client) -> list[str]:
    """Scan Redis for job keys."""
    try:
        keys = redis_client.keys("job:*:mission_brief")
        ids: list[str] = []
        for k in keys:
            raw = k.decode() if isinstance(k, bytes) else k
            parts = raw.split(":")
            if len(parts) >= 2:
                ids.append(parts[1])
        return ids
    except Exception:
        return []


def resolve_slug(
    slug_or_prefix: str,
    redis_client=None,
) -> str | None:
    """Resolve a slug or slug prefix to a full mission UUID.

    Accepts: full slug ('swift-falcon-3a9c'), prefix ('swift'), partial slug.
    Returns: the matching mission UUID, or None if no match.
    """
    candidates = _mission_ids_from_outputs()
    if redis_client:
        try:
            candidates = list(set(candidates + _mission_ids_from_redis(redis_client)))
        except Exception:
            pass

    slug_or_prefix = slug_or_prefix.lower()
    matches: list[str] = []
    for mid in candidates:
        slug = uuid_to_slug(mid)
        if (
            slug == slug_or_prefix
            or slug.startswith(slug_or_prefix)
            or mid.startswith(slug_or_prefix)
        ):
            matches.append(mid)

    if len(matches) == 1:
        return matches[0]
    return None


def format_slug(mission_id: str) -> str:
    """Return the slug for a mission ID, or the ID itself if it's a slug."""
    if mission_id == "latest":
        return "latest"
    if mission_id.startswith("job-"):
        return uuid_to_slug(mission_id)  # raw mission ID → convert
    # Already a slug (adjective-noun-hex): return as-is
    return mission_id


MISSIONS_THIS_WEEK_CACHE: dict[str, int] = {}


def count_missions_this_week() -> int:
    """Count missions created in the last 7 days."""
    import datetime

    outputs = Path("outputs")
    if not outputs.exists():
        return 0
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)
    count = 0
    for child in outputs.iterdir():
        if child.is_dir() and (child / "trace.jsonl").exists():
            try:
                mtime = datetime.datetime.fromtimestamp((child / "trace.jsonl").stat().st_mtime)
                if mtime >= week_ago:
                    count += 1
            except (OSError, ValueError):
                pass
    return count


def workspace_name() -> str:
    """Get the workspace display name."""
    from prometheus.services.config_service import ConfigService

    try:
        return ConfigService().get_workspace_name()
    except Exception:
        return "unknown"
