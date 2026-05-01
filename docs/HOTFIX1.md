# N.O.R.M. beta2-pre2 hotfix1

Fixes `/hello` and other plugin landing routes on FastAPI/Pydantic/Python 3.13.

The bug was caused by binding the plugin record as a default argument in the route handler. FastAPI treated that default as a query parameter and Pydantic attempted to deepcopy the PluginRecord/AppContext object graph, causing a recursion error.

Install from `~/norm`:

```bash
unzip -o /path/to/norm-beta2-pre2-hotfix1-overlay.zip
./scripts/run_web.sh
```

Then test:

- `/hello`
- `/api/plugins/hello_norm/status`
- `/plugins`
