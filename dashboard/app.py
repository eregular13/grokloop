"""LocalGrokLoop Streamlit dashboard."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
import redis
import streamlit as st

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DATA_PATH = Path(os.getenv("DATA_PATH", "/data"))
TASKS_PATH = Path(os.getenv("TASKS_PATH", "/tasks"))
HUMAN_INBOX = Path(os.getenv("HUMAN_INBOX", "/human_inbox"))
HUMAN_OUTBOX = Path(os.getenv("HUMAN_OUTBOX", "/human_outbox"))
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b")

st.set_page_config(page_title="LocalGrokLoop", page_icon="🔄", layout="wide")


@st.cache_resource
def get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True)


def load_jsonl(path: Path, limit: int = 50) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    records = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def ollama_status() -> dict:
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(f"{OLLAMA_URL}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return {"ok": True, "models": models}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Header ─────────────────────────────────────────────────────────
st.title("🔄 LocalGrokLoop")
st.caption("Persistent local autonomous agent — observe → plan → act → reflect → store → decide")

col1, col2, col3, col4 = st.columns(4)
r = get_redis()

active = r.get("localgrokloop:active_goal")
hb_path = DATA_PATH / "logs" / "heartbeat.json"
hb_ok = hb_path.exists()
ollama = ollama_status()

col1.metric("Agent", "🟢 Alive" if hb_ok else "🔴 Unknown")
col2.metric("Ollama", "🟢 OK" if ollama["ok"] else "🔴 Down")
col3.metric("Model", OLLAMA_MODEL)
col4.metric("Queue", r.llen("localgrokloop:task_queue"))

# ── Submit goal ────────────────────────────────────────────────────
st.subheader("Submit a goal")
with st.form("submit_goal"):
    goal_text = st.text_area(
        "Goal",
        placeholder="Help me refactor the workspace project and add tests...",
        height=100,
    )
    submitted = st.form_submit_button("Queue goal", type="primary")
    if submitted and goal_text.strip():
        payload = {
            "goal_id": __import__("hashlib").sha256(goal_text.encode()).hexdigest()[:12],
            "goal": goal_text.strip(),
            "source": "dashboard",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        r.rpush("localgrokloop:task_queue", json.dumps(payload))
        r.lpush("localgrokloop:task_history", json.dumps({**payload, "status": "queued"}))
        st.success(f"Queued goal `{payload['goal_id']}`")

# ── Active goal ────────────────────────────────────────────────────
st.subheader("Active goal")
if active:
    data = json.loads(active)
    st.info(f"**{data['goal_id']}** — {data['goal']}")
else:
    st.write("No active goal.")

# ── Human-in-the-loop ──────────────────────────────────────────────
st.subheader("Human-in-the-loop")
hcol1, hcol2 = st.columns(2)

with hcol1:
    st.markdown("**Pending questions**")
    if HUMAN_OUTBOX.exists():
        questions = sorted(HUMAN_OUTBOX.glob("question_*.json"))
        for q in questions[-5:]:
            try:
                data = json.loads(q.read_text(encoding="utf-8"))
                st.warning(f"**{data.get('question', '')}**")
                st.caption(data.get("context", "")[:200])
            except json.JSONDecodeError:
                pass
    else:
        st.write("None")

with hcol2:
    st.markdown("**Send response**")
    with st.form("human_response"):
        response_text = st.text_area("Your answer / approval", height=80)
        if st.form_submit_button("Send to agent"):
            if response_text.strip():
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                path = HUMAN_INBOX / f"response_{ts}.txt"
                HUMAN_INBOX.mkdir(parents=True, exist_ok=True)
                path.write_text(response_text.strip(), encoding="utf-8")
                st.success(f"Saved to `{path.name}`")

# ── Activity log ───────────────────────────────────────────────────
st.subheader("Recent cycles")
cycles = load_jsonl(DATA_PATH / "logs" / "agent_cycles.jsonl", limit=100)
if cycles:
    df = pd.DataFrame(cycles)
    st.dataframe(df, use_container_width=True, height=300)
else:
    st.write("No cycle logs yet.")

# ── Task history ───────────────────────────────────────────────────
with st.expander("Task history"):
    history = r.lrange("localgrokloop:task_history", 0, 19)
    for item in history:
        data = json.loads(item)
        st.write(f"- `{data.get('goal_id', '?')}` [{data.get('source', '?')}] {data.get('goal', '')[:80]}")

# ── Ollama models ──────────────────────────────────────────────────
with st.expander("Ollama models"):
    if ollama["ok"]:
        st.write(", ".join(ollama["models"]))
    else:
        st.error(ollama.get("error", "Unknown error"))

# ── Drop file hint ─────────────────────────────────────────────────
st.divider()
st.markdown(
    f"**Other ways to submit goals:**\n"
    f"- Drop a `.txt` file in `{TASKS_PATH}`\n"
    f"- CLI: `docker compose exec agent python -m main submit \"Your goal here\"`"
)