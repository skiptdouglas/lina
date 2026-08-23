"""Aggregate model import.

``Base.metadata.create_all`` only knows about tables whose modules have been
imported. Importing this module registers all of them.
"""

from app.audit.models import AuditRecord  # noqa: F401
from app.cases.models import Case  # noqa: F401
from app.core.models import Counter  # noqa: F401
from app.evidence.models import Evidence  # noqa: F401

__all__ = ["AuditRecord", "Case", "Counter", "Evidence"]
