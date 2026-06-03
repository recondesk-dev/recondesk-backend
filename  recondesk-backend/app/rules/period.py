"""PRD_, SUP_, RPT_, and TDS_ rules — period, supplier, reporting, and TDS/TCS."""

from app.rules.base import REGISTRY, RuleCategory, RuleDefinition, RuleSeverity

# ── Period rules (PRD_) ───────────────────────────────────────────────────────

REGISTRY.register(RuleDefinition(
    id="PRD_001",
    name="ITC Claim Deadline Nov 30",
    category=RuleCategory.PERIOD,
    severity=RuleSeverity.CRITICAL,
    description="Enforce 30 November deadline for claiming ITC pertaining to a financial year.",
    gst_ref="Section 16(4) CGST Act",
    applies_to=["purchase_register"],
    tags=["period", "deadline", "itc"],
))

REGISTRY.register(RuleDefinition(
    id="PRD_002",
    name="Amendment Window Detection",
    category=RuleCategory.PERIOD,
    severity=RuleSeverity.MEDIUM,
    description="Detect whether an invoice falls within the GSTR-1 amendment filing window.",
    gst_ref="Rule 67 CGST Rules",
    applies_to=["purchase_register", "gstr2b"],
    tags=["period", "amendment"],
))

REGISTRY.register(RuleDefinition(
    id="PRD_003",
    name="Late Filing Threshold",
    category=RuleCategory.PERIOD,
    severity=RuleSeverity.MEDIUM,
    description="Flag supplier GSTR-1 filings received more than 7 days after the invoice date.",
    applies_to=["gstr2b"],
    tags=["period", "late-filing"],
))

REGISTRY.register(RuleDefinition(
    id="PRD_004",
    name="FY Boundary Detection",
    category=RuleCategory.PERIOD,
    severity=RuleSeverity.MEDIUM,
    description="Detect invoices spanning financial year boundaries for correct ITC period assignment.",
    applies_to=["purchase_register"],
    tags=["period", "fy", "boundary"],
))

REGISTRY.register(RuleDefinition(
    id="PRD_005",
    name="Rule 37 Clock Start",
    category=RuleCategory.PERIOD,
    severity=RuleSeverity.HIGH,
    description="Start the 180-day Rule 37 payment clock from invoice date for overdue payment tracking.",
    gst_ref="Rule 37 CGST Rules",
    applies_to=["purchase_register"],
    tags=["period", "rule-37"],
))

REGISTRY.register(RuleDefinition(
    id="PRD_006",
    name="IMS Acceptance Window",
    category=RuleCategory.PERIOD,
    severity=RuleSeverity.HIGH,
    description="Track Invoice Management System acceptance window for pending ITC actions.",
    gst_ref="IMS CGST Rules",
    applies_to=["gstr2b"],
    tags=["period", "ims"],
))

REGISTRY.register(RuleDefinition(
    id="PRD_007",
    name="QRMP Quarterly Filer Expansion",
    category=RuleCategory.PERIOD,
    severity=RuleSeverity.MEDIUM,
    description="Expand GSTR-2B matching window for QRMP quarterly filers to cover their filing quarter.",
    applies_to=["gstr2b"],
    tags=["period", "qrmp", "quarterly"],
))

# ── Supplier rules (SUP_) ─────────────────────────────────────────────────────

REGISTRY.register(RuleDefinition(
    id="SUP_001",
    name="Composition Dealer No ITC",
    category=RuleCategory.SUPPLIER,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on purchases from composition scheme dealers.",
    gst_ref="Section 10 CGST Act",
    applies_to=["purchase_register"],
    tags=["supplier", "composition", "blocked"],
))

REGISTRY.register(RuleDefinition(
    id="SUP_002",
    name="RCM Self-Invoice Required",
    category=RuleCategory.SUPPLIER,
    severity=RuleSeverity.HIGH,
    description="Require self-invoice generation for reverse charge supplies from unregistered suppliers.",
    gst_ref="Section 9(3) CGST Act",
    applies_to=["purchase_register"],
    tags=["supplier", "rcm", "self-invoice"],
))

REGISTRY.register(RuleDefinition(
    id="SUP_003",
    name="SEZ Zero-Rated Check",
    category=RuleCategory.SUPPLIER,
    severity=RuleSeverity.HIGH,
    description="Verify SEZ supplier zero-rated supply treatment and applicable ITC restrictions.",
    gst_ref="Section 16 IGST Act",
    applies_to=["purchase_register"],
    tags=["supplier", "sez", "zero-rated"],
))

REGISTRY.register(RuleDefinition(
    id="SUP_004",
    name="Exempt Supply Proportionate Reversal",
    category=RuleCategory.SUPPLIER,
    severity=RuleSeverity.HIGH,
    description="Calculate proportionate ITC reversal for inputs used in exempt supplies.",
    gst_ref="Rule 42 CGST Rules",
    applies_to=["purchase_register"],
    tags=["supplier", "exempt", "reversal"],
))

REGISTRY.register(RuleDefinition(
    id="SUP_005",
    name="Vendor Intelligence Risk Score",
    category=RuleCategory.SUPPLIER,
    severity=RuleSeverity.MEDIUM,
    description="Assign supplier risk score based on filing history, mismatch rate, and Rule 37 exposure.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["supplier", "vendor-intelligence", "risk"],
))

