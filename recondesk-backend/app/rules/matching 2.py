"""MAT_ rules — L1–L5 matching and reconciliation logic."""

from app.rules.base import REGISTRY, RuleCategory, RuleDefinition, RuleSeverity

REGISTRY.register(RuleDefinition(
    id="MAT_001",
    name="L1 Exact Match",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.LOW,
    description="Match purchase register rows to GSTR-2B when GSTIN, invoice number, and invoice date are identical.",
    gst_ref="GSTR-2B reconciliation",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "l1", "exact"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_002",
    name="GSTIN Uppercase Normalisation",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.LOW,
    description="Normalise GSTIN to uppercase before comparison to avoid false mismatches from case differences.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "gstin", "normalisation"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_003",
    name="L2 Amount Tolerance",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.MEDIUM,
    description="Accept L2 matches when taxable value differs by up to ₹100 between purchase register and GSTR-2B.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "l2", "amount", "tolerance"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_004",
    name="Paise Conversion Guard",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.HIGH,
    description="Convert rupee amounts to paise before comparison to prevent floating-point rounding mismatches.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "amount", "paise"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_005",
    name="L3 Period-Shifted Match",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.MEDIUM,
    description="Match invoices filed in an adjacent GSTR-2B period when supplier filed late but invoice details otherwise align.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "l3", "period"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_006",
    name="L3 Late Filing Flag",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.MEDIUM,
    description="Flag L3 matches where supplier GSTR-1 filing date exceeds invoice date by more than 7 days.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "l3", "late-filing"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_007",
    name="L4 Fuzzy Invoice Match",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.MEDIUM,
    description="Match rows using fuzzy invoice number comparison when exact match fails but GSTIN and amount align.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "l4", "fuzzy"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_008",
    name="L4 Similarity Floor",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.MEDIUM,
    description="Require minimum invoice number similarity score of 0.40 before accepting an L4 fuzzy match.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "l4", "similarity"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_009",
    name="L5 Probable Match",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.HIGH,
    description="Surface probable matches when only GSTIN and approximate amount align without confident invoice linkage.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "l5", "probable"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_010",
    name="L5 Vendor Intelligence Boost",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.MEDIUM,
    description="Increase L5 match confidence when vendor intelligence history shows consistent filing patterns.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "l5", "vendor-intelligence"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_011",
    name="Missed ITC",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.HIGH,
    description="Identify invoices present in purchase register but absent from GSTR-2B, indicating potential missed ITC.",
    gst_ref="Section 16(2)(aa) CGST Act",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "itc", "missed"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_012",
    name="Wrongful ITC",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.CRITICAL,
    description="Identify GSTR-2B entries with no corresponding purchase register invoice, indicating potential wrongful ITC claim.",
    gst_ref="Section 16 CGST Act",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "itc", "wrongful"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_013",
    name="Cross-Run Carry-Forward",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.MEDIUM,
    description="Carry unmatched purchase register rows from prior reconciliation runs into the current period for re-matching.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "carry-forward"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_014",
    name="Amendment Invoice Linkage",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.MEDIUM,
    description="Link amended GSTR-2B invoices to their original purchase register entries using amendment reference numbers.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "amendment"],
))

REGISTRY.register(RuleDefinition(
    id="MAT_015",
    name="Credit Note Offset Matching",
    category=RuleCategory.MATCHING,
    severity=RuleSeverity.MEDIUM,
    description="Offset credit note entries against original invoices during matching to avoid duplicate ITC claims.",
    gst_ref="Section 34 CGST Act",
    applies_to=["purchase_register", "gstr2b"],
    tags=["matching", "credit-note"],
))
