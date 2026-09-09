"""NRM_ rules — invoice, GSTIN, and amount normalisation."""

from app.rules.base import REGISTRY, RuleCategory, RuleDefinition, RuleSeverity

REGISTRY.register(RuleDefinition(
    id="NRM_001",
    name="Whitespace Strip",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.LOW,
    description="Strip leading and trailing whitespace from all string fields before processing.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["normalisation", "string"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_002",
    name="Uppercase Normalisation",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.LOW,
    description="Convert GSTIN and invoice number fields to uppercase for consistent comparison.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["normalisation", "string", "uppercase"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_003",
    name="Forward Slash Removal",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.LOW,
    description="Remove forward slashes from invoice numbers to unify formatting variants.",
    applies_to=["purchase_register"],
    tags=["normalisation", "invoice"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_004",
    name="Hyphen Removal",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.LOW,
    description="Remove hyphens from invoice numbers when comparing across purchase register and GSTR-2B.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["normalisation", "invoice"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_005",
    name="Leading Zero Strip",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.LOW,
    description="Strip leading zeros from numeric invoice number segments to improve match rates.",
    applies_to=["purchase_register"],
    tags=["normalisation", "invoice"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_006",
    name="Prefix Strip",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.LOW,
    description="Remove common invoice prefixes such as INV, TAX, and GST before matching.",
    applies_to=["purchase_register"],
    tags=["normalisation", "invoice", "prefix"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_007",
    name="FY Segment Removal",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.LOW,
    description="Remove financial year segments embedded in invoice numbers that differ between systems.",
    applies_to=["purchase_register"],
    tags=["normalisation", "invoice", "fy"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_008",
    name="Debit/Credit Note Prefix Detection",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.MEDIUM,
    description="Detect DN/CN prefixes on invoice numbers and classify as debit or credit note entries.",
    gst_ref="Section 34 CGST Act",
    applies_to=["purchase_register", "gstr2b"],
    tags=["normalisation", "credit-note", "debit-note"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_009",
    name="GSTIN 15-Char Validation",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.HIGH,
    description="Validate GSTIN is exactly 15 characters before accepting a row for reconciliation.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["normalisation", "gstin", "validation"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_010",
    name="GSTIN State Code Extraction",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.LOW,
    description="Extract two-digit state code from the first two characters of a valid GSTIN.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["normalisation", "gstin", "state"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_011",
    name="GSTIN Checksum Validation",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.HIGH,
    description="Validate GSTIN checksum digit using the standard mod-36 algorithm.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["normalisation", "gstin", "validation", "checksum"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_012",
    name="GSTIN Period Format",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.MEDIUM,
    description="Normalise GSTR period fields to MMYYYY format for consistent period assignment.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["normalisation", "period", "format"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_013",
    name="Paise Conversion",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.HIGH,
    description="Convert rupee amounts to integer paise to eliminate decimal precision errors.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["normalisation", "amount", "paise"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_014",
    name="NULL Amount Defaulting",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.MEDIUM,
    description="Default NULL or empty amount fields to zero paise with a warning flag.",
    applies_to=["purchase_register"],
    tags=["normalisation", "amount", "null"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_015",
    name="Negative Amount Detection",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.HIGH,
    description="Detect negative taxable values and classify as credit notes or data errors.",
    applies_to=["purchase_register", "gstr2b"],
    tags=["normalisation", "amount", "negative"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_016",
    name="Tally Detection",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.LOW,
    description=(
        "Detect Tally Export format from column headers, classify Purchase vs Sales "
        "register type, and apply Tally-specific column alias mapping."
    ),
    applies_to=["purchase_register", "sales_register"],
    tags=["normalisation", "parser", "tally"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_017",
    name="Busy Detection",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.LOW,
    description="Detect Busy accounting export format from column headers and apply Busy-specific column mapping.",
    applies_to=["purchase_register"],
    tags=["normalisation", "parser", "busy"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_018",
    name="Header Row Auto-Detection",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.MEDIUM,
    description="Scan rows 0–3 to auto-detect the header row when importing spreadsheet files.",
    applies_to=["purchase_register"],
    tags=["normalisation", "parser", "header"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_019",
    name="Column Alias Mapping",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.MEDIUM,
    description="Map known column aliases to canonical field names across different export formats.",
    applies_to=["purchase_register"],
    tags=["normalisation", "parser", "columns"],
))

REGISTRY.register(RuleDefinition(
    id="NRM_020",
    name="ParseError on Missing Core Columns",
    category=RuleCategory.NORMALIZATION,
    severity=RuleSeverity.CRITICAL,
    description="Raise ParseError when required core columns (GSTIN, invoice number, invoice date, taxable value) are missing.",
    applies_to=["purchase_register"],
    tags=["normalisation", "parser", "error"],
))
