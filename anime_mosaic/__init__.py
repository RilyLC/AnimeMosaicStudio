"""AnimeMosaicStudio — automatic mosaic removal studio.

The package is layered so the processing engine can be reused from a CLI, a
notebook or another front end without dragging in the desktop UI:

``anime_mosaic.core``
    Pure processing logic: detection, cropping, ComfyUI calls, blending, saving.
``anime_mosaic.services``
    Use-case helpers shared by the UI and CLI (environment probing, presets).
``anime_mosaic.ui``
    PySide6 desktop interface.  Only this layer imports Qt.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
