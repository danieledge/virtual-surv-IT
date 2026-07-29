# Team extensions - ACME

## Standing instructions

- Cite CTRL-xxx control ids in findings.

## Close actions

- Offer to append a summary line to handover-queue.md.

## Analyser registry

```json
{"analysers": [
  {"name": "acmescan", "command": "python3 tools/acmescan.py {target}",
   "probe": "python3", "lenses": ["security"], "replaces": ["bandit"], "output": "sarif",
   "severity_map": {"error": "critical", "note": "style"}}
]}
```
