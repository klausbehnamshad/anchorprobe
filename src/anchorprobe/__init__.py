"""anchorprobe: Stable Text Anchor profile, drift forensics and conformance probes.

An offset is not a number. It is a measurement with a unit, taken on a text in
one particular encoding form. This package makes the unit, the form and the
integrity scope explicit, converts between the addressing schemes used in
digital humanities text services, and explains why an anchor stopped matching.
"""

from .anchor import Anchor, ProfileError, Verdict, make_anchor, verify
from .canon import BOM, Canonical, CanonError, canonicalize, sha256_hex, variant
from .forensics import Diagnosis, Explanation, diagnose
from .units import UNITS, BoundaryError, Measurement, Ruler

__version__ = "0.1.0"
STA_VERSION = "0.1"

__all__ = [
    "Anchor",
    "BOM",
    "BoundaryError",
    "Canonical",
    "CanonError",
    "Diagnosis",
    "Explanation",
    "Measurement",
    "ProfileError",
    "Ruler",
    "STA_VERSION",
    "UNITS",
    "Verdict",
    "canonicalize",
    "diagnose",
    "make_anchor",
    "sha256_hex",
    "variant",
    "verify",
]
