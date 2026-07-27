"""Make ``m15_sourcing`` importable when pytest is run from ``sourcing/``.

CI sets ``PYTHONPATH`` explicitly (see .github/workflows/backend-tests.yml), but
a developer running a bare ``pytest`` from this directory has no such help —
pytest's rootdir insertion doesn't reliably cover the parent of the tests dir
under every import mode. This mirrors what ``demo_crunch.py`` does for the same
reason, so both entry points work the same way.

``backend/`` is deliberately NOT added here. Only ``m15_sourcing/models.py``
needs it (``from app.database import Base``), and that module is the one piece
of this package that isn't pure — the test suite covers the pure modules, so
pulling SQLAlchemy's declarative Base into every test run would trade a real
import-isolation signal for nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
