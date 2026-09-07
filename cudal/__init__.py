"""
CuDAL -- Content Uniformity and Dissolution Acceptance Limits

Python translation of the legacy SAS/AF application (CuDAL.sas, cusp1.sas,
Cusp2.sas, Disp1.sas, Disp2.sas) used to derive parametric (tolerance
interval) acceptance limits for the USP <905> Content Uniformity and
USP <711> Dissolution tests.

Modules
-------
core     : shared, fully vectorized probability primitives
           (content_uniformity_bound, dissolution_bound, and the new
           extended_release_bound / acid_stage_bound / delayed_release_bound)
           and the batched root finder used by the acceptance-limit
           table builders.
cusp1    : Content Uniformity, Sampling Plan 1 (single location)
cusp2    : Content Uniformity, Sampling Plan 2 (multiple locations)
disp1    : Dissolution (Immediate-Release), Sampling Plan 1 (single location)
disp2    : Dissolution (Immediate-Release), Sampling Plan 2 (multiple locations)
extdisp1 : Dissolution (Extended-Release), Sampling Plan 1 (single location)
extdisp2 : Dissolution (Extended-Release), Sampling Plan 2 (multiple locations)
deldisp1 : Dissolution (Delayed-Release), Sampling Plan 1 (single location)
deldisp2 : Dissolution (Delayed-Release), Sampling Plan 2 (multiple locations)

Note on extdisp*/deldisp*
--------------------------
Unlike cusp1/cusp2/disp1/disp2 (direct translations of the original SAS
CuDAL macros), the extdisp1/extdisp2/deldisp1/deldisp2 modules are new
derivations extending the same methodology to the Extended-Release and
Delayed-Release dosage-form categories defined in USP <711> (Acceptance
Tables 2, 3, and 4). See each module's docstring, and cudal/core.py's
extended_release_bound / acid_stage_bound / delayed_release_bound, for
the full derivations and stated modeling assumptions.
"""

from . import core, cusp1, cusp2, deldisp1, deldisp2, disp1, disp2, extdisp1, extdisp2

__all__ = [
    "core",
    "cusp1",
    "cusp2",
    "deldisp1",
    "deldisp2",
    "disp1",
    "disp2",
    "extdisp1",
    "extdisp2",
]

__version__ = "1.1.0rc1"
