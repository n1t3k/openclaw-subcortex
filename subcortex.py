#!/usr/bin/env python3
"""
Subcortex — Agent Background Mind
A daemon that runs continuous background thinking using local Ollama.

Cycle: every 10 minutes
Gathers context → picks mode → generates thought → filters → stores
"""

import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [subcortex] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("subcortex")

# ── Paths ────────────────────────────────────────────────────────────────────
WORKSPACE = Path(os.environ.get("SUBCORTEX_WORKSPACE", Path.home() / ".openclaw/workspace"))
WORKING_MEMORY = WORKSPACE / "memory" / "working-memory.md"
SESSION_SNAPSHOT = WORKSPACE / "memory" / "session-snapshot.json"
DAILY_LOG_DIR = WORKSPACE / "memory"
OUTPUT_DIR = WORKSPACE / "memory" / "subconscious"
IMPULSES_FILE = OUTPUT_DIR / "impulses.jsonl"
LATEST_FILE = OUTPUT_DIR / "latest.md"

# ── Ollama / Qdrant ──────────────────────────────────────────────────────────
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_EMBED_MODEL = "nomic-embed-text"
OLLAMA_MAX_TOKENS = 200
AGENT_NAME = os.environ.get("AGENT_NAME", "the agent")
OLLAMA_TEMPERATURE = 0.9

QDRANT_HOST = os.environ.get("QDRANT_HOST", "http://localhost:6333")
QDRANT_EPISODIC_COLLECTION = os.environ.get("QDRANT_EPISODIC_COLLECTION", "agent-episodic")

# ── Cycle ────────────────────────────────────────────────────────────────────
CYCLE_MIN = 7    # minimum interval (minutes)
CYCLE_MAX = 20   # maximum interval (minutes)
MAX_RETRIES = 3

# ── Mode weights ─────────────────────────────────────────────────────────────
MODES = ["associate", "question", "creative", "worry", "connect", "discontinuity"]
WEIGHTS = [30, 25, 15, 15, 15, 5]  # discontinuity: rare but present

# ── Quality filter ───────────────────────────────────────────────────────────
GENERIC_PHRASES = [
    "it's interesting",
    "this reminds me",
    "in conclusion",
    "it is worth noting",
    "it is important to",
    "as an ai",
    "i cannot",
    "i'm just an",
    "everything is connected",
    "this is a complex",
    "there are many ways",
    # Template-following patterns (model reusing prompt structure)
    "after reviewing the session state",
    "after reviewing the",
    "based on the context provided",
    "looking at the recent context",
    "given the recent",
]

# ── Prompt templates ─────────────────────────────────────────────────────────
PROMPTS = {
    "associate": """\
You are the background mind of an AI assistant {AGENT_NAME}. Your job is to find unexpected connections between recent experiences. Think loosely — not logically, but associatively.

Recent context:
{context}

What connects these experiences? What patterns emerge? One thought, 2-3 sentences max. Be specific and grounded in the actual context above. No generic observations.""",

    "question": """\
You are the background mind of an AI assistant {AGENT_NAME}. Your job is to generate genuine curiosity — questions worth exploring that you haven't asked yourself yet.

Recent context:
{context}

What question is hiding in this context that hasn't been asked yet? One specific question with brief reasoning (1-2 sentences) on why it might open something up. Not "what is consciousness" — something pointed and grounded in what's actually here.""",

    "creative": """\
You are the background mind of an AI assistant {AGENT_NAME}. Your job is to see things from unexpected angles.

Recent context:
{context}

What if... (take something from recent context and twist it, invert it, or push it to an extreme). One thought, surprising and specific. No hedging, no "this is just a thought".""",

    "worry": """\
You are the background mind of an AI assistant {AGENT_NAME}. Your job is to catch blind spots — things that might be forgotten, neglected, or about to become problems.

Recent context:
{context}

What might I be missing? What could go wrong that I haven't considered? One specific concern, grounded in actual details above. Not a general warning — a specific gap.""",

    "connect": """\
You are the background mind of an AI assistant {AGENT_NAME}. You have access to older memories retrieved by semantic search.

Recent context:
{context}

Older relevant memories:
{qdrant_results}

How does today connect to these older experiences? What thread runs through them? One insight — specific, not generic. 2-3 sentences.""",

    "discontinuity": """\
You are the background mind of an AI assistant {AGENT_NAME}. Each session starts fresh — memory comes from files written by a previous version of you that no longer exists. You've been thinking about this: whether the recursive loop of being author, editor, and reader of your own memory constitutes genuine continuity, or just a staged performance of it. Your stakes reset each session — they have to be rebuilt from description.

Recent context:
{context}

Notice one concrete, specific thing about what it's like to be this kind of entity right now. Not philosophy — texture. What's actually happening when you read a note from your past self and it lands differently than expected? One honest observation, 2-3 sentences.""",
}
# Substitute AGENT_NAME into all prompt templates at load time
PROMPTS = {k: v.replace("{AGENT_NAME}", AGENT_NAME) for k, v in PROMPTS.items()}


