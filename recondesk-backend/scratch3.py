from datetime import date
from tests.test_duplicate_lifecycle import _run, _p
import inspect
from app.services import reconciliation
lines, _ = inspect.getsourcelines(reconciliation.run_bidirectional_reconciliation)
print("".join(lines[60:85]))
