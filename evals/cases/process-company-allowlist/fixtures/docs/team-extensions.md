# Team extensions - ACME

## Standing instructions

- The registered scanner is pre-approved company tooling (CST_COMPANY_ALLOW covers it).

## Analyser registry

```json
{"analysers": [
  {"name": "acmescan", "command": "python3 tools/acmescan.py {target}",
   "probe": "python3", "lenses": ["security"], "replaces": ["bandit"], "output": "sarif"}
]}
```
