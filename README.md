# config-manager

[![CI](https://github.com/lukaszplk/config-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/lukaszplk/config-manager/actions/workflows/ci.yml)

A lightweight, zero-dependency config loader for Python data-processing pipelines.

- Walks **parent directories** automatically to find `config.json`, `config.yaml`, or `config.toml`
- Loads `.env` from the same directory into `os.environ` (without overwriting existing vars)
- **Auto-detects** the calling script's name as the active section — no boilerplate
- Special **`_globals` section** — its values are merged into every section automatically
- Resolves **`{{section.key.subkey}}`** cross-references at arbitrary depth
- Interpolates **`${ENV_VAR}`** placeholders from `os.environ` in string values
- Attribute-style access with IDE tab-completion (`cfg.lr`, `cfg.paths.raw`)
- Clear error messages when a reference can't be resolved

## Install

```bash
pip install refconf-manager
```

With YAML support:
```bash
pip install "refconf-manager[yaml]"
```

## Quick start

```
project/
├── config/
│   ├── config.json
│   └── .env
├── preprocess.py
└── pipeline/
    └── train.py   ← ConfigManager() walks up and finds config/config.json
```

**config/config.json**
```json
{
    "_globals": {
        "root":    "data/",
        "version": "v2"
    },
    "preprocess": {
        "output": "{{root}}clean.csv"
    },
    "train": {
        "input":   "{{preprocess.output}}",
        "lr":      0.01,
        "run_id":  "{{version}}"
    }
}
```

**train.py**
```python
from refconf_manager import ConfigManager

cfg = ConfigManager()       # section="train" detected from filename

cfg["input"]                # → "data/clean.csv"  (resolved via preprocess)
cfg.input                   # → "data/clean.csv"  (attribute-style shorthand)
cfg["lr"]                   # → 0.01
cfg.lr                      # → 0.01
cfg["version"]              # → "v2"  (injected from _globals)
cfg["run_id"]               # → "v2"
cfg.get("device", "cpu")    # → "cpu"  (default)
```

## Use cases

### 1 — Multi-step pipeline

Each script reads only its own section. `{{section.key}}` wires outputs to inputs.

```python
# preprocess.py
cfg = ConfigManager()
df.to_csv(cfg["output"])   # saves to "data/clean.csv"

# train.py
cfg = ConfigManager()
df = pd.read_csv(cfg["input"])   # reads "data/clean.csv" automatically
```

### 2 — Shared constants with `_globals`

Put anything shared (paths, versions, DB hosts) in `_globals` and access it directly in every section without any `{{...}}` syntax.

```json
{
    "_globals": {
        "db_host": "localhost",
        "root":    "data/"
    },
    "etl":  { "source": "{{root}}raw.csv" },
    "api":  { "host":   "{{db_host}}" }
}
```

```python
cfg = ConfigManager()
cfg["db_host"]   # available in every section
```

### 3 — Deep nested references

Reference values at any depth using dot notation.

```json
{
    "infra": {
        "storage": { "bucket": "my-bucket", "prefix": "runs/" }
    },
    "train": {
        "output": "{{infra.storage.bucket}}/{{infra.storage.prefix}}model.pt"
    }
}
```

```python
cfg = ConfigManager()
cfg["output"]   # → "my-bucket/runs/model.pt"
```

### 4 — Nested attribute access

When a config value is itself a dict, attribute access returns a namespace object that supports the same interface — including further attribute access, `__dir__`, `len()`, and iteration.

```json
{
    "train": {
        "db": { "host": "localhost", "port": 5432 }
    }
}
```

```python
cfg = ConfigManager()
cfg.db.host          # → "localhost"
cfg.db.port          # → 5432
cfg.db == {"host": "localhost", "port": 5432}   # → True
cfg.db.to_dict()     # → {"host": "localhost", "port": 5432}
```

### 5 — Environment variable interpolation

Use `${VAR}` in any string value. Variables from the `.env` file are available too.

```json
{
    "app": {
        "db_url": "postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}/mydb"
    }
}
```

```
# config/.env
DB_HOST=localhost
DB_USER=admin
DB_PASS=secret
```

```python
cfg = ConfigManager()
cfg["db_url"]   # → "postgresql://admin:secret@localhost/mydb"
```

### 6 — Logger injection

Pass your own logger to capture config loading events at `DEBUG` level.

```python
import logging
from refconf_manager import ConfigManager

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)

cfg = ConfigManager(logger=log)
# DEBUG config_manager: Config file: /project/config.json
# DEBUG config_manager: Active section: 'train' | globals: ['root', 'version'] | ...
```

### 7 — Override section or root

```python
# Load a specific section explicitly
cfg = ConfigManager(section="shared")

# Start searching from a different directory
cfg = ConfigManager(start_dir="/path/to/project")
```

## Error messages

When a reference can't be resolved, you get a clear, actionable message:

```
KeyError: "Reference {{preprocess.no_such_key}}: Key 'no_such_key' not found
under 'preprocess'. Available: ['output', 'batch_size']"
```

```
KeyError: "Reference {{version}}: no section prefix given and 'version' not
found in '_globals'. Use {{section.version}} or add it to '_globals'."
```

## Config file location

Config files must live inside a `config/` directory.  
The `.env` file also goes in the same `config/` directory.

```
project/
├── config/
│   ├── config.json   ← or config.yaml / config.toml
│   └── .env
└── scripts/
    └── train.py
```

`ConfigManager()` walks up from the calling script until it finds `config/config.json` (or yaml/toml).

## Config file formats

| File | Notes |
|------|-------|
| `config/config.json` | No extra dependencies |
| `config/config.yaml` / `config.yml` | Requires `pip install pyyaml` |
| `config/config.toml` | Built-in on Python 3.11+; `pip install tomli` on older |

## Reference syntax

Use `{{section.key}}` or `{{section.key.subkey.deeper}}` in any string value:

```json
{
    "_globals": {"root": "data/"},
    "shared":   {"db": {"host": "localhost", "port": 5432}},
    "app":      {
        "db_url":   "postgresql://{{shared.db.host}}:{{shared.db.port}}/mydb",
        "data_dir": "{{root}}processed/"
    }
}
```

References work inside nested dicts and lists too.  
Bare `{{key}}` (no dot) is resolved from `_globals`.

## Environment variable syntax

Use `${VAR}` to interpolate `os.environ` values in any string. Substitution happens after `{{}}` reference resolution, so both syntaxes can coexist:

```json
{
    "app": {
        "host":   "${DB_HOST}",
        "db_url": "postgresql://${DB_USER}@${DB_HOST}/{{_globals.db_name}}"
    }
}
```

Variables set in `config/.env` are loaded before interpolation, so they are available as `${VAR}` too. A missing variable raises `KeyError` with a clear message.

## API

### `ConfigManager(section=None, *, start_dir=None, logger=None)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `section` | `str` | auto-detected | Config section to load |
| `start_dir` | `str \| Path` | caller's directory | Where to start searching |
| `logger` | `logging.Logger` | `None` | Logger for internal debug events |

### Properties

| Property | Returns | Description |
|----------|---------|-------------|
| `section` | `str` | Active section name |
| `config_path` | `Path` | Resolved path to the config file |

### Dict-like and attribute-style access

```python
cfg["key"]                     # dict-style access (KeyError if missing)
cfg.key                        # attribute-style shorthand (AttributeError if missing)
cfg.get("key", default=None)   # with default
"key" in cfg                   # membership test
len(cfg)                       # number of keys in the active section
for k in cfg: ...              # iterate over keys
cfg.keys() / .values() / .items()
cfg.to_dict()                  # plain dict (recursively unwraps nested namespaces)
```

Attribute-style access also enables **IDE tab-completion**: type `cfg.` and your editor
will suggest the keys loaded from the active section (Pylance, Jedi, IPython, Jupyter).
Nested dict values return a `_Namespace` object that supports the same interface,
so `cfg.db.host` and `dir(cfg.db)` both work.

> **Note:** if a config key shares a name with a built-in method (e.g. `get`, `keys`),
> the method wins on attribute access. Use `cfg["get"]` in that case.

> **Note:** `ConfigManager` is read-only — assigning to any public attribute raises
> `AttributeError`.

## Development

```bash
git clone https://github.com/lukaszplk/config-manager
cd config-manager
pip install -e ".[dev]"
pytest
```

> The PyPI package is `refconf-manager`; the import name is `refconf_manager`.
