"""Repository abstractions for ReconDesk datastores."""

from app.repositories.compliance import (
    AuroraComplianceRepository,
    get_compliance_repository,
)
from app.repositories.gstr3b import (
    AuroraGstr3bRepository,
    get_gstr3b_repository,
    set_gstr3b_repository,
)
from app.repositories.vendor_compliance import (
    AuroraVendorComplianceRepository,
    get_vendor_compliance_repository,
    set_vendor_compliance_repository,
)
from app.repositories.return_reconciliation import (
    AuroraReturnReconciliationRepository,
    get_return_reconciliation_repository,
    set_return_reconciliation_repository,
)

__all__ = [
    "AuroraComplianceRepository",
    "get_compliance_repository",
    "AuroraGstr3bRepository",
    "get_gstr3b_repository",
    "set_gstr3b_repository",
    "AuroraVendorComplianceRepository",
    "get_vendor_compliance_repository",
    "set_vendor_compliance_repository",
    "AuroraReturnReconciliationRepository",
    "get_return_reconciliation_repository",
    "set_return_reconciliation_repository",
]
