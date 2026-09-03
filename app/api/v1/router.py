"""
app/api/v1/router.py
Aggregates all v1 sub-routers into a single APIRouter.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, calendar, histories, predictions

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(calendar.router, prefix="/calendar", tags=["Economic Calendar"])
api_v1_router.include_router(predictions.router, prefix="/predictions", tags=["Predictions"])
api_v1_router.include_router(histories.router, prefix="/history", tags=["History & Accuracy"])
