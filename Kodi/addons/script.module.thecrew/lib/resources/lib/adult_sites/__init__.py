"""
Adult Sites Module
Provides individual site handlers for adult content
"""

from .base import CrewAdult

# Import all site modules to register them
from . import redtube
from . import whoreshub
from . import freeomovie
from . import xxxfiles
from . import homepornking
from . import pornrewind
from . import cumlouder

__all__ = ['CrewAdult']
