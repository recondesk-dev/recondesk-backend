import re

with open("app/routers/reconciliation_api.py", "r") as f:
    code = f.read()

new_code = code.replace(
    'mismatched_count = sum(1 for m in matched_engine if m.get("match_level") == "Mismatch")',
    'mismatched_count = sum(1 for m in matched_engine if isinstance(m.get("match_level"), int) and m.get("match_level") >= 3)'
)

with open("app/routers/reconciliation_api.py", "w") as f:
    f.write(new_code)
