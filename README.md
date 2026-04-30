# N.O.R.M. beta2-pre1

**Neural Overseer for Routine Management**  
Fresh modular skeleton for the separate N.O.R.M. beta2 install.

This is the first beta2 foundation package. It does **not** replace the current deployed N.O.R.M. install. Deploy it into a fresh directory such as:

```bash
~/norm-beta2/
```

The goal of pre1 is simple: prove the new core runtime can boot, load versioned configs, start services, discover plugins, and run a dummy plugin without dragging the whole app into the swamp.

## Included

```text
app.py
config/
  norm.yaml
  plugins.yaml
core/
  app_context.py
  config.py
  event_bus.py
  lifecycle.py
  logging.py
  paths.py
  plugin_manager.py
  safety.py
  service.py
  service_manager.py
plugins/
  hello_norm/
    plugin.yaml
    config.yaml
    main.py
scripts/
  install_deps.sh
  run_dev.sh
  run_once.sh
  run_safe_mode.sh
  clean_project.sh
tests/
  test_boot_once.py
```

## What works in pre1

- Config files include `config_version: 2`
- YAML config loading
- Startup logging to console and `data/logs/norm-beta2.log`
- `AppContext`
- `EventBus`
- `BaseService`
- `ServiceManager`
- `PluginManagerService`
- Plugin discovery from `./plugins/`
- Plugin manifest loading
- Plugin config loading and override merging
- Plugin lifecycle: `setup`, `start`, `stop`, `health`
- Plugin failure quarantine
- Basic web route reservation/conflict checks
- Safe mode plugin skip
- Startup health report

## What intentionally does not exist yet

- Web UI shell
- Plugin route mounting
- Face service
- Face packs
- Face designer
- TTS manager
- Piper
- Wake word
- Memory database
- Identity recognition
- Body/hardware control

That is deliberate. Skeleton first. Haunted robot organs later.

## Install on the Pi

```bash
cd ~
unzip norm-beta2-pre1.zip -d norm-beta2
cd norm-beta2
./scripts/install_deps.sh
```

Activate the venv:

```bash
source .venv/bin/activate
```

Run a one-shot boot test:

```bash
./scripts/run_once.sh
```

Expected output includes:

```text
Plugin discovered: hello_norm
Plugin started: hello_norm
=== N.O.R.M. beta2-pre1 startup report ===
```

Run normally:

```bash
./scripts/run_dev.sh
```

Stop with `Ctrl+C`.

## Safe mode

Safe mode boots the runtime but skips plugin startup:

```bash
./scripts/run_safe_mode.sh
```

Or:

```bash
python3 app.py --safe-mode --once
```

You can also set this in `config/norm.yaml`:

```yaml
app:
  safe_mode: true
```

## Config versioning

Every major config file starts with:

```yaml
config_version: 2
```

Pre1 refuses missing, old, or future config versions. That is intentional safety behavior so future config migrations do not silently mangle N.O.R.M.'s brainstem.

## Plugin override example

`config/plugins.yaml` can override a plugin without editing the plugin folder:

```yaml
config_version: 2

plugins:
  hello_norm:
    enabled: true
    config_overrides:
      greeting: "The plugin chamber is operational."
    webui:
      route: "/hello"
```

## Next planned milestone

`beta2-pre2`: Web UI shell + plugin-aware routes.

That should add:

- dark amber cockpit web shell
- `/plugins` page
- plugin status display
- configurable plugin web routes
- `/api/plugins/<plugin_id>/...` namespace
- reserved route protection in the actual web server
