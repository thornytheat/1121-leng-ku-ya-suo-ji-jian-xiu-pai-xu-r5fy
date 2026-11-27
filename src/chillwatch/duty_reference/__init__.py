"""历史工况。"""
from .service import evaluate

__all__ = ["evaluate"]

from .service import compare_references
__all__ += ["compare_references"]
