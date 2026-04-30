# N.O.R.M. beta2-pre2

**Neural Overseer for Routine Management**

This is the second beta2 foundation package. It keeps the modular pre1 skeleton and adds the first dark/amber web cockpit shell plus plugin-aware web routes.

This package is meant to live in `~/norm` if that is your preferred beta2 working directory. It does **not** require touching the original alpha install unless you intentionally use the same folder.

## What pre2 adds

- `config_version: 2` safety checks remain in place
- Core `AppContext`
- `EventBus`
- `ServiceManager`
- `PluginManagerService`
- New `WebUIService`
- FastAPI dashboard shell
- `/plugins` page
- `/config` read-only config page
- `/events` event bus viewer
- `/logs` basic log file listing
- `/api/core/health`
- `/api/core/config`
- `/api/core/events`
- `/api/plugins`
- `/api/plugins/<plugin_id>/health`
- `/api/plugins/<plugin_id>/status`
- Configurable plugin landing route support
- Demo plugin mounted at `/hello`
- Reserved route protection
- Dark amber CSS shell

## Install / update in `~/norm`

From your Pi:

```bash
cd ~/norm
unzip -o /path/to/norm-beta2-pre2-overlay.zip
./scripts/install_deps.sh
source .venv/bin/activate
```

## Smoke test without web

```bash
./scripts/run_once.sh
```

This starts core services and plugins, skips the web server, prints a startup report, then exits.

## Smoke test with web service

```bash
./scripts/run_once_web.sh
```

This confirms FastAPI/Uvicorn can initialize, then exits.

## Run the web UI

```bash
./scripts/run_web.sh
```

Then open:

```text
http://<pi-ip>:8090
```

Useful pages:

```text
/
/plugins
/config
/events
/logs
/hello
/api/core/health
/api/plugins
/api/plugins/hello_norm/status
```

## Change the web port

Temporary override:

```bash
./scripts/run_web.sh --port 8091
```

Permanent setting:

```yaml
# config/norm.yaml
webui:
  enabled: true
  host: "0.0.0.0"
  port: 8090
```

## Plugin route example

`plugins/hello_norm/plugin.yaml`:

```yaml
webui:
  enabled: true
  route: "/hello"
  label: "Hello"
```

Plugin API routes are automatically namespaced under:

```text
/api/plugins/<plugin_id>/...
```

Plugin UI routes cannot override reserved core paths like `/`, `/config`, `/plugins`, `/api/core/*`, or `/api/plugins/*`.

## Next milestone

beta2-pre3 should begin the Face Core transplant:

- `FaceService`
- face state events
- current procedural renderer wrapped as `norm_default`
- basic face pack loader
- basic face preview API
- face selector shell in the web UI

