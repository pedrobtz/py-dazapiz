"""The Azure helpers azure-identity lacks.

The design is in `.agents/design.md` in the repository.
"""

from importlib.metadata import version

__version__ = version("dazure")

__all__ = ["__version__"]
