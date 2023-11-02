""" Addon class definition and Settings definition must be imported here.

If addon class or settings definition won't be here their definition won't
be found by OpenPype discovery.
"""

from .version import __version__
from .addon import KitsuAddon


__all__ = (
    "__version__",
    "KitsuAddon",
)
