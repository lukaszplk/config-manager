"""Tests for ConfigManager."""

import json
import logging
import os
from pathlib import Path

import pytest

from config_manager import ConfigManager


# ── Helpers ────────────────────────────────────────────────────────────────────

def write_config(directory: Path, data: dict, fmt: str = "json") -> Path:
    config_dir = directory / "config"
    config_dir.mkdir(exist_ok=True)
    path = config_dir / f"config.{fmt}"
    if fmt == "json":
        path.write_text(json.dumps(data), encoding="utf-8")
    elif fmt in ("yaml", "yml"):
        import yaml
        path.write_text(yaml.dump(data), encoding="utf-8")
    return path


def write_env(directory: Path, content: str) -> Path:
    config_dir = directory / "config"
    config_dir.mkdir(exist_ok=True)
    path = config_dir / ".env"
    path.write_text(content, encoding="utf-8")
    return path


# ── Basic loading ──────────────────────────────────────────────────────────────

class TestBasicLoading:
    def test_loads_section_by_name(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"myscript": {"key": "value"}})
        cfg = ConfigManager(section="myscript", start_dir=tmp_path)
        assert cfg["key"] == "value"

    def test_get_with_default(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"a": 1}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.get("missing", "default") == "default"

    def test_contains(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"x": 1}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert "x" in cfg
        assert "y" not in cfg

    def test_mapping_interface(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"a": 1, "b": 2}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert set(cfg.keys()) == {"a", "b"}
        assert set(cfg.values()) == {1, 2}
        assert dict(cfg.items()) == {"a": 1, "b": 2}

    def test_section_property(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.section == "s"

    def test_config_path_property(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.config_path == tmp_path / "config" / "config.json"


# ── Parent directory search ────────────────────────────────────────────────────

class TestParentSearch:
    def test_finds_config_in_parent(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"v": 42}})
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        cfg = ConfigManager(section="s", start_dir=nested)
        assert cfg["v"] == 42

    def test_raises_if_no_config(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError):
            ConfigManager(section="s", start_dir=empty)

    def test_raises_if_section_missing(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"other": {}})
        with pytest.raises(KeyError, match="other"):
            ConfigManager(section="s", start_dir=tmp_path)


# ── .env loading ───────────────────────────────────────────────────────────────

class TestEnvLoading:
    def test_env_vars_set(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("MY_VAR", raising=False)
        write_config(tmp_path, {"s": {}})
        write_env(tmp_path, "MY_VAR=hello\n")
        ConfigManager(section="s", start_dir=tmp_path)
        assert os.environ["MY_VAR"] == "hello"

    def test_existing_env_not_overwritten(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MY_VAR", "original")
        write_config(tmp_path, {"s": {}})
        write_env(tmp_path, "MY_VAR=new_value\n")
        ConfigManager(section="s", start_dir=tmp_path)
        assert os.environ["MY_VAR"] == "original"

    def test_env_comments_ignored(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("REAL_VAR", raising=False)
        write_config(tmp_path, {"s": {}})
        write_env(tmp_path, "# comment\nREAL_VAR=yes\n")
        ConfigManager(section="s", start_dir=tmp_path)
        assert os.environ["REAL_VAR"] == "yes"

    def test_missing_env_file_silently_ignored(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"k": "v"}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["k"] == "v"


# ── Reference resolution ───────────────────────────────────────────────────────

class TestReferenceResolution:
    def test_simple_reference(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "a": {"output": "results/clean.csv"},
            "b": {"input": "{{a.output}}"},
        })
        cfg = ConfigManager(section="b", start_dir=tmp_path)
        assert cfg["input"] == "results/clean.csv"

    def test_reference_embedded_in_string(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "a": {"dir": "results"},
            "b": {"path": "{{a.dir}}/model.pt"},
        })
        cfg = ConfigManager(section="b", start_dir=tmp_path)
        assert cfg["path"] == "results/model.pt"

    def test_multiple_references_in_one_value(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "a": {"x": "foo", "y": "bar"},
            "b": {"combined": "{{a.x}}_{{a.y}}"},
        })
        cfg = ConfigManager(section="b", start_dir=tmp_path)
        assert cfg["combined"] == "foo_bar"

    def test_reference_in_nested_dict(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "a": {"out": "file.csv"},
            "b": {"paths": {"data": "{{a.out}}"}},
        })
        cfg = ConfigManager(section="b", start_dir=tmp_path)
        assert cfg["paths"]["data"] == "file.csv"

    def test_reference_in_list(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "a": {"file": "data.csv"},
            "b": {"inputs": ["{{a.file}}", "static.csv"]},
        })
        cfg = ConfigManager(section="b", start_dir=tmp_path)
        assert cfg["inputs"][0] == "data.csv"

    def test_unresolved_section_raises_with_hint(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "b": {"input": "{{missing.key}}"},
        })
        with pytest.raises(KeyError, match="missing"):
            ConfigManager(section="b", start_dir=tmp_path)

    def test_unresolved_key_raises_with_hint(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "a": {"x": 1},
            "b": {"v": "{{a.no_such_key}}"},
        })
        with pytest.raises(KeyError, match="no_such_key"):
            ConfigManager(section="b", start_dir=tmp_path)

    def test_non_reference_value_unchanged(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"n": 42, "lst": [1, 2]}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["n"] == 42
        assert cfg["lst"] == [1, 2]


