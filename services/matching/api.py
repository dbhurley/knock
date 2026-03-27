"""
FastAPI Endpoints for the Knock Matching & Prediction Engine.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from market_intel import MarketIntelligence
from predictor import TransitionPredictor
from reverse_matcher import ReverseMatcher
from scorer import MatchScorer

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://knock_admin:knock@postgres:5432/knock",
)

# ---------------------------------------------------------------------------
# App lifespan — connection pool
# ---------------------------------------------------------------------------

pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    yield
    if pool:
        await pool.close()


app = FastAPI(
    title="Knock Matching Engine",
    description="Candidate-school matching, transition prediction, and market intelligence",
    version="1.0.0",
    lifespan=lifespan,
)


def _get_pool() -> asyncpg.Pool:
    if pool is None:
        raise HTTPException(status_code=503, detail="Database pool not initialized")
    return pool


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ScoreRequest(BaseModel):
    candidate_id: str = Field(..., description="UUID of the candidate (people.id)")
    search_id: str = Field(..., description="UUID of the search (searches.id)")


class FindCandidatesRequest(BaseModel):
    search_id: str = Field(..., description="UUID of the search")
    limit: int = Field(20, ge=1, le=100)
    min_score: float = Field(0, ge=0, le=100)


class ReverseMatchRequest(BaseModel):
    candidate_id: str = Field(..., description="UUID of the candidate")
    limit: int = Field(25, ge=1, le=100)
    transition_only: bool = Field(False, description="Only show schools likely to transition")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    p = _get_pool()
    try:
        async with p.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "healthy", "service": "matching-engine"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------------------------------------------------------------------------
# Matching endpoints
# ---------------------------------------------------------------------------

@app.post("/match/score")
async def match_score(req: ScoreRequest):
    """Score one candidate against one search. Returns a detailed match report."""
    scorer = MatchScorer(_get_pool())
    try:
        report = await scorer.score(req.candidate_id, req.search_id)
        return report.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/match/find")
async def match_find(req: FindCandidatesRequest):
    """Find top N candidates for a search, ranked by composite score."""
    scorer = MatchScorer(_get_pool())
    try:
        results = await scorer.find_top_candidates(
            req.search_id, limit=req.limit, min_score=req.min_score
        )
        return {
            "search_id": req.search_id,
            "total_scored": len(results),
            "candidates": [r.to_dict() for r in results],
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/match/reverse")
async def match_reverse(req: ReverseMatchRequest):
    """Find ideal schools for a candidate."""
    matcher = ReverseMatcher(_get_pool())
    try:
        results = await matcher.find_schools(
            req.candidate_id,
            limit=req.limit,
            transition_only=req.transition_only,
        )
        return {
            "candidate_id": req.candidate_id,
            "total_matches": len(results),
            "schools": [r.to_dict() for r in results],
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Prediction endpoints
# ---------------------------------------------------------------------------

@app.get("/predict/transitions")
async def predict_transitions(
    limit: int = Query(50, ge=1, le=200),
    min_confidence: float = Query(20.0, ge=0, le=100),
):
    """Schools most likely to need a new HOS in the next 12-24 months."""
    predictor = TransitionPredictor(_get_pool())
    results = await predictor.predict_transitions(
        limit=limit, min_confidence=min_confidence
    )
    return {
        "total": len(results),
        "predictions": [r.to_dict() for r in results],
    }


@app.get("/predict/transitions/{school_id}")
async def predict_transition_single(school_id: str):
    """Predict transition likelihood for a single school."""
    predictor = TransitionPredictor(_get_pool())
    try:
        result = await predictor.predict_single(school_id)
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/predict/update-scores")
async def update_prediction_scores():
    """Batch update transition_prediction_score for all schools."""
    predictor = TransitionPredictor(_get_pool())
    count = await predictor.update_school_predictions()
    return {"updated": count}


# ---------------------------------------------------------------------------
# Intelligence endpoints
# ---------------------------------------------------------------------------

@app.get("/intel/dashboard")
async def intel_dashboard():
    """Market intelligence summary dashboard."""
    intel = MarketIntelligence(_get_pool())
    return await intel.dashboard_summary()


@app.get("/intel/pipeline")
async def intel_pipeline():
    """Candidate pipeline health report."""
    intel = MarketIntelligence(_get_pool())
    return await intel.pipeline_health()


@app.get("/intel/salary-trends")
async def intel_salary_trends():
    """Salary trend analysis by region and school type."""
    intel = MarketIntelligence(_get_pool())
    data = await intel.salary_trends()
    return {"trends": data}


@app.get("/intel/geographic-hotspots")
async def intel_hotspots(years_back: int = Query(3, ge=1, le=10)):
    """Geographic hotspots for HOS transitions."""
    intel = MarketIntelligence(_get_pool())
    data = await intel.geographic_hotspots(years_back=years_back)
    return {"hotspots": data}


@app.get("/intel/competitive")
async def intel_competitive():
    """Competitive intelligence - search firm performance."""
    intel = MarketIntelligence(_get_pool())
    data = await intel.competitive_intel()
    return {"firms": data}


@app.get("/intel/seasonal")
async def intel_seasonal():
    """Seasonal patterns in search activity."""
    intel = MarketIntelligence(_get_pool())
    data = await intel.seasonal_patterns()
    return {"patterns": data}


@app.get("/intel/longest-serving")
async def intel_longest_serving(limit: int = Query(50, ge=1, le=200)):
    """Schools with longest-serving HOS."""
    intel = MarketIntelligence(_get_pool())
    data = await intel.longest_serving_hos(limit=limit)
    return {"schools": data}
