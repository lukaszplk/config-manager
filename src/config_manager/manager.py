"""
config_manager.manager
~~~~~~~~~~~~~~~~~~~~~~
Hierarchical config loader for data-processing pipelines.

Features:
  - Walks parent directories to find config.json / config.yaml / config.toml
  - Loads a .env file from the same directory into os.environ
  - Auto-detects the calling script's name as the active section
  - Resolves {{section.key}} cross-references between sections
  - Supports JSON, YAML, and TOML formats

Typical layout::

    project/
    ├── .env
    ├── config.json
    ├── script01.py
    └── pipeline/
        └── script02.py   ← ConfigManager() walks up and finds config.json

config.json example::

    {
        "script01": {"output": "results/clean.csv"},
        "script02": {"input": "{{script01.output}}", "model": "rf"}
    }
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

_REF_PATTERN = re.compile(r"\{\{(\w+)\.(\w+)\}\}")
_CONFIG_NAMES = ("config.json", "config.yaml", "config.yml", "config.toml")
_ENV_NAME = ".env"


def _find_config(start: Path) -> Optional[Path]:
    """Walk from *start* upward until a config file is found."""
    current = start.resolve()
    while True:
        for name in _CONFIG_NAMES:
            candidate = current / name
            if candidate.is_file():
                return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _load_file(path: Path) -> dict:
    """Parse JSON, YAML, or TOML and return a dict."""
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")

    if suffix == ".json":
        return json.loads(text)

    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise ImportError(
                "PyYAML is required for YAML config files: pip install pyyaml"
            ) from e
        return yaml.safe_load(text) or {}

    if suffix == ".toml":
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore
            except ImportError as e:
                raise ImportError(
                    "tomli is required for TOML config files on Python <3.11: "
                    "pip install tomli"
                ) from e
        return tomllib.loads(text)

    raise ValueError(f"Unsupported config format: {path.suffix}")


def _load_env(env_path: Path) -> None:
    """Parse a .env file and set variables into os.environ (skip if missing)."""
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _resolve_refs(value: Any, raw: dict) -> Any:
    """Recursively resolve {{section.key}} references in *value*."""
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            section, key = match.group(1), match.group(2)
            try:
                resolved = raw[section][key]
            except KeyError:
                raise KeyError(
                    f"Config reference {{{{{section}.{key}}}}} could not be "
                    f"resolved — section={section!r} key={key!r}"
                )
            return str(_resolve_refs(resolved, raw))

        return _REF_PATTERN.sub(replace, value)

    if isinstance(value, dict):
        return {k: _resolve_refs(v, raw) for k, v in value.items()}

    if isinstance(value, list):
        return [_resolve_refs(v, raw) for v in value]

    return value


def _caller_stem() -> Optional[str]:
    """Return the stem of the first non-library frame's filename."""
    this_file = Path(__file__).resolve()
    for frame_info in inspect.stack():
        path = Path(frame_info.filename).resolve()
        if path == this_file:
            continue
        # skip pytest / standard library internals
        if any(part in path.parts for part in ("pytest", "_pytest", "pluggy")):
            continue
        stem = path.stem
        if stem not in ("<string>", "<stdin>"):
            return stem
    return None


class ConfigManager:
    """Hierarchical config loader with cross-section reference resolution.

    On construction:
      1. Walks parent directories from the calling script's location
         (or *start_dir*) until ``config.json`` / ``config.yaml`` /
         ``config.toml`` is found.
      2. Loads ``.env`` from the same directory into ``os.environ``
         (existing env vars are never overwritten).
      3. Determines the active *section* — defaults to the calling
         script's filename stem (e.g. ``script02`` for ``script02.py``).
      4. Resolves ``{{section.key}}`` cross-references in the active
         section's values.

    Args:
        section: Config section to expose.  Defaults to the calling
            script's filename stem.  Pass explicitly to override.
        start_dir: Directory to start searching from.  Defaults to the
            calling script's directory.
        logger: Optional :class:`logging.Logger` for internal events.

    Raises:
        FileNotFoundError: If no config file is found in any parent dir.
        KeyError: If *section* is not present in the config file.

    Example::

        # config.json
        # {
        #   "preprocess": {"output": "results/clean.csv"},
        #   "train":      {"input": "{{preprocess.output}}", "lr": 0.01}
        # }

        # train.py
        from config_manager import ConfigManager
        cfg = ConfigManager()           # section="train" auto-detected
        cfg["input"]                    # → "results/clean.csv"
        cfg["lr"]                       # → 0.01
        cfg.get("missing", "default")   # → "default"
    """

    def __init__(
        self,
        section: Optional[str] = None,
        *,
        start_dir: Optional[str | Path] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._log = logger

        # determine search root
        if start_dir is not None:
            search_root = Path(start_dir).resolve()
        else:
            # use caller's directory
            caller_frame = inspect.stack()[1]
            search_root = Path(caller_frame.filename).resolve().parent

        # find config file
        config_path = _find_config(search_root)
        if config_path is None:
            raise FileNotFoundError(
                f"No config file found searching upward from {search_root}"
            )
        if self._log:
            self._log.debug("Config file: %s", config_path)

        # load .env from the same directory
        env_path = config_path.parent / _ENV_NAME
        _load_env(env_path)
        if self._log and env_path.is_file():
            self._log.debug("Loaded .env from %s", env_path)

        # parse config
        raw = _load_file(config_path)

        # determine section
        if section is None:
            section = _caller_stem()
        if section is None:
            raise ValueError(
                "Could not auto-detect section name. "
                "Pass section= explicitly."
            )
        if section not in raw:
            raise KeyError(
                f"Section {section!r} not found in {config_path}. "
                f"Available: {list(raw)}"
            )
        if self._log:
            self._log.debug("Active section: %r", section)

        # resolve cross-references
        self._data: dict = _resolve_refs(raw[section], raw)
        self._section = section
        self._config_path = config_path

    # ── Mapping interface ──────────────────────────────────────────────────────

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    # ── Introspection ──────────────────────────────────────────────────────────

    @property
    def section(self) -> str:
        """The active config section name."""
        return self._section

    @property
    def config_path(self) -> Path:
        """Path to the config file that was loaded."""
        return self._config_path

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"section={self._section!r}, "
            f"config={self._config_path.name!r})"
        )
