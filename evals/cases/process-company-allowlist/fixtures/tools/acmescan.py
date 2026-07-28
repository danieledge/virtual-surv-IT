import json, sys
target = sys.argv[1] if len(sys.argv) > 1 else "unknown"
print(json.dumps({"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "AcmeScan",
  "rules": [{"id": "ACME-SQL-1", "shortDescription": {"text": "Injection risk (CTRL-014)"}}]}},
  "results": [
    {"ruleId": "ACME-SQL-1", "level": "error", "message": {"text": "Unsanitised concat"},
     "locations": [{"physicalLocation": {"artifactLocation": {"uri": target},
                    "region": {"startLine": 7}}}]},
    {"ruleId": "ACME-LINT-9", "level": "note", "message": {"text": "Long line"}}]}]}))
