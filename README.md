# config-manager

[![CI](https://github.com/lukaszplk/config-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/lukaszplk/config-manager/actions/workflows/ci.yml)

A lightweight, zero-dependency config loader for Python data-processing pipelines.

- Walks **parent directories** automatically to find `config.json`, `config.yaml`, or `config.toml`
- Loads `.env` from the same directory into `os.environ` (without overwriting existing vars)
- **Auto-detects** the calling script's name as the active section — no boilerplate
- Resolves `{{section.key}}` cross-references between sections

## Install

```bash
pip install config-manager
```

With YAML support:
```bash
pip install "config-manager[yaml]"
```

## Quick start

```
project/
├── config.json
├── preprocess.py
└── pipeline/
    └── train.py   ← ConfigManager() walks up and finds config.json
```

**config.json**
```json
{
    "preprocess": {
        "output": "results/clean.csv"
    },
    "train": {
        "input":  "{{preprocess.output}}",
        "lr":     0.01,
        "epochs": 50
    }
}
```

**train.py**
```python
from config_manager import ConfigManager

cfg = ConfigManager()     # section="train" detected automatically

print(cfg["input"])       # results/clean.csv  (resolved from preprocess)
print(cfg["lr"])          # 0.01
print(cfg.get("device", "cpu"))  # cpu (default)
```

## Use cases

### 1 — Multi-step pipeline

Each script reads only its own section; `{{section.key}}` wires them together.

```python
# preprocess.py
cfg = ConfigManager()
df.to_csv(cfg["output"])

# train.py
cfg = ConfigManager()
df = pd.read_csv(cfg["input"])   # resolves to preprocess.output automatically
```

### 2 — Override section explicitly

```python
cfg = ConfigManager(section="shared")
db_url = cfg["db_url"]
```

### 3 — Logger injection

```python
import logging
log = logging.getLogger(__name__)
cfg = ConfigManager(logger=log)
```

### 4 — Custom search root

```python
cfg = ConfigManager(start_dir="/path/to/project")
```

## Config file formats

| File | Notes |
|------|-------|
| `config.json` | No extra dependencies |
| `config.yaml` / `config.yml` | Requires `pip install pyyaml` |
| `config.toml` | Built-in on Python 3.11+; `pip install tomli` on older |

## Reference syntax

Use `{{section.key}}` anywhere in a string value to reference another section's key:

```json
{
    "shared": {"root": "data/"},
    "train":  {"input": "{{shared.root}}train.csv"}
}
```

References are resolved recursively and work inside nested dicts and lists.

## API

### `ConfigManager(section=None, *, start_dir=None, logger=None)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `section` | `str` | auto-detected | Config section to load |
| `start_dir` | `str \| Path` | caller's directory | Where to start searching |
| `logger` | `logging.Logger` | `None` | Logger for internal events |

### Properties

| Property | Returns | Description |
|----------|---------|-------------|
| `section` | `str` | Active section name |
| `config_path` | `Path` | Resolved path to the config file |

### Dict-like access

```python
cfg["key"]             # direct access (KeyError if missing)
cfg.get("key", None)   # with default
"key" in cfg           # membership test
cfg.keys() / .values() / .items()
```

## Development

```bash
git clone https://github.com/lukaszplk/config-manager
cd config-manager
pip install -e ".[dev]"
pytest
```
