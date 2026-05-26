"""
config_manager.manager
~~~~~~~~~~~~~~~~~~~~~~
Hierarchical config loader for data-processing pipelines.

Features:
  - Walks parent directories to find config.json / config.yaml / config.toml
  - Loads a .env file from the same directory into os.environ
  - Auto-detects the calling script's name as the active section
  - Special ``_globals`` section: its values are merged into every section
    so they are directly accessible without a prefix (section values win)
  - Resolves ``{{section.key.subkey}}`` cross-references (arbitrary depth)
  - Supports JSON, YAML, and TOML formats

Typical layout::

    project/
    ├── config/
    │   ├── config.json
    │   └── .env
    ├── script01.py
    └── pipeline/
        └── script02.py   ← ConfigManager() walks up and finds config/config.json

config/config.json example::

    {
        "_globals": {"root": "data/", "version": "v2"},
        "script01": {"output": "{{root}}clean.csv"},
        "script02": {
            "input":  "{{script01.output}}",
            "model":  "rf",
            "run_id": "{{version}}"
        }
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

# Matches {{any.dot.path}} — first segment is the section name (or a globals key),
# subsequent segments are nested keys within that section.
_REF_PATTERN = re.compile(r"\{\{([\w]+(?:\.[\w]+)*)\}\}")

_CONFIG_DIR = "config"
_CONFIG_NAMES = ("config.json", "config.yaml", "config.yml", "config.toml")
_ENV_NAME = ".env"
_GLOBALS_KEY = "_globals"


def _find_config(start: Path) -> Optional[Path]:
    """Walk from *start* upward until a ``config/<file>`` is found."""
    current = start.resolve()
    while True:
        for name in _CONFIG_NAMES:
            candidate = current / _CONFIG_DIR / name
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


def _deep_get(data: dict, path: str) -> Any:
    """Retrieve a value from nested dicts using a dot-separated *path*.

    Raises KeyError with a descriptive message if any segment is missing.
    """
    keys = path.split(".")
    current: Any = data
    traversed: list[str] = []
    for key in keys:
        if not isinstance(current, dict):
            raise KeyError(
                f"Cannot index into {type(current).__name__!r} "
                f"at {'.'.join(traversed)!r} (looking for key {key!r})"
            )
        if key not in current:
            available = list(current.keys()) if isinstance(current, dict) else []
            raise KeyError(
                f"Key {key!r} not found"
                + (f" under {'.'.join(traversed)!r}" if traversed else "")
                + (f". Available: {available}" if available else "")
            )
        traversed.append(key)
        current = current[key]
    return current


def _resolve_refs(value: Any, raw: dict, *, _context: str = "") -> Any:
    """Recursively resolve ``{{path}}`` references in *value*.

    *raw* is the full, unresolved config dict (all sections).
    ``{{path}}`` — first segment is the section name; subsequent segments are
    nested keys.  For single-segment paths (e.g. ``{{version}}``) the lookup
    falls back to ``_globals`` if present.
    """
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            full_path = match.group(1)
            parts = full_path.split(".", 1)

            if len(parts) == 1:
                # bare key → look in _globals first
                key = parts[0]
                globals_data = raw.get(_GLOBALS_KEY, {})
                if key not in globals_data:
                    raise KeyError(
                        f"Reference {{{{{{ {full_path} }}}}}}: "
                        f"no section prefix given and {key!r} not found in "
                        f"'_globals'. Use {{{{section.{key}}}}} or add it to "
                        f"'_globals'."
                    )
                resolved = globals_data[key]
            else:
                section, remainder = parts
                if section not in raw:
                    raise KeyError(
                        f"Reference {{{{{{ {full_path} }}}}}}: "
                        f"section {section!r} not found. "
                        f"Available sections: {[k for k in raw if not k.startswith('_')]}"
                    )
                try:
                    resolved = _deep_get(raw[section], remainder)
                except KeyError as exc:
                    raise KeyError(
                        f"Reference {{{{{{ {full_path} }}}}}}: {exc}"
                        + (f" (in {_context})" if _context else "")
                    ) from exc

            return str(_resolve_refs(resolved, raw, _context=full_path))

        return _REF_PATTERN.sub(replace, value)

    if isinstance(value, dict):
        return {k: _resolve_refs(v, raw, _context=_context) for k, v in value.items()}

    if isinstance(value, list):
        return [_resolve_refs(v, raw, _context=_context) for v in value]

    return value


def _caller_stem() -> Optional[str]:
    """Return the stem of the first non-library frame's filename."""
    this_file = Path(__file__).resolve()
    for frame_info in inspect.stack():
        path = Path(frame_info.filename).resolve()
        if path == this_file:
            continue
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
      3. Merges the special ``_globals`` section (if present) into the
         active section — globals act as default values, section keys win.
      4. Determines the active *section* — defaults to the calling
         script's filename stem (e.g. ``script02`` for ``script02.py``).
      5. Resolves ``{{section.key.subkey}}`` cross-references in the
         active section's values (arbitrary depth).

    Args:
        section: Config section to expose.  Defaults to the calling
            script's filename stem.  Pass explicitly to override.
        start_dir: Directory to start searching from.  Defaults to the
            calling script's directory.
        logger: Optional :class:`logging.Logger` for internal events.

    Raises:
        FileNotFoundError: If no config file is found in any parent dir.
        KeyError: If *section* is not present in the config file, or a
            ``{{reference}}`` cannot be resolved.

    Examples::

        # config.json
        # {
        #   "_globals": {"root": "data/", "version": "v2"},
        #   "preprocess": {"output": "{{root}}clean.csv"},
        #   "train": {
        #       "input":   "{{preprocess.output}}",
        #       "lr":      0.01,
        #       "run_id":  "{{version}}"
        #   }
        # }

        # train.py
        from config_manager import ConfigManager

        log = logging.getLogger(__name__)
        cfg = ConfigManager(logger=log)     # section="train" auto-detected

        cfg["input"]                        # → "data/clean.csv"
        cfg["lr"]                           # → 0.01
        cfg["version"]                      # → "v2"  (from _globals)
        cfg.get("missing", "default")       # → "default"
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

        available = [k for k in raw if not k.startswith("_")]
        if section not in raw:
            raise KeyError(
                f"Section {section!r} not found in {config_path.name}. "
                f"Available: {available}"
            )
        if self._log:
            self._log.debug(
                "Active section: %r  |  globals: %s  |  config: %s",
                section,
                list(raw.get(_GLOBALS_KEY, {}).keys()),
                config_path,
            )

        # merge _globals (base) + section (wins) → resolve references
        merged: dict = {**raw.get(_GLOBALS_KEY, {}), **raw[section]}
        self._data: dict = _resolve_refs(merged, raw, _context=section)
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
