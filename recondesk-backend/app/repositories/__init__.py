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

__all__ = [
    "AuroraComplianceRepository",
    "get_compliance_repository",
    "AuroraGstr3bRepository",
    "get_gstr3b_repository",
    "set_gstr3b_repository",
]
