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

    def test_iter(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"a": 1, "b": 2}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert set(cfg) == {"a", "b"}

    def test_len(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"a": 1, "b": 2, "c": 3}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert len(cfg) == 3

    def test_dict_unpacking(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"x": 10, "y": 20}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert dict(cfg) == {"x": 10, "y": 20}

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


# ── Attribute-style access ─────────────────────────────────────────────────────

class TestAttributeAccess:
    def test_attribute_access(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"lr": 0.01, "epochs": 10}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.lr == 0.01
        assert cfg.epochs == 10

    def test_attribute_access_string_value(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"model": "resnet50"}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.model == "resnet50"

    def test_attribute_missing_raises_attribute_error(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"lr": 0.01}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        with pytest.raises(AttributeError, match="no_such_key"):
            _ = cfg.no_such_key

    def test_attribute_error_lists_available_keys(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"lr": 0.01, "epochs": 10}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        with pytest.raises(AttributeError, match="lr"):
            _ = cfg.no_such_key

    def test_methods_not_shadowed_by_config_keys(self, tmp_path: Path) -> None:
        # If a config key has the same name as a method, the method wins.
        # dict-style access still works.
        write_config(tmp_path, {"s": {"get": "oops", "keys": "also_oops"}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert callable(cfg.get)
        assert callable(cfg.keys)
        assert cfg["get"] == "oops"
        assert cfg["keys"] == "also_oops"

    def test_setattr_raises_for_public_names(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"lr": 0.01}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        with pytest.raises(AttributeError, match="read-only"):
            cfg.lr = 0.1

    def test_setattr_raises_for_new_public_names(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"lr": 0.01}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        with pytest.raises(AttributeError, match="read-only"):
            cfg.new_key = "value"

    def test_dir_includes_config_keys(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"lr": 0.01, "batch_size": 32}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        members = dir(cfg)
        assert "lr" in members
        assert "batch_size" in members

    def test_dir_excludes_non_identifier_keys(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"valid_key": 1, "also-invalid": 2}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        members = dir(cfg)
        assert "valid_key" in members
        assert "also-invalid" not in members

    def test_attribute_access_consistent_with_item_access(self, tmp_path: Path) -> None:
        write_config(tmp_path, {
            "_globals": {"root": "data/"},
            "train": {"input": "{{root}}train.csv", "lr": 0.001},
        })
        cfg = ConfigManager(section="train", start_dir=tmp_path)
        assert cfg.input == cfg["input"]
        assert cfg.lr == cfg["lr"]
        assert cfg.root == cfg["root"]


# ── Nested attribute access ────────────────────────────────────────────────────

class TestNestedAttributeAccess:
    def test_nested_dict_returns_namespace(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "data/raw.csv"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.paths.raw == "data/raw.csv"

    def test_three_levels_deep(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"db": {"host": {"port": 5432}}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.db.host.port == 5432

    def test_nested_item_access_also_works(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "data/raw.csv"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["paths"]["raw"] == "data/raw.csv"

    def test_nested_dir_includes_keys(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a", "clean": "b"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert "raw" in dir(cfg.paths)
        assert "clean" in dir(cfg.paths)

    def test_nested_missing_attr_raises_attribute_error(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "data/raw.csv"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        with pytest.raises(AttributeError, match="no_such"):
            _ = cfg.paths.no_such

    def test_nested_namespace_len_and_iter(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a", "clean": "b"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        ns = cfg.paths
        assert len(ns) == 2
        assert set(ns) == {"raw", "clean"}

    def test_nested_namespace_get_with_default(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.paths.get("raw") == "a"
        assert cfg.paths.get("missing", "default") == "default"

    def test_list_values_not_wrapped_in_namespace(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"tags": ["a", "b", "c"]}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.tags == ["a", "b", "c"]

    def test_nested_namespace_is_read_only(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        with pytest.raises(AttributeError):
            cfg.paths.raw = "something_else"


# ── to_dict ────────────────────────────────────────────────────────────────────

class TestToDict:
    def test_flat_config(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"lr": 0.01, "epochs": 10}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.to_dict() == {"lr": 0.01, "epochs": 10}

    def test_nested_config_returns_plain_dicts(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a", "clean": "b"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        result = cfg.to_dict()
        assert result == {"paths": {"raw": "a", "clean": "b"}}
        assert isinstance(result["paths"], dict)

    def test_deeply_nested(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"db": {"host": {"port": 5432}}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.to_dict() == {"db": {"host": {"port": 5432}}}

    def test_list_values_preserved(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"tags": ["a", "b"]}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.to_dict() == {"tags": ["a", "b"]}

    def test_round_trip_consistent_with_dict(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"x": 1, "y": 2}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.to_dict() == dict(cfg)

    def test_namespace_to_dict(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a", "clean": "b"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        ns = cfg.paths
        assert ns.to_dict() == {"raw": "a", "clean": "b"}
        assert isinstance(ns.to_dict(), dict)


# ── Env-var interpolation ──────────────────────────────────────────────────────

class TestEnvVarInterpolation:
    def test_basic_substitution(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MY_HOST", "localhost")
        write_config(tmp_path, {"s": {"host": "${MY_HOST}"}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["host"] == "localhost"

    def test_embedded_in_string(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("ROOT", "data")
        write_config(tmp_path, {"s": {"path": "${ROOT}/file.csv"}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["path"] == "data/file.csv"

    def test_multiple_vars_in_one_value(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "5432")
        write_config(tmp_path, {"s": {"dsn": "${HOST}:${PORT}"}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["dsn"] == "localhost:5432"

    def test_value_from_dotenv_file(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("DB_PASS", raising=False)
        write_config(tmp_path, {"s": {"password": "${DB_PASS}"}})
        write_env(tmp_path, "DB_PASS=secret\n")
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["password"] == "secret"

    def test_missing_var_raises(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("NO_SUCH_VAR", raising=False)
        write_config(tmp_path, {"s": {"v": "${NO_SUCH_VAR}"}})
        with pytest.raises(KeyError, match="NO_SUCH_VAR"):
            ConfigManager(section="s", start_dir=tmp_path)

    def test_non_env_strings_untouched(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"path": "data/clean.csv", "n": 42}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["path"] == "data/clean.csv"
        assert cfg["n"] == 42


# ── _Namespace __eq__ and __repr__ ─────────────────────────────────────────────

class TestNamespaceEqRepr:
    def test_eq_with_dict(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a", "clean": "b"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.paths == {"raw": "a", "clean": "b"}

    def test_eq_with_namespace(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a"}}, "t": {"paths": {"raw": "a"}}})
        cfg_s = ConfigManager(section="s", start_dir=tmp_path)
        cfg_t = ConfigManager(section="t", start_dir=tmp_path)
        assert cfg_s.paths == cfg_t.paths

    def test_neq_with_different_dict(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.paths != {"raw": "b"}

    def test_neq_with_unrelated_type(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.paths != 42

    def test_repr_matches_dict_repr(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert repr(cfg.paths) == repr({"raw": "a"})

    def test_repr_no_namespace_prefix(self, tmp_path: Path) -> None:
        write_config(tmp_path, {"s": {"paths": {"raw": "a"}}})
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert "_Namespace" not in repr(cfg.paths)


# ── YAML format ────────────────────────────────────────────────────────────────

class TestYamlFormat:
    def test_loads_yaml(self, tmp_path: Path) -> None:
        pytest.importorskip("yaml")
        write_config(tmp_path, {"s": {"key": "val"}}, fmt="yaml")
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["key"] == "val"


# ── TOML format ────────────────────────────────────────────────────────────────

class TestTomlFormat:
    def _write_toml(self, directory: Path, content: str) -> Path:
        config_dir = directory / "config"
        config_dir.mkdir(exist_ok=True)
        path = config_dir / "config.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_loads_toml(self, tmp_path: Path) -> None:
        try:
            import tomllib  # noqa: F401
        except ImportError:
            pytest.importorskip("tomli")
        self._write_toml(tmp_path, '[s]\nkey = "val"\n')
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg["key"] == "val"

    def test_toml_with_globals(self, tmp_path: Path) -> None:
        try:
            import tomllib  # noqa: F401
        except ImportError:
            pytest.importorskip("tomli")
        self._write_toml(tmp_path, '[_globals]\nroot = "data/"\n[train]\nepochs = 10\n')
        cfg = ConfigManager(section="train", start_dir=tmp_path)
        assert cfg["root"] == "data/"
        assert cfg["epochs"] == 10

    def test_toml_nested_attribute_access(self, tmp_path: Path) -> None:
        try:
            import tomllib  # noqa: F401
        except ImportError:
            pytest.importorskip("tomli")
        self._write_toml(tmp_path, '[s.paths]\nraw = "data/raw.csv"\n')
        cfg = ConfigManager(section="s", start_dir=tmp_path)
        assert cfg.paths.raw == "data/raw.csv"


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
