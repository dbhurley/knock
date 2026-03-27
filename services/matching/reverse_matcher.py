"""
Reverse Match - School Finder for Candidates
Given a candidate, find schools that would be ideal fits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import asyncpg

from scorer import (
    ROLE_SENIORITY,
    SOFT_WEIGHTS,
    _norm,
    _range_contains,
    _tag_overlap,
    _tier_label,
    _years_between,
)


@dataclass
class SchoolMatch:
    school_id: str
    school_name: str
    state: str
    city: str
    enrollment: int | None
    tier: str
    current_hos_tenure_years: float | None
    transition_likely: bool
    fit_score: float
    fit_tier: str
    factors: dict = field(default_factory=dict)
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "school_id": self.school_id,
            "school_name": self.school_name,
            "state": self.state,
            "city": self.city,
            "enrollment": self.enrollment,
            "tier": self.tier,
            "current_hos_tenure_years": (
                round(self.current_hos_tenure_years, 1)
                if self.current_hos_tenure_years is not None
                else None
            ),
            "transition_likely": self.transition_likely,
            "fit_score": round(self.fit_score, 2),
            "fit_tier": self.fit_tier,
            "factors": {k: round(v, 1) for k, v in self.factors.items()},
            "reasoning": self.reasoning,
        }


class ReverseMatcher:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def _load_candidate(self, person_id: str) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM people WHERE id = $1", person_id)
            if row is None:
                raise ValueError(f"Candidate {person_id} not found")
            candidate = dict(row)

            ed_rows = await conn.fetch(
                "SELECT degree, field_of_study, is_education_leadership "
                "FROM person_education WHERE person_id = $1",
                person_id,
            )
            candidate["education"] = [dict(r) for r in ed_rows]

            exp_rows = await conn.fetch(
                "SELECT * FROM person_experience WHERE person_id = $1 ORDER BY start_date DESC",
                person_id,
            )
            candidate["experience"] = [dict(r) for r in exp_rows]
            return candidate

    async def _get_school_pool(self, candidate: dict, limit: int = 300) -> list[dict]:
        """Get schools that could plausibly be fits for this candidate."""
        pref_states = candidate.get("preferred_states") or []
        willing_to_relocate = candidate.get("willing_to_relocate")
        candidate_state = candidate.get("state")

        async with self.pool.acquire() as conn:
            # Build a broad query: prefer geographic match but include others
            if pref_states:
                rows = await conn.fetch(
                    """
                    SELECT s.*,
                        slh.person_id AS current_hos_person_id,
                        slh.start_date AS hos_start_date,
                        slh.position_title AS hos_title
                    FROM schools s
                    LEFT JOIN school_leadership_history slh
                        ON slh.school_id = s.id AND slh.is_current = TRUE
                    WHERE s.is_active = TRUE
                    ORDER BY
                        CASE WHEN s.state = ANY($1::text[]) THEN 0 ELSE 1 END,
                        s.enrollment_total DESC NULLS LAST
                    LIMIT $2
                    """,
                    pref_states,
                    limit,
                )
            elif candidate_state:
                rows = await conn.fetch(
                    """
                    SELECT s.*,
                        slh.person_id AS current_hos_person_id,
                        slh.start_date AS hos_start_date,
                        slh.position_title AS hos_title
                    FROM schools s
                    LEFT JOIN school_leadership_history slh
                        ON slh.school_id = s.id AND slh.is_current = TRUE
                    WHERE s.is_active = TRUE
                    ORDER BY
                        CASE WHEN s.state = $1 THEN 0 ELSE 1 END,
                        s.enrollment_total DESC NULLS LAST
                    LIMIT $2
                    """,
                    candidate_state,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT s.*,
                        slh.person_id AS current_hos_person_id,
                        slh.start_date AS hos_start_date,
                        slh.position_title AS hos_title
                    FROM schools s
                    LEFT JOIN school_leadership_history slh
                        ON slh.school_id = s.id AND slh.is_current = TRUE
                    WHERE s.is_active = TRUE
                    ORDER BY s.enrollment_total DESC NULLS LAST
                    LIMIT $1
                    """,
                    limit,
                )

            return [dict(r) for r in rows]

    def _score_school_for_candidate(self, candidate: dict, school: dict) -> SchoolMatch:
        """Score how good a fit this school is for the candidate."""
        factors: dict[str, float] = {}
        reasons: list[str] = []

        # 1. HOS tenure - transition likelihood
        hos_start = school.get("hos_start_date")
        tenure_years: float | None = None
        transition_likely = False
        if hos_start:
            tenure_years = _years_between(hos_start, date.today())
            if tenure_years is not None:
                if tenure_years > 10:
                    factors["transition_likelihood"] = 95
                    transition_likely = True
                    reasons.append(f"HOS tenure {tenure_years:.1f}y - high transition probability")
                elif tenure_years > 7:
                    factors["transition_likelihood"] = 70
                    transition_likely = True
                    reasons.append(f"HOS tenure {tenure_years:.1f}y - transition window opening")
                elif tenure_years > 5:
                    factors["transition_likelihood"] = 40
                    reasons.append(f"HOS tenure {tenure_years:.1f}y - mid-tenure")
                else:
                    factors["transition_likelihood"] = 15
                    reasons.append(f"HOS tenure {tenure_years:.1f}y - recently placed")
        else:
            factors["transition_likelihood"] = 50
            reasons.append("HOS tenure data unavailable")

        # 2. Geographic fit
        school_state = _norm(school.get("state", ""))
        pref_states = [_norm(s) for s in (candidate.get("preferred_states") or []) if s]
        candidate_state = _norm(candidate.get("state", ""))

        if school_state in pref_states:
            factors["geographic_fit"] = 100
        elif school_state == candidate_state:
            factors["geographic_fit"] = 90
        elif candidate.get("willing_to_relocate"):
            factors["geographic_fit"] = 60
        else:
            factors["geographic_fit"] = 30

        # 3. School type alignment
        candidate_types = set(
            _norm(t) for t in (candidate.get("school_type_experience") or []) if t
        )
        for exp in candidate.get("experience", []):
            st = _norm(exp.get("school_type", ""))
            if st:
                candidate_types.add(st)

        school_attrs = []
        for field_name in ["school_type", "boarding_status", "coed_status"]:
            val = _norm(school.get(field_name, ""))
            if val and val not in ("none", "unknown", ""):
                school_attrs.append(val)

        if school_attrs:
            matches = sum(1 for a in school_attrs if a in candidate_types)
            factors["type_alignment"] = (matches / len(school_attrs)) * 100
        else:
            factors["type_alignment"] = 50

        # 4. Enrollment / size fit (stretch but credible)
        target_enrollment = school.get("enrollment_total")
        max_enrollment_led = 0
        for exp in candidate.get("experience", []):
            se = exp.get("school_enrollment")
            if se and se > max_enrollment_led:
                max_enrollment_led = se

        if target_enrollment and max_enrollment_led:
            ratio = target_enrollment / max(max_enrollment_led, 1)
            if 0.7 <= ratio <= 1.0:
                factors["size_fit"] = 95  # same or slightly smaller
            elif 1.0 < ratio <= 1.5:
                factors["size_fit"] = 85  # credible stretch up
            elif 1.5 < ratio <= 2.0:
                factors["size_fit"] = 60  # big stretch
            elif ratio < 0.7:
                factors["size_fit"] = 70  # overqualified on size
            else:
                factors["size_fit"] = 35
        else:
            factors["size_fit"] = 50

        # 5. Step-up credibility
        current_role = _norm(candidate.get("primary_role", ""))
        current_level = ROLE_SENIORITY.get(current_role, 3)
        # For HOS searches, target level is 5
        target_level = 5
        gap = target_level - current_level
        if gap == 0:
            factors["step_credibility"] = 85  # lateral
        elif gap == 1:
            factors["step_credibility"] = 95  # ideal step up
        elif gap == 2:
            factors["step_credibility"] = 55  # stretch
        elif gap < 0:
            factors["step_credibility"] = 70  # step down
        else:
            factors["step_credibility"] = 30

        # 6. Cultural/mission overlap
        candidate_tags = (candidate.get("cultural_fit_tags") or []) + (candidate.get("tags") or [])
        school_tags = school.get("tags") or []
        factors["cultural_fit"] = _tag_overlap(candidate_tags, school_tags) if candidate_tags and school_tags else 50

        # Composite score (weighted)
        weights = {
            "transition_likelihood": 0.25,
            "geographic_fit": 0.20,
            "type_alignment": 0.15,
            "size_fit": 0.12,
            "step_credibility": 0.15,
            "cultural_fit": 0.13,
        }
        fit_score = sum(factors.get(k, 50) * w for k, w in weights.items())

        return SchoolMatch(
            school_id=str(school.get("id", "")),
            school_name=school.get("name", "Unknown"),
            state=(school.get("state") or "").upper(),
            city=school.get("city") or "",
            enrollment=school.get("enrollment_total"),
            tier=school.get("tier") or "unranked",
            current_hos_tenure_years=tenure_years,
            transition_likely=transition_likely,
            fit_score=fit_score,
            fit_tier=_tier_label(fit_score),
            factors=factors,
            reasoning="; ".join(reasons),
        )

    async def find_schools(
        self,
        candidate_id: str,
        limit: int = 25,
        transition_only: bool = False,
    ) -> list[SchoolMatch]:
        """Find and rank schools that would be ideal fits for a candidate."""
        candidate = await self._load_candidate(candidate_id)
        schools = await self._get_school_pool(candidate, limit=500)

        results: list[SchoolMatch] = []
        for school in schools:
            match = self._score_school_for_candidate(candidate, school)
            if transition_only and not match.transition_likely:
                continue
            results.append(match)

        results.sort(key=lambda m: m.fit_score, reverse=True)
        return results[:limit]