# ── Deep (multi-level) references ─────────────────────────────────────────────

class TestDeepReferences:
    def test_three_level_reference(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "shared": {"paths": {"raw": "data/raw.csv"}},
            "train":  {"input": "{{shared.paths.raw}}"},
        })
        cfg = ConfigManager(section="train", start_dir=tmp_path)
        assert cfg["input"] == "data/raw.csv"

    def test_four_level_reference(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "shared": {"db": {"host": {"port": "5432"}}},
            "app":    {"port": "{{shared.db.host.port}}"},
        })
        cfg = ConfigManager(section="app", start_dir=tmp_path)
        assert cfg["port"] == "5432"

    def test_deep_ref_missing_intermediate_key_raises(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "a": {"x": {"y": 1}},
            "b": {"v": "{{a.x.missing}}"},
        })
        with pytest.raises(KeyError, match="missing"):
            ConfigManager(section="b", start_dir=tmp_path)


# ── _globals section ───────────────────────────────────────────────────────────

class TestGlobals:
    def test_globals_available_in_section(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "_globals": {"version": "v2", "root": "data/"},
            "train":    {"epochs": 10},
        })
        cfg = ConfigManager(section="train", start_dir=tmp_path)
        assert cfg["version"] == "v2"
        assert cfg["root"] == "data/"
        assert cfg["epochs"] == 10

    def test_section_overrides_globals(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "_globals": {"lr": 0.001},
            "train":    {"lr": 0.01},
        })
        cfg = ConfigManager(section="train", start_dir=tmp_path)
        assert cfg["lr"] == 0.01  # section value wins

    def test_reference_to_globals_via_explicit_prefix(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "_globals": {"root": "data/"},
            "train":    {"path": "{{_globals.root}}train.csv"},
        })
        cfg = ConfigManager(section="train", start_dir=tmp_path)
        assert cfg["path"] == "data/train.csv"

    def test_bare_reference_resolves_from_globals(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "_globals": {"root": "data/"},
            "train":    {"path": "{{root}}/train.csv"},
        })
        cfg = ConfigManager(section="train", start_dir=tmp_path)
        assert cfg["path"] == "data//train.csv"

    def test_bare_reference_missing_raises_with_hint(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "s": {"v": "{{no_section_prefix}}"},
        })
        with pytest.raises(KeyError, match="_globals"):
            ConfigManager(section="s", start_dir=tmp_path)

    def test_globals_not_listed_as_available_section(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "_globals": {"x": 1},
            "s": {},
        })
        with pytest.raises(KeyError) as exc_info:
            ConfigManager(section="missing", start_dir=tmp_path)
        assert "_globals" not in str(exc_info.value)


# ── YAML format ────────────────────────────────────────────────────────────────

class TestYamlFormat:
    def test_loads_yaml(self, tmp_path: Path) -> None:
        pytest.importorskip("yaml")
        write_config(tmp_path, {"s": {"key": "val"}}, fmt="yaml")
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["key"] == "val"


# ── Logger injection ───────────────────────────────────────────────────────────

class TestLogger:
    def test_logger_receives_debug_messages(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"k": "v"}})
        log = logging.getLogger("test_cfg")
        messages: list[str] = []
        handler = logging.handlers_list = []

        class Capture(logging.Handler):
            def emit(self, record):
                messages.append(record.getMessage())

        log.addHandler(Capture())
        log.setLevel(logging.DEBUG)
        ConfigManager(section="s", start_dir=tmp_path, logger=log)
        assert any("Config file" in m for m in messages)
        assert any("Active section" in m for m in messages)

    def test_none_logger_is_silent(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {}})
        # should not raise even with no logger
        cfg = ConfigManager(section="s", start_dir=tmp_path, logger=None)
        assert cfg.section == "s"


# ── Repr ───────────────────────────────────────────────────────────────────────

class TestRepr:
    def test_contains_section(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"mysection": {}})
        cfg = ConfigManager(section="mysection", start_dir=tmp_path)
        assert "mysection" in repr(cfg)

    def test_contains_filename(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert "config.json" in repr(cfg)
