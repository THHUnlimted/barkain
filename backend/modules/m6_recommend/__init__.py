"""M6 Recommendation Engine — deterministic stacking (Step 3e).

No LLM. `RecommendationService` gathers prices + identity + card + portal
inputs in one `asyncio.gather`, then stacks them in pure Python. Sentence
templates turn the winning path into headline + why copy.
"""

from modules.m6_recommend.router import router
from modules.m6_recommend.service import RecommendationService

__all__ = ["router", "RecommendationService"]
