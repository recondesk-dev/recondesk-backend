from datetime import date
from tests.test_duplicate_lifecycle import _run, _p
res = _run([], [_p("p1", inv="UNIQUE-PR-001")])
print("wrongful_risk_count:", res["stats"]["wrongful_risk_count"])
print("wrongful_itc_risk:", res["wrongful_itc_risk"])
