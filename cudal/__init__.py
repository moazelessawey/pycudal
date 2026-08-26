"""
CuDAL -- Content Uniformity and Dissolution Acceptance Limits

Python translation of the legacy SAS/AF application (CuDAL.sas, cusp1.sas,
Cusp2.sas, Disp1.sas, Disp2.sas) used to derive parametric (tolerance
interval) acceptance limits for the USP <905> Content Uniformity and
USP <711> Dissolution tests.

Modules
-------
core   : shared probability primitives (content_uniformity_bound, dissolution_bound)
cusp1  : Content Uniformity, Sampling Plan 1 (single location)
cusp2  : Content Uniformity, Sampling Plan 2 (multiple locations)
disp1  : Dissolution, Sampling Plan 1 (single location)
disp2  : Dissolution, Sampling Plan 2 (multiple locations)
"""

from . import core, cusp1, cusp2, disp1, disp2

__version__ = "1.0.0"
__all__ = ["core", "cusp1", "cusp2", "disp1", "disp2"]