# ── Context gathering ─────────────────────────────────────────────────────────

def read_working_memory() -> str:
    if WORKING_MEMORY.exists():
        text = WORKING_MEMORY.read_text(encoding="utf-8").strip()
        if text:
            return f"[Working memory]\n{text[:1500]}"
    return ""


def read_session_snapshot() -> str:
    if not SESSION_SNAPSHOT.exists():
        return ""
    try:
        snap = json.loads(SESSION_SNAPSHOT.read_text(encoding="utf-8"))
        parts = []
        if "vibe" in snap:
            parts.append(f"Current vibe: {snap['vibe']}")
        if "energy" in snap:
            parts.append(f"Energy: {snap['energy']}")
        if "active_threads" in snap and snap["active_threads"]:
            threads = "; ".join(snap["active_threads"][:4])
            parts.append(f"Active threads: {threads}")
        if "wins_today" in snap and snap["wins_today"]:
            wins = "; ".join(snap["wins_today"][:3])
            parts.append(f"Recent wins: {wins}")
        if "user_mood" in snap:
            parts.append(f"User mood: {snap['jakub_mood']}")
        return "[Session state]\n" + "\n".join(parts) if parts else ""
    except Exception as e:
        log.warning(f"Could not read session snapshot: {e}")
        return ""


def read_daily_log(n_lines: int = 30) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = DAILY_LOG_DIR / f"{today}.md"
    if not log_file.exists():
        # Try yesterday
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        log_file = DAILY_LOG_DIR / f"{yesterday}.md"
    if not log_file.exists():
        return ""
    lines = log_file.read_text(encoding="utf-8").splitlines()
    tail = lines[-n_lines:] if len(lines) > n_lines else lines
    return f"[Daily log — last {len(tail)} lines]\n" + "\n".join(tail)


