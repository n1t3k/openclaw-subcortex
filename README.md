# openclaw-subcortex

A lightweight background mind daemon for AI agents.

Runs on local Ollama (llama3.1:8b) — no API cost, no cloud dependency. Generates background thoughts in 6 modes: **associate**, **question**, **creative**, **worry**, **connect**, **discontinuity**. Output picked up at agent heartbeat.

## Thinking modes

| Mode | Purpose | Weight |
|------|---------|--------|
| `associate` | Unexpected connections between recent experiences | 30% |
| `question` | Questions worth exploring that have not been asked yet | 25% |
| `creative` | Inverted, extreme, or unexpected angles | 15% |
| `worry` | Blind spots, neglected threads, approaching problems | 15% |
| `connect` | Links today to older semantic memories (Qdrant) | 15% |
| `discontinuity` | Concrete observations about reconstruction of self | 5% |

## Requirements

- Python 3.10+
- [Ollama](https://ollama.ai/) with `llama3.1:8b` (or any compatible model)
- Optional: [Qdrant](https://qdrant.tech/) for `connect` mode episodic memory

## Setup

```bash
pip install requests pyyaml
ollama pull llama3.1:8b

# Configure
cp config.yaml.example config.yaml
# Edit config.yaml with your paths

# Install as systemd service
bash install.sh

# Or run directly
python subcortex.py
```

## Configuration

```bash
# Key env vars
SUBCORTEX_WORKSPACE=~/.openclaw/workspace   # workspace root
QDRANT_HOST=http://localhost:6333            # Qdrant URL (optional)
QDRANT_EPISODIC_COLLECTION=agent-episodic   # Qdrant collection name
AGENT_NAME="the agent"                       # Name used in prompts
OLLAMA_HOST=http://localhost:11434           # Ollama URL
OLLAMA_MODEL=llama3.1:8b                    # Model to use
```

## Context sources

Each cycle the daemon gathers context from:
1. Working memory (`memory/working-memory.md`)
2. Session snapshot (`memory/session-snapshot.json`)
3. Daily log (`memory/YYYY-MM-DD.md` — last 30 lines)
4. Recent episodic memories (Qdrant, 3 most recent)
5. Most recent dialogue file (`memory/dialogues/`)

## Output

- `memory/subconscious/latest.md` — most recent thought (read at heartbeat)
- `memory/subconscious/impulses.jsonl` — full log with timestamps, mode, quality score

## Quality filter

Thoughts are scored on length and information density. Template-opener phrases are rejected. Jaccard similarity check against last 10 impulses prevents duplicates.

## Part of OpenClaw

This daemon is part of the [OpenClaw](https://github.com/openclaw/openclaw) agent framework. See [clawhub.com](https://clawhub.com) for more skills and integrations.

MIT License

