from app.services.reconciliation import resolve_orphans
import app.services.reconciliation as rec

GSTIN_OTHER = "29ABCDE1234F1Z5"
wrongful = [{
    "id": "p1",
    "supplier_gstin": GSTIN_OTHER,
    "invoice_number_normalized": "R37OLD001",
    "invoice_date": "2025-10-01",
    "taxable_amount_paise": 9_000_000,
    "total_tax_paise": 1_620_000,
}]

def resolve_debug(matched, missed_itc, wrongful_itc_risk, gstr_by_id, pr_by_id, amount_tolerance_paise=10000):
    groups = rec.defaultdict(lambda: {"gstr": [], "pr": []})
    for w in wrongful_itc_risk:
        groups[rec._identity_key(w.get("supplier_gstin"), w.get("invoice_number_normalized"))]["pr"].append(w)
    
    conflicted_pr_ids = set()
    print("conflicted_pr_ids:", conflicted_pr_ids)

    wrongful_after_conflict = [w for w in wrongful_itc_risk if str(w.get("id")) not in conflicted_pr_ids]
    print("wrongful_after_conflict:", wrongful_after_conflict)

    consumed_wrongful = set()
    wrongful_final = [
        w for w in wrongful_after_conflict if id(w) not in consumed_wrongful
    ]
    print("wrongful_final:", wrongful_final)

resolve_debug([], [], wrongful, {}, {"p1": wrongful[0]})
