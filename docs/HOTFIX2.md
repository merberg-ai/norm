# N.O.R.M. beta2-pre2 hotfix2

Plugin landing routes such as `/hello` are now mounted with Starlette `app.add_route()` instead of FastAPI `app.add_api_route()`.

This bypasses FastAPI/Pydantic dependency inspection for dynamic plugin HTML pages. Core JSON/API routes still use FastAPI.

Install:

```bash
cd ~/norm
unzip -o /path/to/norm-beta2-pre2-hotfix2-overlay.zip
source .venv/bin/activate
./scripts/run_web.sh
```

Test:

```text
http://<pi-ip>:8090/hello
http://<pi-ip>:8090/plugins
http://<pi-ip>:8090/api/plugins/hello_norm/status
```
