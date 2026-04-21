import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AmendmentResult:
    type: str  # CANCELLED | UPWARD_REVISION | DOWNWARD_REVISION | NO_CHANGE
    original_itc_paise: int
    new_itc_paise: int
    itc_change_paise: int  # = new_itc_paise - original_itc_paise
    # negative for DOWNWARD_REVISION and CANCELLED
    action_required: str
    description: str
    urgency: str  # LOW | MEDIUM | HIGH | CRITICAL


def process_amendment(
    original_record: dict, amended_record: Optional[dict]
) -> AmendmentResult:
    if original_record is None:
        raise ValueError("original_record cannot be None")

    original_itc_paise = original_record["total_tax_paise"]

    if amended_record is None:
        amendment_type = "CANCELLED"
        new_itc_paise = 0
        itc_change_paise = 0 - original_itc_paise
    else:
        new_itc_paise = amended_record["total_tax_paise"]
        itc_change_paise = new_itc_paise - original_itc_paise
        if itc_change_paise > 0:
            amendment_type = "UPWARD_REVISION"
        elif itc_change_paise < 0:
            amendment_type = "DOWNWARD_REVISION"
        else:
            amendment_type = "NO_CHANGE"

    if amendment_type == "CANCELLED":
        urgency = "CRITICAL"
    elif amendment_type == "DOWNWARD_REVISION":
        urgency = "HIGH"
    elif amendment_type == "UPWARD_REVISION":
        urgency = "LOW"
    else:
        urgency = "LOW"

    if amendment_type == "CANCELLED":
        action_required = f"Reverse full ITC of Rs{original_itc_paise // 100}"
        description = "Supplier has cancelled this invoice"
    elif amendment_type == "DOWNWARD_REVISION":
        action_required = f"Reverse excess ITC of Rs{abs(itc_change_paise) // 100}"
        description = "Supplier revised invoice downward"
    elif amendment_type == "UPWARD_REVISION":
        action_required = f"Claim additional ITC of Rs{itc_change_paise // 100}"
        description = "Supplier revised invoice upward"
    else:
        action_required = "No action required"
        description = "No ITC change after amendment"

    return AmendmentResult(
        type=amendment_type,
        original_itc_paise=original_itc_paise,
        new_itc_paise=new_itc_paise,
        itc_change_paise=itc_change_paise,
        action_required=action_required,
        description=description,
        urgency=urgency,
    )
