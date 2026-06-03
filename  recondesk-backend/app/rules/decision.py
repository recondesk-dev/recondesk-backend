"""DEC_ rules — decision templates for reconciliation outcomes."""

from app.rules.base import REGISTRY, RuleCategory, RuleDefinition, RuleSeverity

REGISTRY.register(RuleDefinition(
    id="DEC_001",
    name="L1 Exact Match Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.LOW,
    description="Decision template for L1 exact matches with full GSTIN, invoice number, and date alignment.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["decision", "l1", "exact"],
))

REGISTRY.register(RuleDefinition(
    id="DEC_002",
    name="L2 Amount Diff Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.MEDIUM,
    description="Decision template for L2 matches where invoice details align but taxable value differs within tolerance.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["decision", "l2", "amount"],
))

REGISTRY.register(RuleDefinition(
    id="DEC_003",
    name="L3 Amount Diff Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.MEDIUM,
    description="Decision template for L3 period-shifted matches with amount or filing date discrepancies.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["decision", "l3", "amount", "period"],
))

REGISTRY.register(RuleDefinition(
    id="DEC_004",
    name="L4 Invoice Number Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.MEDIUM,
    description="Decision template for L4 fuzzy invoice number matches requiring manual review.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["decision", "l4", "invoice"],
))

REGISTRY.register(RuleDefinition(
    id="DEC_005",
    name="L5 Probable Match Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.HIGH,
    description="Decision template for L5 probable matches with low confidence requiring user confirmation.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["decision", "l5", "probable"],
))

REGISTRY.register(RuleDefinition(
    id="DEC_006",
    name="Missed ITC Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.HIGH,
    description="Decision template for invoices in purchase register absent from GSTR-2B.",
    gst_ref="Section 16(2)(aa) CGST Act",
    applies_to=["purchase_register", "gstr2b"],
    tags=["decision", "itc", "missed"],
))

REGISTRY.register(RuleDefinition(
    id="DEC_007",
    name="Wrongful ITC Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.CRITICAL,
    description="Decision template for GSTR-2B entries with no purchase register counterpart.",
    gst_ref="Section 16 CGST Act",
    applies_to=["purchase_register", "gstr2b"],
    tags=["decision", "itc", "wrongful"],
))

REGISTRY.register(RuleDefinition(
    id="DEC_008",
    name="Rule 37 Overdue Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.CRITICAL,
    description="Decision template for invoices exceeding 180-day payment deadline requiring ITC reversal.",
    gst_ref="Rule 37 CGST Rules",
    applies_to=["purchase_register"],
    tags=["decision", "rule-37", "reversal"],
))

REGISTRY.register(RuleDefinition(
    id="DEC_009",
    name="Rule 37 Warning Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.HIGH,
    description="Decision template for invoices approaching the 180-day Rule 37 payment deadline.",
    gst_ref="Rule 37 CGST Rules",
    applies_to=["purchase_register"],
    tags=["decision", "rule-37", "warning"],
))

REGISTRY.register(RuleDefinition(
    id="DEC_010",
    name="Blocked Credit Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.CRITICAL,
    description="Decision template for Section 17(5) blocked credit items that cannot be claimed as ITC.",
    gst_ref="Section 17(5) CGST Act",
    applies_to=["purchase_register"],
    tags=["decision", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="DEC_011",
    name="Late Filing Template",
    category=RuleCategory.DECISION,
    severity=RuleSeverity.MEDIUM,
    description="Decision template for matches where supplier GSTR-1 was filed more than 7 days after invoice date.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["decision", "late-filing"],
))
