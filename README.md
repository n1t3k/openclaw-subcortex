# agent-subcortex

> Give your AI agent a background mind.

**agent-subcortex** is a lightweight Python daemon that runs continuous background thinking alongside your AI agent. Instead of only reacting to user inputs, the agent's "subconscious" keeps working between interactions — generating loose associations, surfacing questions, catching blind spots, and connecting current context to older memories.

Inspired by subcortical brain structures, which handle automatic processing, pattern recognition, and diffuse thinking below the threshold of conscious attention.

---

## Why This Is Interesting

Most AI agent architectures are reactive: the agent thinks when asked. But human cognition is never fully idle — background processing continues, making unexpected connections and surfacing insights that weren't explicitly requested.

This daemon emulates that:

- **No GPU required beyond what Ollama already uses** — llama3.1:8b runs locally, cycle takes ~10s
- **Low cost** — 200 tokens per thought, every 7-20 minutes
- **Serendipitous** — associations and questions the agent wouldn't generate on demand
- **Integrated** — agent picks up impulses at its own heartbeat/tick interval

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         AGENT PROCESS                           │
│  (your main agent: handles user, reads impulses at heartbeat)   │
└────────────────────────────┬────────────────────────────────────┘
                             │ reads memory/subconscious/
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                      SUBCORTEX DAEMON                           │
│                                                                 │
│  Context sources          Thinking modes         Output         │
│  ─────────────────        ──────────────         ──────         │
│  working-memory.md   →    associate (30%)   →    impulses.jsonl │
│  session-snapshot    →    question   (25%)  →    latest.md      │
│  daily log           →    creative   (15%)                      │
│  episodic memories   →    worry      (15%)                      │
│                      →    connect    (15%) ← Qdrant search      │
│                                                                 │
│  ┌─────────────────┐      ┌────────────────┐                    │
│  │  Ollama         │      │  Qdrant        │                    │
│  │  llama3.1:8b    │      │  (optional)    │                    │
│  │  nomic-embed    │      │  episodic store│                    │
│  └─────────────────┘      └────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘

Cycle: every 7-20 min (randomized) → gather context → pick mode
     → generate (200 tokens, temp=0.9) → filter → store
```

---

## Requirements

- **Python 3.10+**
- **[Ollama](https://ollama.com)** running locally with `llama3.1:8b` pulled
- `pip install requests`
- **[Qdrant](https://qdrant.tech)** (optional) — only needed for `connect` mode (semantic memory search). Run with Docker: `docker run -p 6333:6333 qdrant/qdrant`

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/n1t3k/agent-subcortex.git
cd agent-subcortex

# 2. Install dependency
pip install requests

# 3. Make sure Ollama is running with the right model
ollama pull llama3.1:8b

# 4. Set workspace (where your agent's memory files live)
export SUBCORTEX_WORKSPACE=/path/to/your/agent/workspace
export AGENT_NAME="my agent"   # optional, shown in prompts

# 5. Run a single test cycle
python subcortex.py --once

# 6. Run as daemon
python subcortex.py

# 7. Or install as systemd user service (Linux)
bash install.sh
```

### Test a specific mode

```bash
python subcortex.py --once --mode associate
python subcortex.py --once --mode worry
python subcortex.py --once --mode creative
```

---

## Memory Layout

Subcortex expects (and creates) this directory structure under `SUBCORTEX_WORKSPACE`:

```
$SUBCORTEX_WORKSPACE/
├── memory/
│   ├── working-memory.md          ← active task / session state (optional)
│   ├── session-snapshot.json      ← vibe, energy, active threads (optional)
│   ├── YYYY-MM-DD.md              ← daily log entries (optional)
│   └── subconscious/              ← OUTPUT (created automatically)
│       ├── impulses.jsonl         ← all generated thoughts
│       └── latest.md              ← most recent thought
```

**None of the input files are required.** If they don't exist, subcortex generates thoughts from "(no context available)" — less interesting, but functional.

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SUBCORTEX_WORKSPACE` | `~/.agent-subcortex` | Root directory for memory files |
| `AGENT_NAME` | `the AI assistant` | Name used in prompts |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model for generation |
| `QDRANT_HOST` | `http://localhost:6333` | Qdrant API endpoint |
| `QDRANT_EPISODIC_COLLECTION` | `agent-episodic` | Collection for episodic memory |

### config.yaml Fields

```yaml
ollama:
  model: llama3.1:8b       # any Ollama model
  max_tokens: 200          # keep short — impulses, not essays
  temperature: 0.9         # high creativity

cycle:
  min_minutes: 7           # randomized interval lower bound
  max_minutes: 20          # randomized interval upper bound

quality:
  min_score: 0.4           # discard low-quality thoughts
```

> **Note:** `config.yaml` documents the design parameters but the daemon currently reads values from the Python constants / env vars. Contributions to wire config.yaml at runtime are welcome.

---

## Thinking Modes

