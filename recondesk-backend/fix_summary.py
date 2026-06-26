import re

with open("app/services/reconciliation_payload_store.py", "r") as f:
    content = f.read()

sig_replacement = """def build_run_summary_metrics(
    *,
    n_gstr: int,
    n_pr: int,
    matched_count: int,
    missed_itc_count: int,
    wrongful_count: int,
    itc_missed: int,
    wrongful_paise: int,
    rule37_itc_paise: int,
    itc_at_risk_total: int,
    late_itc_paise: int,
    late_match_count: int,
    rule37_pending_verification_count: int = 0,
    rule37_pending_verification_paise: int = 0,
    skipped_count: int = 0,
    review_required_count: int = 0,
) -> dict[str, Any]:
    \"\"\"Scalar run_summary only — no decisions/compliance blobs (kept in results payload).\"\"\"
    return {
        "total_records": n_gstr + n_pr,
        "matched_count": matched_count + review_required_count, # total linked
        "clean_matched_count": matched_count,
        "review_required_count": review_required_count,
        "total_linked_count": matched_count + review_required_count,
        "unmatched_count": missed_itc_count + wrongful_count,
        "itc_at_risk": itc_at_risk_total,
        "missed_itc_paise": itc_missed,
        "rule37_itc_paise": rule37_itc_paise,
        "wrongful_itc": wrongful_paise,
        "late_itc": late_itc_paise,
        "late_match_count": late_match_count,
        "gstr_in_scope": n_gstr,
        "pr_in_scope": n_pr,
        "rule37_pending_verification_count": rule37_pending_verification_count,
        "rule37_pending_verification_paise": rule37_pending_verification_paise,
        "skipped_count": skipped_count,
    }"""

content = re.sub(
    r"def build_run_summary_metrics\(.*?skipped_count:\s*int\s*=\s*0,\n\) -> dict\[str, Any\]:\n    .*?return \{.*?\n    \}",
    sig_replacement,
    content,
    flags=re.DOTALL
)

with open("app/services/reconciliation_payload_store.py", "w") as f:
    f.write(content)


with open("app/worker/reconciliation_task.py", "r") as f:
    worker_content = f.read()

worker_replacement = """        run_summary = build_run_summary_metrics(
            n_gstr=n_gstr,
            n_pr=n_pr,
            matched_count=matched_count,
            missed_itc_count=missed_itc_count,
            wrongful_count=wrongful_count,
            itc_missed=itc_missed,
            wrongful_paise=wrongful_paise,
            rule37_itc_paise=rule37_paise,
            itc_at_risk_total=wrongful_paise + rule37_paise,
            late_itc_paise=late_itc_paise,
            late_match_count=late_itc,
            rule37_pending_verification_count=rule37_pending_count,
            rule37_pending_verification_paise=rule37_pending_paise,
            skipped_count=skipped_count,
            review_required_count=review_gstr_count,
        )"""

worker_content = re.sub(
    r"        run_summary = build_run_summary_metrics\(.*?skipped_count=skipped_count,\n        \)",
    worker_replacement,
    worker_content,
    flags=re.DOTALL
)

with open("app/worker/reconciliation_task.py", "w") as f:
    f.write(worker_content)

