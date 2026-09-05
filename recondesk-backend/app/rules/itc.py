"""ITC_ rules — Section 17(5), Rule 37, Section 16 eligibility."""

from app.rules.base import REGISTRY, RuleCategory, RuleDefinition, RuleSeverity

# Section 17(5) blocked credit categories
REGISTRY.register(RuleDefinition(
    id="ITC_001",
    name="Section 17(5)(a) Motor Vehicles",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on motor vehicles except when used for specified taxable supplies.",
    gst_ref="Section 17(5)(a) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_002",
    name="Section 17(5)(aa) Vessels and Aircraft",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on vessels and aircraft except when used for specified taxable supplies.",
    gst_ref="Section 17(5)(aa) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_003",
    name="Section 17(5)(ab) General Insurance",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on general insurance, servicing, repair and maintenance of motor vehicles, vessels, and aircraft.",
    gst_ref="Section 17(5)(ab) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_004",
    name="Section 17(5)(b)(i) Food and Beverages",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on food and beverages except when supplied outwardly or as part of taxable composite supply.",
    gst_ref="Section 17(5)(b)(i) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_005",
    name="Section 17(5)(b)(ii) Outdoor Catering",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on outdoor catering except when supplied outwardly or as part of taxable composite supply.",
    gst_ref="Section 17(5)(b)(ii) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_006",
    name="Section 17(5)(b)(iii) Beauty Treatment",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on beauty treatment except when supplied outwardly or as part of taxable composite supply.",
    gst_ref="Section 17(5)(b)(iii) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_007",
    name="Section 17(5)(b)(iv) Health Services",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on health services except when supplied outwardly or as part of taxable composite supply.",
    gst_ref="Section 17(5)(b)(iv) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_008",
    name="Section 17(5)(b)(ii) Club Membership",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on membership of clubs, health and fitness centres.",
    gst_ref="Section 17(5)(b)(ii) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_009",
    name="Section 17(5)(b)(i) Rent-a-Cab",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on rent-a-cab, life insurance and health insurance except when outward supply obligation exists.",
    gst_ref="Section 17(5)(b)(i) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_010",
    name="Section 17(5)(b)(iii) Travel Benefits",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on travel benefits extended to employees on vacation such as leave or home travel concession.",
    gst_ref="Section 17(5)(b)(iii) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_011",
    name="Section 17(5)(c) Works Contract",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on works contract services for construction of immovable property except plant and machinery.",
    gst_ref="Section 17(5)(c) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_012",
    name="Section 17(5)(g) Personal Consumption",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Block ITC on goods or services used for personal consumption or gifts exceeding ₹50,000.",
    gst_ref="Section 17(5)(g) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "blocked", "section-17-5"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_013",
    name="Rule 37 Overdue",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Reverse ITC when payment to supplier exceeds 180 days from invoice date as per Rule 37.",
    gst_ref="Rule 37 CGST Rules",
    applies_to=["purchase_register"],
    tags=["itc", "reversal", "rule-37"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_014",
    name="Rule 37 Warning",
    category=RuleCategory.ITC,
    severity=RuleSeverity.HIGH,
    description="Warn when payment to supplier is overdue between 130 and 180 days, approaching Rule 37 reversal threshold.",
    gst_ref="Rule 37 CGST Rules",
    applies_to=["purchase_register"],
    tags=["itc", "warning", "rule-37"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_015",
    name="Rule 37 SHA1 Stable ID",
    category=RuleCategory.ITC,
    severity=RuleSeverity.MEDIUM,
    description="Generate stable SHA1 identifier for Rule 37 tracking across reconciliation runs using invoice key fields.",
    gst_ref="Rule 37 CGST Rules",
    applies_to=["purchase_register"],
    tags=["itc", "rule-37", "identifier"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_016",
    name="Rule 37A Supplier Non-Filing",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Flag ITC risk when supplier has not filed GSTR-1/GSTR-3B for the invoice period as per Rule 37A.",
    gst_ref="Rule 37A CGST Rules",
    applies_to=["purchase_register", "gstr2b"],
    tags=["itc", "rule-37a", "supplier"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_017",
    name="Section 16(2)(aa) 2B Reflection",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Require invoice to appear in GSTR-2B before ITC can be claimed as per Section 16(2)(aa).",
    gst_ref="Section 16(2)(aa) CGST Act",
    applies_to=["purchase_register", "gstr2b"],
    tags=["itc", "eligibility", "section-16"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_018",
    name="Section 16(4) Time Limit",
    category=RuleCategory.ITC,
    severity=RuleSeverity.CRITICAL,
    description="Enforce ITC claim deadline of 30 November following the end of the financial year per Section 16(4).",
    gst_ref="Section 16(4) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "eligibility", "section-16", "deadline"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_019",
    name="Section 16(2)(b) Tax Paid",
    category=RuleCategory.ITC,
    severity=RuleSeverity.HIGH,
    description="Verify supplier has actually paid tax to government before ITC can be availed per Section 16(2)(b).",
    gst_ref="Section 16(2)(b) CGST Act",
    applies_to=["purchase_register", "gstr2b"],
    tags=["itc", "eligibility", "section-16"],
))

REGISTRY.register(RuleDefinition(
    id="ITC_020",
    name="RCM Self-Invoice ITC",
    category=RuleCategory.ITC,
    severity=RuleSeverity.HIGH,
    description="Allow ITC on reverse charge self-invoices only when self-invoice and tax payment obligations are fulfilled.",
    gst_ref="Section 9(3) CGST Act",
    applies_to=["purchase_register"],
    tags=["itc", "rcm", "self-invoice"],
))
