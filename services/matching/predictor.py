"""
Transition Predictor
Predictive model for head-of-school transitions.
Scores schools by likelihood of needing a new HOS in the next 12-24 months.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import asyncpg


@dataclass
class TransitionSignal:
    name: str
    points: int
    fired: bool
    detail: str = ""


@dataclass
class TransitionPrediction:
    school_id: str
    school_name: str
    state: str
    city: str
    enrollment: int | None
    tier: str

    # Current HOS info
    current_hos_name: str | None
    current_hos_tenure_years: float | None

    # Signals
    signals: list[TransitionSignal] = field(default_factory=list)
    raw_points: int = 0
    confidence_score: float = 0.0     # 0-100 normalized
    confidence_label: str = ""        # 'very_high', 'high', 'moderate', 'low'
    predicted_window: str = ""        # '0-6 months', '6-12 months', '12-24 months'
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "school_id": self.school_id,
            "school_name": self.school_name,
            "state": self.state,
            "city": self.city,
            "enrollment": self.enrollment,
            "tier": self.tier,
            "current_hos_name": self.current_hos_name,
            "current_hos_tenure_years": (
                round(self.current_hos_tenure_years, 1)
                if self.current_hos_tenure_years is not None
                else None
            ),
            "signals": [
                {
                    "name": s.name,
                    "points": s.points,
                    "fired": s.fired,
                    "detail": s.detail,
                }
                for s in self.signals
                if s.fired
            ],
            "raw_points": self.raw_points,
            "confidence_score": round(self.confidence_score, 1),
            "confidence_label": self.confidence_label,
            "predicted_window": self.predicted_window,
            "reasoning": self.reasoning,
        }


# Maximum possible raw points if every signal fires
_MAX_POINTS = 15 + 25 + 20 + 10 + 30 + 40 + 35 + 10 + 10 + 15 + 15 + 50  # = 275


class TransitionPredictor:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def _load_school_data(self, conn: asyncpg.Connection, school: dict) -> dict:
        """Enrich school record with leadership and financial signals."""
        school_id = school["id"]

        # Current HOS
        hos_row = await conn.fetchrow(
            """
            SELECT slh.*, p.full_name AS hos_name
            FROM school_leadership_history slh
            LEFT JOIN people p ON p.id = slh.person_id
            WHERE slh.school_id = $1 AND slh.is_current = TRUE
            ORDER BY slh.start_date DESC
            LIMIT 1
            """,
            school_id,
        )
        school["hos"] = dict(hos_row) if hos_row else None

        # Board chair changes in last 2 years
        board_changes = await conn.fetchval(
            """
            SELECT COUNT(*) FROM school_board_members
            WHERE school_id = $1
            AND role IN ('chair', 'board_chair')
            AND term_start > NOW() - INTERVAL '2 years'
            """,
            school_id,
        )
        school["recent_board_chair_changes"] = board_changes or 0

        # Senior admin departures in last 18 months
        admin_departures = await conn.fetchval(
            """
            SELECT COUNT(*) FROM school_leadership_history
            WHERE school_id = $1
            AND is_current = FALSE
            AND end_date > NOW() - INTERVAL '18 months'
            AND position_title NOT ILIKE '%head of school%'
            AND position_title NOT ILIKE '%president%'
            """,
            school_id,
        )
        school["recent_admin_departures"] = admin_departures or 0

        # Financial data (most recent 2 years)
        fin_rows = await conn.fetch(
            """
            SELECT fiscal_year, enrollment, revenue, expenses, endowment
            FROM school_financials
            WHERE school_id = $1
            ORDER BY fiscal_year DESC
            LIMIT 3
            """,
            school_id,
        )
        school["financials"] = [dict(r) for r in fin_rows]

        # Check for active searches with competitors
        competitor_search = await conn.fetchval(
            """
            SELECT COUNT(*) FROM searches
            WHERE school_id = $1
            AND status NOT IN ('placed', 'closed_no_fill', 'cancelled')
            AND lead_consultant NOT ILIKE '%knock%'
            AND lead_consultant IS NOT NULL
            AND lead_consultant != ''
            """,
            school_id,
        )
        school["competitor_search_active"] = (competitor_search or 0) > 0

        # Check for interim positions posted
        interim_search = await conn.fetchval(
            """
            SELECT COUNT(*) FROM searches
            WHERE school_id = $1
            AND (position_title ILIKE '%interim%' OR position_category = 'interim_head')
            AND status NOT IN ('placed', 'closed_no_fill', 'cancelled')
            """,
            school_id,
        )
        school["has_interim_posting"] = (interim_search or 0) > 0

        # Check for existing transition_prediction fields
        school["transition_prediction_score"] = school.get("transition_prediction_score")

        return school

    def _evaluate_signals(self, school: dict) -> list[TransitionSignal]:
        """Evaluate all transition signals for a school."""
        signals: list[TransitionSignal] = []
        hos = school.get("hos")
        today = date.today()

        # 1. HOS tenure > 7 years (+15)
        tenure_years = None
        if hos and hos.get("start_date"):
            diff = (today - hos["start_date"]).days / 365.25
            tenure_years = diff
            signals.append(TransitionSignal(
                name="hos_tenure_gt_7",
                points=15,
                fired=tenure_years > 7,
                detail=f"Current HOS tenure: {tenure_years:.1f} years",
            ))
        else:
            signals.append(TransitionSignal(
                name="hos_tenure_gt_7", points=15, fired=False,
                detail="HOS start date unknown",
            ))

        # 2. HOS tenure > 10 years (+25)
        signals.append(TransitionSignal(
            name="hos_tenure_gt_10",
            points=25,
            fired=(tenure_years is not None and tenure_years > 10),
            detail=f"Tenure: {tenure_years:.1f}y" if tenure_years else "Unknown",
        ))

        # 3. HOS age > 60 (+20) - we may not have age data
        # We check last_head_change plus typical career progression
        last_change = school.get("last_head_change")
        age_signal_fired = False
        age_detail = "HOS age data not available"
        if tenure_years and tenure_years > 15:
            # Very long tenure suggests older HOS
            age_signal_fired = True
            age_detail = f"Tenure of {tenure_years:.0f}y suggests HOS likely over 60"

        signals.append(TransitionSignal(
            name="hos_age_over_60",
            points=20,
            fired=age_signal_fired,
            detail=age_detail,
        ))

        # 4. Recent board chair change (+10)
        board_changes = school.get("recent_board_chair_changes", 0)
        signals.append(TransitionSignal(
            name="recent_board_chair_change",
            points=10,
            fired=board_changes > 0,
            detail=f"{board_changes} board chair change(s) in last 2 years",
        ))

        # 5. Interim posting (+30)
        signals.append(TransitionSignal(
            name="interim_position_posted",
            points=30,
            fired=school.get("has_interim_posting", False),
            detail="School has active interim position posting" if school.get("has_interim_posting") else "No interim postings",
        ))

        # 6. News mentions of search/transition (+40)
        # Placeholder: in production this would query a news/scraping table
        # For now, check if school has any tags containing 'transition' or 'search'
        tags = [t.lower() for t in (school.get("tags") or [])]
        news_signal = any("transition" in t or "search_pending" in t for t in tags)
        signals.append(TransitionSignal(
            name="news_mentions_search",
            points=40,
            fired=news_signal,
            detail="Tags indicate transition/search activity" if news_signal else "No search-related news signals",
        ))

        # 7. HOS removed school from LinkedIn (+35)
        # Placeholder: would come from LinkedIn data sync
        signals.append(TransitionSignal(
            name="hos_linkedin_removed",
            points=35,
            fired=False,
            detail="LinkedIn monitoring not yet implemented",
        ))

        # 8. Enrollment decline > 10% over 2 years (+10)
        financials = school.get("financials", [])
        enrollment_decline = False
        enrollment_detail = "Insufficient enrollment data"
        if len(financials) >= 2:
            recent = financials[0].get("enrollment")
            older = financials[-1].get("enrollment")
            if recent and older and older > 0:
                change_pct = (recent - older) / older * 100
                if change_pct < -10:
                    enrollment_decline = True
                    enrollment_detail = f"Enrollment declined {change_pct:.1f}% over {len(financials)} years"
                else:
                    enrollment_detail = f"Enrollment change: {change_pct:+.1f}%"

        signals.append(TransitionSignal(
            name="enrollment_decline_10pct",
            points=10,
            fired=enrollment_decline,
            detail=enrollment_detail,
        ))

        # 9. Financial stress from 990 (+10)
        financial_stress = False
        fin_detail = "Insufficient financial data"
        if financials:
            latest = financials[0]
            revenue = latest.get("revenue")
            expenses = latest.get("expenses")
            if revenue and expenses and revenue > 0:
                margin = (revenue - expenses) / revenue
                if margin < -0.05:
                    financial_stress = True
                    fin_detail = f"Operating at {margin*100:.1f}% margin (FY{latest.get('fiscal_year')})"
                else:
                    fin_detail = f"Operating margin: {margin*100:.1f}% (FY{latest.get('fiscal_year')})"

        signals.append(TransitionSignal(
            name="financial_stress_990",
            points=10,
            fired=financial_stress,
            detail=fin_detail,
        ))

        # 10. HOS speaking at career transitions events (+15)
        # Placeholder: would come from event scraping
        signals.append(TransitionSignal(
            name="hos_career_transition_events",
            points=15,
            fired=False,
            detail="Event monitoring not yet implemented",
        ))

        # 11. Multiple senior admin departures (+15)
        admin_deps = school.get("recent_admin_departures", 0)
        signals.append(TransitionSignal(
            name="multiple_admin_departures",
            points=15,
            fired=admin_deps >= 2,
            detail=f"{admin_deps} senior admin departure(s) in last 18 months",
        ))

        # 12. School hiring search firm competitors (+50 - confirmed!)
        signals.append(TransitionSignal(
            name="competitor_search_firm",
            points=50,
            fired=school.get("competitor_search_active", False),
            detail="School has active search with a competitor firm" if school.get("competitor_search_active") else "No competitor search detected",
        ))

        return signals

    def _compute_prediction(self, signals: list[TransitionSignal]) -> tuple[int, float, str, str]:
        """Compute raw points, confidence score, label, and predicted window."""
        fired = [s for s in signals if s.fired]
        raw_points = sum(s.points for s in fired)

        # Normalize to 0-100 confidence
        # Use a sigmoid-like curve: 50 points = ~50% confidence, 150+ = ~95%
        import math
        confidence = 100 / (1 + math.exp(-0.04 * (raw_points - 75)))

        if confidence >= 80:
            label = "very_high"
            window = "0-12 months"
        elif confidence >= 60:
            label = "high"
            window = "6-18 months"
        elif confidence >= 40:
            label = "moderate"
            window = "12-24 months"
        else:
            label = "low"
            window = "24+ months"

        return raw_points, confidence, label, window

    async def predict_transitions(
        self, limit: int = 50, min_confidence: float = 20.0
    ) -> list[TransitionPrediction]:
        """Predict which schools are most likely to need a new HOS."""
        async with self.pool.acquire() as conn:
            # Get all active schools
            rows = await conn.fetch(
                """
                SELECT * FROM schools
                WHERE is_active = TRUE
                ORDER BY enrollment_total DESC NULLS LAST
                """
            )

            predictions: list[TransitionPrediction] = []
            for row in rows:
                school = dict(row)
                school = await self._load_school_data(conn, school)

                signals = self._evaluate_signals(school)
                raw_points, confidence, label, window = self._compute_prediction(signals)

                if confidence < min_confidence:
                    continue

                hos = school.get("hos")
                hos_name = hos.get("hos_name") if hos else None
                tenure_years = None
                if hos and hos.get("start_date"):
                    tenure_years = (date.today() - hos["start_date"]).days / 365.25

                fired_signals = [s for s in signals if s.fired]
                reasoning_parts = [s.detail for s in fired_signals[:5]]

                predictions.append(TransitionPrediction(
                    school_id=str(school["id"]),
                    school_name=school.get("name", "Unknown"),
                    state=(school.get("state") or "").upper(),
                    city=school.get("city") or "",
                    enrollment=school.get("enrollment_total"),
                    tier=school.get("tier") or "unranked",
                    current_hos_name=hos_name,
                    current_hos_tenure_years=tenure_years,
                    signals=signals,
                    raw_points=raw_points,
                    confidence_score=confidence,
                    confidence_label=label,
                    predicted_window=window,
                    reasoning="; ".join(reasoning_parts),
                ))

        predictions.sort(key=lambda p: p.confidence_score, reverse=True)
        return predictions[:limit]

    async def predict_single(self, school_id: str) -> TransitionPrediction:
        """Predict transition likelihood for a single school."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM schools WHERE id = $1", school_id)
            if row is None:
                raise ValueError(f"School {school_id} not found")

            school = dict(row)
            school = await self._load_school_data(conn, school)

        signals = self._evaluate_signals(school)
        raw_points, confidence, label, window = self._compute_prediction(signals)

        hos = school.get("hos")
        hos_name = hos.get("hos_name") if hos else None
        tenure_years = None
        if hos and hos.get("start_date"):
            tenure_years = (date.today() - hos["start_date"]).days / 365.25

        fired_signals = [s for s in signals if s.fired]
        reasoning_parts = [s.detail for s in fired_signals]

        return TransitionPrediction(
            school_id=str(school["id"]),
            school_name=school.get("name", "Unknown"),
            state=(school.get("state") or "").upper(),
            city=school.get("city") or "",
            enrollment=school.get("enrollment_total"),
            tier=school.get("tier") or "unranked",
            current_hos_name=hos_name,
            current_hos_tenure_years=tenure_years,
            signals=signals,
            raw_points=raw_points,
            confidence_score=confidence,
            confidence_label=label,
            predicted_window=window,
            reasoning="; ".join(reasoning_parts),
        )

    async def update_school_predictions(self) -> int:
        """Batch update transition_prediction_score for all active schools.
        Returns the number of schools updated."""
        predictions = await self.predict_transitions(limit=10000, min_confidence=0)
        updated = 0
        async with self.pool.acquire() as conn:
            for pred in predictions:
                await conn.execute(
                    """
                    UPDATE schools
                    SET transition_prediction_score = $1,
                        predicted_transition_date = CASE
                            WHEN $1 >= 60 THEN NOW() + INTERVAL '12 months'
                            WHEN $1 >= 40 THEN NOW() + INTERVAL '18 months'
                            ELSE NOW() + INTERVAL '24 months'
                        END,
                        updated_at = NOW()
                    WHERE id = $2
                    """,
                    round(pred.confidence_score, 2),
                    pred.school_id,
                )
                updated += 1
        return updated
