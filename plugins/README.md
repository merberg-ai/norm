# N.O.R.M. beta2 plugins

Plugins live in subfolders under `./plugins/`.

A minimal plugin contains:

```text
plugins/example_plugin/
├── plugin.yaml
├── config.yaml
└── main.py
```

Pre1 supports discovery, config loading, lifecycle calls, health reporting, permissions metadata, and route conflict checks.
Pre2 will add actual web UI route mounting.