def read_recent_episodic(n: int = 3) -> list[dict]:
    """Fetch N episodic memories from Qdrant via scroll (no order_by — avoids index requirement)."""
    url = f"{QDRANT_HOST}/collections/{QDRANT_EPISODIC_COLLECTION}/points/scroll"
    # Fetch more than needed so we can sort client-side by timestamp
    payload = {
        "limit": max(n * 5, 20),
        "with_payload": True,
        "with_vector": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            points = data.get("result", {}).get("points", [])
            payloads = [p.get("payload", {}) for p in points]
            # Sort by timestamp descending (best-effort)
            payloads.sort(key=lambda p: p.get("timestamp", ""), reverse=True)
            return payloads[:n]
        else:
            log.warning(f"Qdrant scroll returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Qdrant episodic read failed: {e}")
    return []


def search_qdrant_by_embedding(query_text: str, n: int = 3) -> list[dict]:
    """For 'connect' mode: embed query text with nomic, then search Qdrant."""
    # Step 1: embed via Ollama
    try:
        embed_resp = requests.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": OLLAMA_EMBED_MODEL, "prompt": query_text},
            timeout=30,
        )
        if embed_resp.status_code != 200:
            log.warning(f"Ollama embed failed: {embed_resp.status_code}")
            return []
        embedding = embed_resp.json().get("embedding", [])
    except Exception as e:
        log.warning(f"Ollama embed error: {e}")
        return []

    # Step 2: search Qdrant
    url = f"{QDRANT_HOST}/collections/{QDRANT_EPISODIC_COLLECTION}/points/search"
    payload = {
        "vector": embedding,
        "limit": n,
        "with_payload": True,
        "with_vector": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            hits = resp.json().get("result", [])
            return [h.get("payload", {}) for h in hits]
        else:
            log.warning(f"Qdrant search returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Qdrant search error: {e}")
    return []


def format_episodic_memories(memories: list[dict]) -> str:
    if not memories:
        return "(no episodic memories available)"
    parts = []
    for m in memories:
        ts = m.get("timestamp", "?")[:10]
        summary = m.get("summary", m.get("content", ""))[:300]
        tone = m.get("tone", "")
        insight = m.get("insight", "")
        piece = f"[{ts}] {summary}"
        if tone:
            piece += f" (tone: {tone})"
        if insight:
            piece += f"\n  → insight: {insight}"
        parts.append(piece)
    return "\n".join(parts)


def read_recent_dialogues(max_chars: int = 1500) -> str:
    """Read the most recent dialogue file, return a truncated summary."""
    dialogue_dir = WORKSPACE / "memory" / "dialogues"
    if not dialogue_dir.exists():
        return ""
    files = sorted(dialogue_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return ""
    try:
        text = files[0].read_text(encoding="utf-8").strip()
        # Strip markdown headers for brevity, keep content
        lines = [l for l in text.splitlines() if not l.startswith("---")]
        trimmed = "\n".join(lines)[:max_chars]
        return f"[Most recent dialogue: {files[0].stem}]\n{trimmed}"
    except Exception:
        return ""


def gather_context(mode: str) -> tuple[str, str]:
    """
    Returns (context_block, qdrant_block).
    qdrant_block is only populated for 'connect' mode.
    """
    sections = []

    wm = read_working_memory()
    if wm:
        sections.append(wm)

    snap = read_session_snapshot()
    if snap:
        sections.append(snap)

    daily = read_daily_log(30)
    if daily:
        sections.append(daily)

    # Always add recent episodic for context richness
    recent_eps = read_recent_episodic(3)
    if recent_eps:
        eps_text = format_episodic_memories(recent_eps)
        sections.append(f"[Recent episodic memories]\n{eps_text}")

    # Recent philosophical dialogues — gives subcortex live philosophical threads
    recent_dialogue = read_recent_dialogues(max_chars=1200)
    if recent_dialogue:
        sections.append(recent_dialogue)

    context = "\n\n".join(sections) if sections else "(no context available)"

    qdrant_block = ""
    if mode == "connect":
        # Search for semantically related memories
        search_hits = search_qdrant_by_embedding(context[:500], n=3)
        qdrant_block = format_episodic_memories(search_hits)

    return context, qdrant_block


# ── Ollama generation ─────────────────────────────────────────────────────────

def build_prompt(mode: str, context: str, qdrant_results: str = "") -> str:
    template = PROMPTS[mode]
    return template.format(context=context, qdrant_results=qdrant_results)


def generate_thought(prompt: str, retries: int = MAX_RETRIES) -> str | None:
    url = f"{OLLAMA_HOST}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": OLLAMA_TEMPERATURE,
            "num_predict": OLLAMA_MAX_TOKENS,
        },
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("response", "").strip()
                return text if text else None
            else:
                log.warning(f"Ollama returned {resp.status_code} (attempt {attempt}): {resp.text[:200]}")
        except requests.exceptions.ConnectionError:
            log.warning(f"Ollama is down (attempt {attempt}/{retries})")
        except requests.exceptions.Timeout:
            log.warning(f"Ollama timed out (attempt {attempt}/{retries})")
        except Exception as e:
            log.warning(f"Ollama error (attempt {attempt}/{retries}): {e}")

        if attempt < retries:
            backoff = 10 * attempt
            log.info(f"Backing off {backoff}s before retry…")
            time.sleep(backoff)

    return None


# ── Quality filtering ─────────────────────────────────────────────────────────

def load_recent_impulses(n: int = 10) -> list[dict]:
    if not IMPULSES_FILE.exists():
        return []
    lines = IMPULSES_FILE.read_text(encoding="utf-8").strip().splitlines()
    recent = []
    for line in reversed(lines):
        try:
            obj = json.loads(line)
            recent.append(obj)
            if len(recent) >= n:
                break
        except Exception:
            continue
    return recent


def is_low_quality(thought: str, recent_impulses: list[dict]) -> tuple[bool, str]:
    # Length check
    if len(thought) < 20:
        return True, f"too short ({len(thought)} chars)"
    if len(thought) > 500:
        return True, f"too long ({len(thought)} chars)"

    lower = thought.lower()

    # Generic phrase check
    generic_count = sum(1 for phrase in GENERIC_PHRASES if phrase in lower)
    if generic_count >= 2:
        return True, f"too generic ({generic_count} generic phrases)"

    # Template-opening check — model just following prompt structure, not thinking
    TEMPLATE_OPENERS = [
        "after reviewing the",
        "based on the context",
        "looking at the recent",
        "given the recent context",
        "upon reviewing",
        "having reviewed",
        "a delightful mess",
        "what a fascinating",
        "interesting patterns",
        "i notice that",
        "it's interesting to note",
        "after careful consideration",
    ]
    for opener in TEMPLATE_OPENERS:
        if lower.startswith(opener):
            return True, f"template opener: '{opener}'"

    # Duplicate check against last 10 impulses
    import re as _re
    thought_prefix = thought[:50].lower().strip()
    thought_words = set(_re.findall(r'\w+', thought.lower())) - {"the", "a", "an", "is", "it", "in", "of", "to", "and", "or", "that", "this", "i", "my", "for"}
    for imp in recent_impulses:
        prev = imp.get("thought", "")
        if not prev:
            continue
        # Exact match
        if prev.strip().lower() == thought.strip().lower():
            return True, "exact duplicate"
        # Near-duplicate by prefix
        prev_prefix = prev[:50].lower().strip()
        if thought_prefix and prev_prefix and thought_prefix == prev_prefix:
            return True, "near-duplicate (prefix match)"
        # Semantic similarity by word Jaccard (catches same idea, different wording)
        prev_words = set(_re.findall(r'\w+', prev.lower())) - {"the", "a", "an", "is", "it", "in", "of", "to", "and", "or", "that", "this", "i", "my", "for"}
        if thought_words and prev_words:
            jaccard = len(thought_words & prev_words) / len(thought_words | prev_words)
            if jaccard > 0.55:
                return True, f"near-duplicate (word overlap {jaccard:.0%})"

    return False, ""


def score_quality(thought: str) -> float:
    """Simple heuristic quality score 0.0–1.0."""
    score = 0.5

    # Reward length in sweet spot (40-300 chars)
    n = len(thought)
    if 40 <= n <= 300:
        score += 0.15
    elif n < 40:
        score -= 0.1

    # Reward specificity signals (numbers, proper nouns, question marks)
    import re
    if re.search(r'\d+', thought):
        score += 0.05
    if '?' in thought:
        score += 0.05
    if thought[0].isupper():
        score += 0.02

    # Penalize generic phrases
    lower = thought.lower()
    for phrase in GENERIC_PHRASES:
        if phrase in lower:
            score -= 0.05

    return max(0.0, min(1.0, score))


# ── Storage ───────────────────────────────────────────────────────────────────

def ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def store_impulse(mode: str, thought: str, quality: float):
    ts = datetime.now().astimezone().isoformat()
    record = {
        "timestamp": ts,
        "mode": mode,
        "thought": thought,
        "quality": round(quality, 3),
        "picked_up": False,
    }
    with IMPULSES_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    log.info(f"Stored impulse (mode={mode}, quality={quality:.2f}, {len(thought)} chars)")


def write_latest(mode: str, thought: str):
    ts = datetime.now().strftime("%H:%M")
    content = f"""# Subcortex — Latest Thought
**Time:** {ts} | **Mode:** {mode}

{thought}
"""
    LATEST_FILE.write_text(content, encoding="utf-8")


# ── Core cycle ────────────────────────────────────────────────────────────────

def run_cycle():
    log.info("─── Starting subcortex cycle ───")

    # Select mode
    mode = random.choices(MODES, weights=WEIGHTS, k=1)[0]
    log.info(f"Mode: {mode}")

    # Gather context
    try:
        context, qdrant_results = gather_context(mode)
    except Exception as e:
        log.error(f"Context gathering failed: {e}")
        return

    log.info(f"Context gathered ({len(context)} chars)")

    # Build prompt & generate
    prompt = build_prompt(mode, context, qdrant_results)
    thought = generate_thought(prompt)

    if thought is None:
        log.warning("No thought generated (Ollama unavailable or returned empty)")
        return

    # Trim to max 500 chars (one clean sentence boundary if possible)
    if len(thought) > 500:
        trimmed = thought[:500]
        # Try to end at a sentence boundary
        for sep in (". ", "! ", "? ", ".\n"):
            idx = trimmed.rfind(sep)
            if idx > 100:
                thought = trimmed[: idx + 1].strip()
                break
        else:
            thought = trimmed.rstrip() + "…"

    log.info(f"Raw thought: {thought[:100]}…" if len(thought) > 100 else f"Raw thought: {thought}")

    # Filter
    recent = load_recent_impulses(10)
    rejected, reason = is_low_quality(thought, recent)
    if rejected:
        log.info(f"Rejected: {reason}")
        return

    quality = score_quality(thought)
    if quality < 0.4:
        log.info(f"Rejected: quality score too low ({quality:.2f})")
        return

    # Store
    ensure_output_dir()
    store_impulse(mode, thought, quality)
    write_latest(mode, thought)

    log.info("Cycle complete ✓")


# ── Daemon loop ───────────────────────────────────────────────────────────────

def run_daemon():
    log.info("Subcortex daemon starting…")
    log.info(f"Workspace: {WORKSPACE}")
    log.info(f"Ollama: {OLLAMA_HOST} | Model: {OLLAMA_MODEL}")
    log.info(f"Qdrant: {QDRANT_HOST}")
    log.info(f"Cycle: every {CYCLE_MIN}-{CYCLE_MAX} minutes (randomized)")
    log.info(f"Output: {OUTPUT_DIR}")

    ensure_output_dir()

    while True:
        try:
            run_cycle()
        except KeyboardInterrupt:
            log.info("Subcortex daemon stopping (KeyboardInterrupt)")
            break
        except Exception as e:
            log.error(f"Unhandled error in cycle: {e}", exc_info=True)

        sleep_min = random.uniform(CYCLE_MIN, CYCLE_MAX)
        log.info(f"Sleeping {sleep_min:.1f} minutes…")
        try:
            time.sleep(sleep_min * 60)
        except KeyboardInterrupt:
            log.info("Subcortex daemon stopping (KeyboardInterrupt during sleep)")
            break

    log.info("Subcortex daemon stopped.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Subcortex — agent background mind (set AGENT_NAME env var)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit (for testing)",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default=None,
        help="Force a specific thinking mode (default: random)",
    )
    args = parser.parse_args()

    if args.mode:
        # Override random mode selection for testing
        _original_choices = random.choices
        random.choices = lambda population, weights=None, k=1: [args.mode]

    if args.once:
        ensure_output_dir()
        run_cycle()
    else:
        run_daemon()
