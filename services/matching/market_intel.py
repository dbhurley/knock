"""
Market Intelligence Dashboard Queries
SQL-based analytics for the Knock executive search platform.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import asyncpg


class MarketIntelligence:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # ------------------------------------------------------------------
    # 1. Schools with longest-serving HOS (transition candidates)
    # ------------------------------------------------------------------

    async def longest_serving_hos(self, limit: int = 50) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    s.id AS school_id,
                    s.name AS school_name,
                    s.state,
                    s.city,
                    s.enrollment_total,
                    s.tier,
                    slh.position_title,
                    p.full_name AS hos_name,
                    slh.start_date AS hos_start_date,
                    EXTRACT(YEAR FROM AGE(NOW(), slh.start_date))::int AS tenure_years,
                    s.transition_prediction_score
                FROM school_leadership_history slh
                JOIN schools s ON s.id = slh.school_id
                LEFT JOIN people p ON p.id = slh.person_id
                WHERE slh.is_current = TRUE
                AND s.is_active = TRUE
                AND slh.start_date IS NOT NULL
                ORDER BY slh.start_date ASC
                LIMIT $1
                """,
                limit,
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 2. Geographic hotspots (states/regions with most transitions)
    # ------------------------------------------------------------------

    async def geographic_hotspots(self, years_back: int = 3) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH transitions AS (
                    SELECT
                        s.state,
                        COUNT(*) AS transition_count,
                        COUNT(DISTINCT s.id) AS schools_involved
                    FROM school_leadership_history slh
                    JOIN schools s ON s.id = slh.school_id
                    WHERE slh.is_current = FALSE
                    AND slh.end_date > NOW() - ($1 || ' years')::interval
                    AND s.state IS NOT NULL
                    GROUP BY s.state
                ),
                active_schools AS (
                    SELECT state, COUNT(*) AS total_schools
                    FROM schools
                    WHERE is_active = TRUE AND state IS NOT NULL
                    GROUP BY state
                )
                SELECT
                    t.state,
                    t.transition_count,
                    t.schools_involved,
                    a.total_schools,
                    ROUND(t.transition_count::numeric / GREATEST(a.total_schools, 1) * 100, 1)
                        AS transition_rate_pct
                FROM transitions t
                JOIN active_schools a ON a.state = t.state
                ORDER BY t.transition_count DESC
                """,
                str(years_back),
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 3. Salary trend analysis by region and school type
    # ------------------------------------------------------------------

    async def salary_trends(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH salary_data AS (
                    SELECT
                        s.state,
                        s.school_type,
                        s.boarding_status,
                        p.placement_date,
                        EXTRACT(YEAR FROM p.placement_date)::int AS year,
                        p.salary
                    FROM placements p
                    JOIN schools s ON s.id = p.school_id
                    WHERE p.salary IS NOT NULL AND p.salary > 0
                    AND p.placement_date IS NOT NULL
                )
                SELECT
                    state,
                    school_type,
                    boarding_status,
                    year,
                    COUNT(*) AS placements,
                    ROUND(AVG(salary)) AS avg_salary,
                    MIN(salary) AS min_salary,
                    MAX(salary) AS max_salary,
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary)) AS median_salary
                FROM salary_data
                GROUP BY state, school_type, boarding_status, year
                ORDER BY year DESC, state, school_type
                """
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 4. Candidate pipeline health
    # ------------------------------------------------------------------

    async def pipeline_health(self) -> dict:
        async with self.pool.acquire() as conn:
            # Overall pipeline counts
            status_counts = await conn.fetch(
                """
                SELECT
                    candidate_status,
                    career_stage,
                    COUNT(*) AS count
                FROM people
                WHERE candidate_status IS NOT NULL
                GROUP BY candidate_status, career_stage
                ORDER BY candidate_status, career_stage
                """
            )

            # Active searches vs available candidates
            active_searches = await conn.fetchval(
                """
                SELECT COUNT(*) FROM searches
                WHERE status NOT IN ('placed', 'closed_no_fill', 'cancelled', 'on_hold')
                """
            )

            active_candidates = await conn.fetchval(
                """
                SELECT COUNT(*) FROM people
                WHERE candidate_status IN ('active', 'passive')
                """
            )

            # By position category
            search_demand = await conn.fetch(
                """
                SELECT
                    position_category,
                    COUNT(*) AS open_searches,
                    AVG(salary_range_high) AS avg_salary_high
                FROM searches
                WHERE status NOT IN ('placed', 'closed_no_fill', 'cancelled', 'on_hold')
                GROUP BY position_category
                ORDER BY open_searches DESC
                """
            )

            candidate_supply = await conn.fetch(
                """
                SELECT
                    primary_role,
                    candidate_status,
                    COUNT(*) AS count
                FROM people
                WHERE candidate_status IN ('active', 'passive')
                GROUP BY primary_role, candidate_status
                ORDER BY count DESC
                """
            )

            # Candidates by rating
            rating_dist = await conn.fetch(
                """
                SELECT
                    knock_rating,
                    COUNT(*) AS count
                FROM people
                WHERE candidate_status IN ('active', 'passive')
                AND knock_rating IS NOT NULL
                GROUP BY knock_rating
                ORDER BY knock_rating DESC
                """
            )

            return {
                "active_searches": active_searches or 0,
                "active_candidates": active_candidates or 0,
                "ratio": round((active_candidates or 0) / max(active_searches or 1, 1), 1),
                "status_breakdown": [dict(r) for r in status_counts],
                "search_demand_by_role": [dict(r) for r in search_demand],
                "candidate_supply_by_role": [dict(r) for r in candidate_supply],
                "rating_distribution": [dict(r) for r in rating_dist],
            }

    # ------------------------------------------------------------------
    # 5. Competitive intelligence
    # ------------------------------------------------------------------

    async def competitive_intel(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    lead_consultant AS search_firm,
                    COUNT(*) AS total_searches,
                    COUNT(*) FILTER (WHERE status = 'placed') AS successful,
                    COUNT(*) FILTER (WHERE status = 'closed_no_fill') AS failed,
                    COUNT(*) FILTER (
                        WHERE status NOT IN ('placed', 'closed_no_fill', 'cancelled')
                    ) AS active,
                    ROUND(
                        COUNT(*) FILTER (WHERE status = 'placed')::numeric /
                        GREATEST(COUNT(*), 1) * 100, 1
                    ) AS success_rate_pct,
                    ROUND(AVG(placement_salary) FILTER (WHERE status = 'placed')) AS avg_salary
                FROM searches
                WHERE lead_consultant IS NOT NULL
                AND lead_consultant != ''
                GROUP BY lead_consultant
                ORDER BY total_searches DESC
                """
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 6. Seasonal patterns
    # ------------------------------------------------------------------

    async def seasonal_patterns(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    EXTRACT(MONTH FROM created_at)::int AS month,
                    TO_CHAR(DATE_TRUNC('month', created_at), 'Month') AS month_name,
                    COUNT(*) AS searches_started,
                    ROUND(AVG(EXTRACT(EPOCH FROM (
                        COALESCE(closed_at, NOW()) - created_at
                    )) / 86400))::int AS avg_duration_days
                FROM searches
                WHERE created_at IS NOT NULL
                GROUP BY EXTRACT(MONTH FROM created_at),
                         TO_CHAR(DATE_TRUNC('month', created_at), 'Month')
                ORDER BY month
                """
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Combined dashboard summary
    # ------------------------------------------------------------------

    async def dashboard_summary(self) -> dict:
        pipeline = await self.pipeline_health()
        seasonal = await self.seasonal_patterns()
        hotspots = await self.geographic_hotspots()
        competitive = await self.competitive_intel()
        longest = await self.longest_serving_hos(limit=10)

        return {
            "pipeline": pipeline,
            "seasonal_patterns": seasonal,
            "geographic_hotspots": hotspots,
            "competitive_intel": competitive,
            "longest_serving_hos": longest,
            "generated_at": datetime.utcnow().isoformat(),
        }
