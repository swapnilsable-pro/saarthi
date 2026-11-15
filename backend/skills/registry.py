"""Load and validate the tool registry (registry.yaml)."""
from __future__ import annotations

import datetime as dt
import subprocess
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_FILE = Path(__file__).with_name("registry.yaml")


class TimeFlag(BaseModel):
    flag: str
    format: str

    def render(self, as_of: dt.datetime) -> list[str]:
        return [self.flag, as_of.strftime(self.format)]


class Repo(BaseModel):
    key: str
    path: Path
    fixtures: Path
    min_python: str

    @property
    def abs_path(self) -> Path:
        return ROOT / self.path

    @property
    def abs_fixtures(self) -> Path:
        return ROOT / self.fixtures


class ToolSpec(BaseModel):
    id: str
    repo: str
    script: str
    command: list[str] = Field(default_factory=list)
    role: str
    json_flag: str | None = Field(default=None, alias="json")
    no_write: bool = False
    time_flag: TimeFlag | None = None
    network: bool = True
    timeout: int = 120
    smoke: list[str] = Field(default_factory=list)
    smoke_as_of: str | None = None

    model_config = {"populate_by_name": True}

    @property
    def point_in_time(self) -> bool:
        return self.time_flag is not None


class Registry(BaseModel):
    repos: dict[str, Repo]
    tools: dict[str, ToolSpec]

    def tool(self, tool_id: str) -> ToolSpec:
        try:
            return self.tools[tool_id]
        except KeyError:
            raise KeyError(f"unknown tool {tool_id!r}") from None

    def script_path(self, spec: ToolSpec) -> Path:
        return self.repos[spec.repo].abs_path / spec.script

    def placeholders(self) -> dict[str, str]:
        return {f"{k}_fx": str(r.abs_fixtures) for k, r in self.repos.items()}

    def expand(self, args: list[str]) -> list[str]:
        ph = self.placeholders()
        return [a.format(**ph) if "{" in a else a for a in args]


def load_registry(path: Path = REGISTRY_FILE) -> Registry:
    raw = yaml.safe_load(path.read_text())
    repos = {k: Repo(key=k, **v) for k, v in raw["repos"].items()}
    tools: dict[str, ToolSpec] = {}
    for entry in raw["tools"]:
        spec = ToolSpec.model_validate(entry)
        if spec.id in tools:
            raise ValueError(f"duplicate tool id {spec.id}")
        if spec.repo not in repos:
            raise ValueError(f"{spec.id}: unknown repo {spec.repo}")
        tools[spec.id] = spec
    return Registry(repos=repos, tools=tools)


@lru_cache
def registry() -> Registry:
    return load_registry()


@lru_cache
def repo_sha(repo_key: str) -> str:
    """Commit of the vendored repo; part of every tool_runs row for reproducibility."""
    path = registry().repos[repo_key].abs_path
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
