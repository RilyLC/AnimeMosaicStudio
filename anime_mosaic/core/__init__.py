"""Core processing primitives (no Qt, no UI concerns).

Import from here to script the pipeline without the desktop application::

    from anime_mosaic.core import Settings, Reporter, run_batch
"""

from .events import ProcessRecord, Reporter, RunSummary
from .pipeline import Pipeline, run_batch
from .settings import DEFAULTS, FIELD_SPECS, Settings, default_output_dir, load_settings, save_settings

__all__ = [
    "DEFAULTS",
    "FIELD_SPECS",
    "Pipeline",
    "ProcessRecord",
    "Reporter",
    "RunSummary",
    "Settings",
    "default_output_dir",
    "load_settings",
    "run_batch",
    "save_settings",
]
