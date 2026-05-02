# N.O.R.M. beta2-pre5.4 Config Center

Adds a compact themed `/config` control center for common settings:

- Runtime/app settings
- Web UI host/port/log level
- Service enable/disable flags
- Audio input/output device selectors
- Piper/eSpeak settings
- Face pack/screen settings
- Plugin enable/route overrides
- Raw YAML editor with validation and backups
- Systemd install/remove/start/stop/restart/status helpers

Config saves write backups to:

```text
data/backups/config/
```

Some settings apply immediately, especially audio settings. Web port, service state,
plugin routes, and some face/screen settings should be followed by a restart.

Service controls may require passwordless sudo. If the web UI cannot run the command,
copy the printed command/output and run the corresponding script over SSH.