Each cycle, one mode is chosen randomly (weighted):

| Mode | Weight | Prompt Goal | Example Output |
|------|--------|-------------|----------------|
| `associate` | 30% | Find unexpected connections between recent experiences | *"The debugging session and the conversation about habits share the same pattern: small consistent actions over time matter more than heroic effort."* |
| `question` | 25% | Generate genuine curiosity worth exploring | *"Why does the agent perform better on ambiguous tasks in the afternoon? Is this a temperature drift in the model, or is the context window more 'warmed up'?"* |
| `creative` | 15% | Twist, invert, or push something to an extreme | *"What if the memory system worked backwards — instead of storing what happened, it only stored what almost happened?"* |
| `worry` | 15% | Catch blind spots, things about to become problems | *"The episodic index hasn't been pruned in 3 weeks. At current growth rate it will degrade search quality within 10 days."* |
| `connect` | 15% | Bridge today's context to older memories (needs Qdrant) | *"The current work on latency optimization echoes the caching redesign from two months ago — the solution there was counterintuitive: less caching, not more."* |

---

## Integration: The Heartbeat Pattern

The intended integration is a **heartbeat** — a periodic tick in your agent where it reads the latest subcortex output:

```python
import json
from pathlib import Path

WORKSPACE = Path(os.environ.get("SUBCORTEX_WORKSPACE", "~/.agent-subcortex")).expanduser()
IMPULSES = WORKSPACE / "memory" / "subconscious" / "impulses.jsonl"
LATEST = WORKSPACE / "memory" / "subconscious" / "latest.md"

def read_subcortex_impulses(n_unread: int = 3) -> list[dict]:
    """Return up to N unread impulses, mark them as picked up."""
    if not IMPULSES.exists():
        return []
    
    lines = IMPULSES.read_text().strip().splitlines()
    impulses = [json.loads(l) for l in lines if l.strip()]
    
    unread = [i for i in impulses if not i.get("picked_up")][-n_unread:]
    
    # Mark as picked up
    for imp in unread:
        imp["picked_up"] = True
    
    if unread:
        IMPULSES.write_text(
            "\n".join(json.dumps(i, ensure_ascii=False) for i in impulses) + "\n"
        )
    
    return unread

# In your agent's heartbeat / tick:
def agent_heartbeat():
    impulses = read_subcortex_impulses()
    for imp in impulses:
        # Incorporate into context, log, act on, or discard
        print(f"[subcortex/{imp['mode']}] {imp['thought']}")
```

---

## Output Format

### `impulses.jsonl`

One JSON object per line:

```json
{
  "timestamp": "2026-02-24T09:15:30+01:00",
  "mode": "associate",
  "thought": "The recent work on async pipelines and the conversation about decision fatigue share a hidden shape: both are about avoiding the cost of context-switching by batching similar work.",
  "quality": 0.72,
  "picked_up": false
}
```

### `latest.md`

Overwritten each successful cycle:

```markdown
# Subcortex — Latest Thought
**Time:** 09:15 | **Mode:** associate

The recent work on async pipelines and the conversation about decision fatigue share a hidden shape: both are about avoiding the cost of context-switching by batching similar work.
```

---

## Session Snapshot Format

If you want the `user_mood` and `vibe` fields to be picked up, write a `session-snapshot.json` in your workspace:

```json
{
  "vibe": "focused",
  "energy": "high",
  "active_threads": ["refactoring auth module", "performance investigation"],
  "wins_today": ["fixed the race condition", "shipped v1.2"],
  "user_mood": "curious"
}
```

Update this from your agent at session boundaries or significant events.

---

## Quality Filtering

Subcortex filters generated thoughts before storing:

1. **Length** — must be 20–500 chars
2. **Generic phrase check** — rejects thoughts containing ≥2 of: *"as an ai"*, *"everything is connected"*, *"it is important to"*, etc.
3. **Duplicate check** — exact and near-duplicate (prefix) match against last 10 impulses
4. **Quality score** — heuristic based on length, question marks, numbers; must be ≥ 0.4

This keeps the impulses file lean and useful.

---

## Resource Usage

- **VRAM**: llama3.1:8b needs ~5GB (runs alongside your main model if you have enough VRAM)
- **CPU**: minimal between cycles
- **Disk**: impulses.jsonl grows ~200 bytes/cycle; prune periodically
- **Network**: only localhost calls (Ollama + optional Qdrant)

---

## Future Extensions

- **Mood influence**: Adjust mode weights based on session-snapshot emotional state
- **Dream integration**: Batch daytime impulses into a synthesis mode at end-of-day
- **Urgency detection**: If `worry` mode catches something time-sensitive → trigger alert
- **Multi-model**: Use different small models for different modes
- **Config hot-reload**: Watch config.yaml for changes without daemon restart

---

## License

MIT — see [LICENSE](LICENSE).

---

*"The subcortex doesn't think in sentences. It thinks in patterns, pressures, and sudden readiness."*
