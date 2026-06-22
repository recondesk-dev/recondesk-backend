import sys
from tests.test_duplicate_lifecycle import _run, _p
import app.services.reconciliation as rec

original_resolve_orphans = rec.resolve_orphans

def debug_resolve_orphans(matched, missed_itc, wrongful_itc_risk, gstr_by_id, pr_by_id, **kwargs):
    print("IN:", wrongful_itc_risk, gstr_by_id.keys(), pr_by_id.keys())
    res = original_resolve_orphans(matched, missed_itc, wrongful_itc_risk, gstr_by_id, pr_by_id, **kwargs)
    print("OUT:", res[2])
    return res

rec.resolve_orphans = debug_resolve_orphans
_run([], [_p("p1", inv="UNIQUE-PR-001")])
