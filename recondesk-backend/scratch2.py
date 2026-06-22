from datetime import date
from tests.test_duplicate_lifecycle import _run, _p
from app.services.reconciliation import build_wrongful_itc_risk, resolve_orphans

pr = [_p("p1", inv="UNIQUE-PR-001")]
pr_by_id = {"p1": pr[0]}
matched = []
missed_itc = []
wrongful_itc_risk = pr

res = resolve_orphans(matched, missed_itc, wrongful_itc_risk, {}, pr_by_id)
print("wrongful_final from resolve_orphans:", res[2])