REGISTRY.register(RuleDefinition(
    id="SUP_006",
    name="Import Bill of Entry",
    category=RuleCategory.SUPPLIER,
    severity=RuleSeverity.HIGH,
    description="Validate import ITC claims against bill of entry details for IGST paid at customs.",
    gst_ref="Section 5 IGST Act",
    applies_to=["purchase_register"],
    tags=["supplier", "import", "boe"],
))

REGISTRY.register(RuleDefinition(
    id="SUP_007",
    name="URP ₹5000 Limit",
    category=RuleCategory.SUPPLIER,
    severity=RuleSeverity.MEDIUM,
    description="Enforce ₹5,000 daily aggregate limit for purchases from unregistered persons.",
    gst_ref="Notification 10/2017-CT",
    applies_to=["purchase_register"],
    tags=["supplier", "urp", "limit"],
))

# ── Reporting rules (RPT_) ────────────────────────────────────────────────────

REGISTRY.register(RuleDefinition(
    id="RPT_001",
    name="DRC-01C Trigger",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.CRITICAL,
    description="Flag reconciliation outcomes that may trigger a DRC-01C show-cause notice response.",
    gst_ref="Section 73 CGST Act",
    applies_to=["purchase_register", "gstr2b"],
    tags=["reporting", "drc-01c", "compliance"],
))

REGISTRY.register(RuleDefinition(
    id="RPT_002",
    name="GSTR-3B vs 2B Comparison",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.HIGH,
    description="Compare ITC claimed in GSTR-3B against GSTR-2B auto-populated values.",
    applies_to=["gstr2b", "gstr3b"],
    tags=["reporting", "gstr3b", "comparison"],
))

REGISTRY.register(RuleDefinition(
    id="RPT_003",
    name="IMS+2B vs PR Reconciliation",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.HIGH,
    description="Reconcile IMS actions, GSTR-2B entries, and purchase register in a unified view.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["reporting", "ims", "reconciliation"],
))

REGISTRY.register(RuleDefinition(
    id="RPT_004",
    name="Finalization Audit Trail",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.MEDIUM,
    description="Record audit trail when a reconciliation run is finalised including user and timestamp.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["reporting", "audit", "finalization"],
))

REGISTRY.register(RuleDefinition(
    id="RPT_005",
    name="Section 17(5) Aggregate Flag",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.HIGH,
    description="Aggregate and flag all Section 17(5) blocked credit items in the reconciliation report.",
    gst_ref="Section 17(5) CGST Act",
    applies_to=["purchase_register"],
    tags=["reporting", "section-17-5", "blocked"],
))

REGISTRY.register(RuleDefinition(
    id="RPT_006",
    name="Vendor Email Trigger",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.LOW,
    description="Trigger vendor follow-up email for unmatched or disputed invoices above a configurable threshold.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["reporting", "email", "vendor"],
))

REGISTRY.register(RuleDefinition(
    id="RPT_007",
    name="Excel 6-Sheet Export",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.LOW,
    description="Export reconciliation results as a 6-sheet Excel workbook covering all match categories.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["reporting", "export", "excel"],
))

REGISTRY.register(RuleDefinition(
    id="RPT_008",
    name="PDF CA Watermark",
    category=RuleCategory.REPORTING,
    severity=RuleSeverity.LOW,
    description="Apply CA firm watermark and signatory details to PDF reconciliation reports.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["reporting", "export", "pdf"],
))

# ── TDS/TCS rules (TDS_) ──────────────────────────────────────────────────────

REGISTRY.register(RuleDefinition(
    id="TDS_001",
    name="Section 51 TDS Deductor",
    category=RuleCategory.TDS_TCS,
    severity=RuleSeverity.HIGH,
    description="Identify TDS obligations under Section 51 for specified goods and services.",
    gst_ref="Section 51 CGST Act",
    applies_to=["purchase_register"],
    tags=["tds", "section-51", "deductor"],
))

REGISTRY.register(RuleDefinition(
    id="TDS_002",
    name="Section 52 TCS E-Commerce",
    category=RuleCategory.TDS_TCS,
    severity=RuleSeverity.HIGH,
    description="Identify TCS obligations under Section 52 for e-commerce operators.",
    gst_ref="Section 52 CGST Act",
    applies_to=["purchase_register"],
    tags=["tcs", "section-52", "ecommerce"],
))

REGISTRY.register(RuleDefinition(
    id="TDS_003",
    name="GSTR-7 vs PR Cross-Check",
    category=RuleCategory.TDS_TCS,
    severity=RuleSeverity.HIGH,
    description="Cross-check TDS deducted per GSTR-7 against purchase register entries.",
    applies_to=["purchase_register", "gstr7"],
    tags=["tds", "gstr7", "cross-check"],
))

REGISTRY.register(RuleDefinition(
    id="TDS_004",
    name="TDS Credit in Cash Ledger",
    category=RuleCategory.TDS_TCS,
    severity=RuleSeverity.MEDIUM,
    description="Verify TDS credit reflected in electronic cash ledger matches deducted amounts.",
    gst_ref="Section 51 CGST Act",
    applies_to=["purchase_register", "gstr7"],
    tags=["tds", "cash-ledger", "credit"],
))
