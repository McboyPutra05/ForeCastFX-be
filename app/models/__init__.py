# app/models/__init__.py
# Import all models here so SQLAlchemy metadata can discover them.

from app.models.user import User
from app.models.economic_event import EconomicEvent, EconomicRelease
from app.models.leading_indicator import LeadingIndicatorConfig
from app.models.prediction_log import PredictionLog

__all__ = [
    "User",
    "EconomicEvent",
    "EconomicRelease",
    "LeadingIndicatorConfig",
    "PredictionLog",
]
