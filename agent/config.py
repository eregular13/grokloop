"""Central configuration for LocalGrokLoop."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

AgentMode = Literal["observe", "edit", "build", "operator"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Ollama
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3:14b"
    ollama_planner_model: str = ""

    # Services
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    searxng_url: str = "http://searxng:8080"
    redis_url: str = "redis://redis:6379/0"

    # Paths (inside container)
    workspace_path: Path = Path("/workspace")
    tasks_path: Path = Path("/tasks")
    data_path: Path = Path("/data")
    human_inbox: Path = Path("/human_inbox")
    human_outbox: Path = Path("/human_outbox")
    project_path: Path = Path("/project")

    # Agent mode: observe < edit < build < operator
    agent_mode: AgentMode = "edit"
    enable_docker_tool: bool = False
    self_edit_mode: bool = False

    # Loop tuning
    loop_sleep_seconds: int = 30
    heartbeat_seconds: int = 60
    max_iterations_per_goal: int = 50
    max_goal_elapsed_seconds: int | None = 3600
    max_consecutive_failures: int = 5
    seed_default_goal: bool = False
    tool_timeout_seconds: int = 120
    log_level: str = "INFO"

    # Dashboard
    dashboard_password: str = ""

    # Memory
    memory_collection: str = "localgrokloop_memory"
    memory_top_k: int = 8

    @property
    def planner_model(self) -> str:
        return self.ollama_planner_model or self.ollama_model

    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"

    @property
    def checkpoint_db(self) -> Path:
        path = self.data_path / "checkpoints" / "agent_state.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def log_dir(self) -> Path:
        path = self.data_path / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path


def load_system_prompt() -> str:
    prompt_path = Path(__file__).parent / "prompts" / "system_prompt.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return "You are LocalGrokLoop, a persistent local autonomous agent."


settings = Settings()