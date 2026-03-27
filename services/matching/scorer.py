"""
Multi-Factor Match Scorer
Scores candidates against school positions using weighted hard/soft factors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

import asyncpg

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class HardFactorResult(Enum):
    PASS = "pass"
    FAIL = "fail"


@dataclass
class SoftFactorScore:
    name: str
    weight: float          # 0-1
    raw_score: float       # 0-100
    weighted_score: float  # raw * weight
    reasoning: str = ""


@dataclass
class MatchReport:
    candidate_id: str
    search_id: str
    school_id: str
    candidate_name: str
    school_name: str
    position_title: str

    # Hard factors
    hard_factors: dict[str, HardFactorResult] = field(default_factory=dict)
    hard_pass: bool = True

    # Soft factors
    soft_factors: list[SoftFactorScore] = field(default_factory=list)
    base_score: float = 0.0

    # Bonuses / penalties
    bonuses: list[dict] = field(default_factory=list)
    bonus_total: float = 0.0

    # Final
    composite_score: float = 0.0
    tier: str = ""       # 'excellent', 'strong', 'moderate', 'weak'
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "search_id": self.search_id,
            "school_id": self.school_id,
            "candidate_name": self.candidate_name,
            "school_name": self.school_name,
            "position_title": self.position_title,
            "hard_factors": {k: v.value for k, v in self.hard_factors.items()},
            "hard_pass": self.hard_pass,
            "soft_factors": [
                {
                    "name": sf.name,
                    "weight": sf.weight,
                    "raw_score": round(sf.raw_score, 1),
                    "weighted_score": round(sf.weighted_score, 2),
                    "reasoning": sf.reasoning,
                }
                for sf in self.soft_factors
            ],
            "base_score": round(self.base_score, 2),
            "bonuses": self.bonuses,
            "bonus_total": round(self.bonus_total, 2),
            "composite_score": round(self.composite_score, 2),
            "tier": self.tier,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Weight configuration
# ---------------------------------------------------------------------------

SOFT_WEIGHTS = {
    "position_trajectory":          0.20,
    "school_type_alignment":        0.15,
    "enrollment_match":             0.10,
    "geographic_desirability":      0.08,
    "cultural_mission_fit":         0.12,
    "financial_acumen":             0.08,
    "specialization_match":         0.10,
    "board_relationship_experience":0.05,
    "tenure_patterns":              0.07,
    "availability_timing":          0.05,
}

EDUCATION_RANK = {
    "ph_d": 4, "phd": 4, "ph.d.": 4,
    "ed_d": 4, "edd": 4, "ed.d.": 4, "doctorate": 4,
    "masters": 3, "m_ed": 3, "m.ed.": 3, "m_a": 3, "m.a.": 3,
    "m_s": 3, "m.s.": 3, "mba": 3, "m.b.a.": 3,
    "bachelors": 2, "b_a": 2, "b.a.": 2, "b_s": 2, "b.s.": 2,
}

# Roles ordered by seniority for trajectory scoring
ROLE_SENIORITY = {
    "teacher":              1,
    "department_chair":     2,
    "dean":                 3,
    "academic_dean":        3,
    "dean_of_students":     3,
    "assistant_head":       4,
    "associate_head":       4,
    "division_head":        4,
    "cfao":                 4,
    "head_of_school":       5,
    "president":            5,
    "interim_head":         5,
}

SCHOOL_TYPE_FIELDS = [
    ("boarding_status", "boarding_status"),
    ("school_type", "school_type"),
    ("coed_status", "coed_status"),
    ("religious_affiliation", "religious_affiliation"),
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _norm(val: Optional[str]) -> str:
    if val is None:
        return ""
    return val.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "")


def _education_level(degrees: list[str]) -> int:
    best = 0
    for d in degrees:
        best = max(best, EDUCATION_RANK.get(_norm(d), 0))
    return best


def _tag_overlap(a: list[str] | None, b: list[str] | None) -> float:
    """Return Jaccard-like overlap 0-100 between two tag lists."""
    if not a or not b:
        return 0.0
    sa = {_norm(t) for t in a if t}
    sb = {_norm(t) for t in b if t}
    if not sa or not sb:
        return 0.0
    intersection = sa & sb
    union = sa | sb
    return (len(intersection) / len(union)) * 100.0


def _range_contains(pg_range: str | None, value: int | None) -> float:
    """Score how well a postgres int4range/int8range contains the value (0-100)."""
    if pg_range is None or value is None:
        return 50.0  # unknown = neutral
    # asyncpg returns Range objects, but if we get a string parse it
    if isinstance(pg_range, str):
        cleaned = pg_range.strip("[]() ")
        if not cleaned or cleaned == "empty":
            return 50.0
        parts = cleaned.split(",")
        try:
            lo = int(parts[0]) if parts[0].strip() else 0
            hi = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 10**9
        except ValueError:
            return 50.0
    else:
        # asyncpg Range object
        lo = pg_range.lower if pg_range.lower is not None else 0
        hi = pg_range.upper if pg_range.upper is not None else 10**9

    if lo <= value <= hi:
        return 100.0
    # Stretch: allow up to 30% above range
    if value > hi:
        overshoot = (value - hi) / max(hi, 1)
        if overshoot <= 0.30:
            return max(50.0, 100.0 - overshoot * 166)  # linear decay
        return 20.0
    # Under range
    undershoot = (lo - value) / max(lo, 1)
    if undershoot <= 0.20:
        return max(60.0, 100.0 - undershoot * 200)
    return 30.0


def _years_between(d1: date | None, d2: date | None) -> float | None:
    if d1 is None or d2 is None:
        return None
    return abs((d2 - d1).days) / 365.25


def _tier_label(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "strong"
    if score >= 50:
        return "moderate"
    return "weak"


# ---------------------------------------------------------------------------
# Main scoring class
# ---------------------------------------------------------------------------

class MatchScorer:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # ----- data loaders -----------------------------------------------------

    async def _load_candidate(self, person_id: str) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM people WHERE id = $1", person_id)
            if row is None:
                raise ValueError(f"Candidate {person_id} not found")
            candidate = dict(row)

            # Education
            ed_rows = await conn.fetch(
                "SELECT degree, field_of_study, is_education_leadership "
                "FROM person_education WHERE person_id = $1",
                person_id,
            )
            candidate["education"] = [dict(r) for r in ed_rows]

            # Experience
            exp_rows = await conn.fetch(
                "SELECT * FROM person_experience WHERE person_id = $1 ORDER BY start_date DESC",
                person_id,
            )
            candidate["experience"] = [dict(r) for r in exp_rows]

            # Placements by Knock
            placement_count = await conn.fetchval(
                "SELECT COUNT(*) FROM placements WHERE person_id = $1", person_id
            )
            candidate["knock_placement_count"] = placement_count or 0

            # Recent rejections by similar schools
            rejection_count = await conn.fetchval(
                "SELECT COUNT(*) FROM search_candidates "
                "WHERE person_id = $1 AND status = 'rejected' "
                "AND updated_at > NOW() - INTERVAL '12 months'",
                person_id,
            )
            candidate["recent_rejections"] = rejection_count or 0

            return candidate

    async def _load_search(self, search_id: str) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT s.*, sc.name AS school_name, sc.state AS school_state, "
                "sc.school_type, sc.boarding_status, sc.coed_status, "
                "sc.religious_affiliation, sc.enrollment_total, sc.endowment_size, "
                "sc.operating_budget, sc.tags AS school_tags, sc.tier AS school_tier, "
                "sc.nais_member "
                "FROM searches s "
                "JOIN schools sc ON sc.id = s.school_id "
                "WHERE s.id = $1",
                search_id,
            )
            if row is None:
                raise ValueError(f"Search {search_id} not found")
            return dict(row)

    # ----- hard factors -----------------------------------------------------

    def _check_hard_factors(self, candidate: dict, search: dict) -> dict[str, HardFactorResult]:
        results: dict[str, HardFactorResult] = {}

        # 1. Required education level
        required_ed = search.get("required_education") or []
        if required_ed:
            candidate_degrees = [e.get("degree", "") for e in candidate.get("education", [])]
            required_level = max(
                (EDUCATION_RANK.get(_norm(r), 0) for r in required_ed), default=0
            )
            candidate_level = _education_level(candidate_degrees)
            results["education_level"] = (
                HardFactorResult.PASS if candidate_level >= required_level
                else HardFactorResult.FAIL
            )
        else:
            results["education_level"] = HardFactorResult.PASS

        # 2. Required years of experience
        req_years = search.get("required_experience_years")
        if req_years and req_years > 0:
            total_years = 0.0
            for exp in candidate.get("experience", []):
                start = exp.get("start_date")
                end = exp.get("end_date") or date.today()
                if start:
                    total_years += max(0, _years_between(start, end) or 0)
            results["experience_years"] = (
                HardFactorResult.PASS if total_years >= req_years
                else HardFactorResult.FAIL
            )
        else:
            results["experience_years"] = HardFactorResult.PASS

        # 3. Do not contact
        status = _norm(candidate.get("candidate_status", ""))
        results["not_disqualified"] = (
            HardFactorResult.FAIL if status in ("do_not_contact", "retired")
            else HardFactorResult.PASS
        )

        return results

    # ----- soft factors -----------------------------------------------------

    def _score_position_trajectory(self, candidate: dict, search: dict) -> SoftFactorScore:
        """Has the candidate held progressively responsible roles leading to this position?"""
        weight = SOFT_WEIGHTS["position_trajectory"]
        experience = candidate.get("experience", [])
        if not experience:
            return SoftFactorScore("position_trajectory", weight, 30, 30 * weight,
                                   "No experience history available")

        target_category = _norm(search.get("position_category", "head_of_school"))
        target_seniority = ROLE_SENIORITY.get(target_category, 5)

        # Check progression
        seniority_history = []
        for exp in sorted(experience, key=lambda e: e.get("start_date") or date.min):
            cat = _norm(exp.get("position_category", ""))
            title = _norm(exp.get("title", ""))
            level = ROLE_SENIORITY.get(cat, 0) or ROLE_SENIORITY.get(title, 0)
            if level > 0:
                seniority_history.append(level)

        if not seniority_history:
            return SoftFactorScore("position_trajectory", weight, 40, 40 * weight,
                                   "Could not map roles to seniority levels")

        peak = max(seniority_history)
        current_role = _norm(candidate.get("primary_role", ""))
        current_level = ROLE_SENIORITY.get(current_role, peak)

        # Ideal: current level is target-1 or target (lateral move)
        gap = target_seniority - current_level
        if gap == 0:
            raw = 90  # lateral move, proven at level
            reasoning = "Currently at target level - lateral move with proven track record"
        elif gap == 1:
            raw = 95  # classic step-up
            reasoning = "One level below target - ideal step-up candidate"
        elif gap == -1:
            raw = 70  # step down - unusual but possible
            reasoning = "Currently above target level - possible step-down/lifestyle move"
        elif gap == 2:
            raw = 55  # stretch
            reasoning = "Two levels below target - significant stretch candidate"
        else:
            raw = max(20, 100 - abs(gap) * 25)
            reasoning = f"Gap of {gap} levels from target position"

        # Bonus for progressive history
        is_progressive = all(
            seniority_history[i] <= seniority_history[i + 1]
            for i in range(len(seniority_history) - 1)
        ) if len(seniority_history) > 1 else True
        if is_progressive and len(seniority_history) >= 3:
            raw = min(100, raw + 5)
            reasoning += "; shows clear progressive trajectory"

        return SoftFactorScore("position_trajectory", weight, raw, raw * weight, reasoning)

    def _score_school_type_alignment(self, candidate: dict, search: dict) -> SoftFactorScore:
        """Experience with same school type."""
        weight = SOFT_WEIGHTS["school_type_alignment"]

        candidate_types = set(_norm(t) for t in (candidate.get("school_type_experience") or []) if t)
        # Also gather from experience records
        for exp in candidate.get("experience", []):
            st = _norm(exp.get("school_type", ""))
            if st:
                candidate_types.add(st)

        target_attrs = []
        for search_field, _ in SCHOOL_TYPE_FIELDS:
            val = _norm(search.get(search_field, ""))
            if val and val not in ("none", "unknown", ""):
                target_attrs.append(val)

        if not target_attrs:
            return SoftFactorScore("school_type_alignment", weight, 70, 70 * weight,
                                   "School type details not specified")

        matches = sum(1 for attr in target_attrs if attr in candidate_types)
        raw = (matches / len(target_attrs)) * 100 if target_attrs else 50

        reasoning = f"Matched {matches}/{len(target_attrs)} school type attributes"
        return SoftFactorScore("school_type_alignment", weight, raw, raw * weight, reasoning)

    def _score_enrollment_match(self, candidate: dict, search: dict) -> SoftFactorScore:
        """Has led school of similar or slightly smaller size."""
        weight = SOFT_WEIGHTS["enrollment_match"]
        target_enrollment = search.get("enrollment_total")

        if not target_enrollment:
            return SoftFactorScore("enrollment_match", weight, 60, 60 * weight,
                                   "Target school enrollment unknown")

        # Check enrollment experience range
        raw = _range_contains(
            candidate.get("enrollment_experience_range"), target_enrollment
        )

        # Also check from experience records
        max_enrollment_led = 0
        for exp in candidate.get("experience", []):
            se = exp.get("school_enrollment")
            if se and se > max_enrollment_led:
                max_enrollment_led = se

        if max_enrollment_led > 0:
            ratio = target_enrollment / max(max_enrollment_led, 1)
            if 0.7 <= ratio <= 1.3:
                raw = max(raw, 90)
                reasoning = f"Led school of {max_enrollment_led} vs target {target_enrollment} - excellent match"
            elif 1.3 < ratio <= 1.8:
                raw = max(raw, 70)
                reasoning = f"Led school of {max_enrollment_led} vs target {target_enrollment} - stretch assignment"
            elif ratio < 0.7:
                raw = max(raw, 60)
                reasoning = f"Led school of {max_enrollment_led} vs target {target_enrollment} - overqualified on size"
            else:
                raw = max(raw, 40)
                reasoning = f"Led school of {max_enrollment_led} vs target {target_enrollment} - significant size gap"
        else:
            reasoning = "No enrollment data from past experience"

        return SoftFactorScore("enrollment_match", weight, raw, raw * weight, reasoning)

    def _score_geographic_desirability(self, candidate: dict, search: dict) -> SoftFactorScore:
        """Candidate's preferred regions/states align."""
        weight = SOFT_WEIGHTS["geographic_desirability"]
        school_state = _norm(search.get("school_state", ""))

        pref_states = [_norm(s) for s in (candidate.get("preferred_states") or []) if s]
        pref_regions = [_norm(r) for r in (candidate.get("preferred_regions") or []) if r]
        willing_to_relocate = candidate.get("willing_to_relocate")
        candidate_state = _norm(candidate.get("state", ""))

        if not school_state:
            return SoftFactorScore("geographic_desirability", weight, 60, 60 * weight,
                                   "School state unknown")

        # State-to-region mapping
        REGION_MAP = {
            "ct": "northeast", "me": "northeast", "ma": "northeast", "nh": "northeast",
            "ri": "northeast", "vt": "northeast", "nj": "northeast", "ny": "northeast",
            "pa": "northeast", "de": "mid_atlantic", "md": "mid_atlantic",
            "dc": "mid_atlantic", "va": "mid_atlantic", "wv": "mid_atlantic",
            "al": "southeast", "fl": "southeast", "ga": "southeast", "ky": "southeast",
            "ms": "southeast", "nc": "southeast", "sc": "southeast", "tn": "southeast",
            "il": "midwest", "in": "midwest", "ia": "midwest", "ks": "midwest",
            "mi": "midwest", "mn": "midwest", "mo": "midwest", "ne": "midwest",
            "nd": "midwest", "oh": "midwest", "sd": "midwest", "wi": "midwest",
            "ar": "south", "la": "south", "ok": "south", "tx": "south",
            "az": "west", "co": "west", "id": "west", "mt": "west",
            "nv": "west", "nm": "west", "ut": "west", "wy": "west",
            "ak": "pacific", "ca": "pacific", "hi": "pacific", "or": "pacific",
            "wa": "pacific",
        }
        school_region = REGION_MAP.get(school_state, "")

        raw = 40.0  # base
        reasons = []

        if school_state in pref_states:
            raw = 100.0
            reasons.append(f"School state ({school_state.upper()}) is in preferred states")
        elif school_region and school_region in pref_regions:
            raw = 85.0
            reasons.append(f"School region ({school_region}) is in preferred regions")
        elif candidate_state == school_state:
            raw = 90.0
            reasons.append("Already lives in the same state")
        elif willing_to_relocate is True:
            raw = 65.0
            reasons.append("Willing to relocate")
        elif willing_to_relocate is None and not pref_states and not pref_regions:
            raw = 50.0
            reasons.append("No geographic preferences specified")
        else:
            raw = 25.0
            reasons.append("School location outside candidate preferences")

        reasoning = "; ".join(reasons) if reasons else "Geographic alignment assessment"
        return SoftFactorScore("geographic_desirability", weight, raw, raw * weight, reasoning)

    def _score_cultural_mission_fit(self, candidate: dict, search: dict) -> SoftFactorScore:
        """Tags overlap: progressive/traditional, faith-based, etc."""
        weight = SOFT_WEIGHTS["cultural_mission_fit"]

        candidate_tags = (candidate.get("cultural_fit_tags") or []) + (candidate.get("tags") or [])
        school_tags = search.get("school_tags") or []

        if not candidate_tags and not school_tags:
            return SoftFactorScore("cultural_mission_fit", weight, 50, 50 * weight,
                                   "Insufficient cultural/mission data for both")

        raw = _tag_overlap(candidate_tags, school_tags)

        # Check religious alignment specifically
        school_religious = _norm(search.get("religious_affiliation", ""))
        if school_religious and school_religious not in ("nonsectarian", "none", ""):
            if school_religious in [_norm(t) for t in candidate_tags]:
                raw = min(100, raw + 20)
            else:
                # Not a guaranteed mismatch, but note it
                raw = max(raw - 10, 0)

        if raw == 0 and (candidate_tags or school_tags):
            raw = 30  # some data exists but no overlap

        reasoning = f"Cultural/mission tag overlap: {raw:.0f}%"
        return SoftFactorScore("cultural_mission_fit", weight, raw, raw * weight, reasoning)

    def _score_financial_acumen(self, candidate: dict, search: dict) -> SoftFactorScore:
        """Experience with budgets and endowments of similar scale."""
        weight = SOFT_WEIGHTS["financial_acumen"]

        target_budget = search.get("operating_budget")
        target_endowment = search.get("endowment_size")

        budget_score = _range_contains(candidate.get("budget_experience_range"), target_budget)
        if target_budget is None:
            budget_score = 50.0

        # Check specializations for financial keywords
        specs = [_norm(s) for s in (candidate.get("specializations") or [])]
        financial_specs = {"fundraising", "financial_management", "endowment", "budgeting",
                          "finance", "capital_campaign", "development"}
        has_financial_spec = bool(set(specs) & financial_specs)

        raw = budget_score
        if has_financial_spec:
            raw = min(100, raw + 15)

        reasoning = f"Budget experience alignment: {budget_score:.0f}%"
        if has_financial_spec:
            reasoning += "; has financial specialization"

        return SoftFactorScore("financial_acumen", weight, raw, raw * weight, reasoning)

    def _score_specialization_match(self, candidate: dict, search: dict) -> SoftFactorScore:
        """Candidate's specializations match school's needs."""
        weight = SOFT_WEIGHTS["specialization_match"]

        candidate_specs = candidate.get("specializations") or []
        # Search needs from preferred_backgrounds and ideal_candidate_profile
        search_needs = search.get("preferred_backgrounds") or []
        search_tags = search.get("school_tags") or []
        # Combine search needs
        all_needs = search_needs + search_tags

        raw = _tag_overlap(candidate_specs, all_needs)
        if raw == 0 and candidate_specs:
            raw = 35  # candidate has specializations, just no overlap data

        reasoning = f"Specialization overlap: {raw:.0f}%"
        return SoftFactorScore("specialization_match", weight, raw, raw * weight, reasoning)

    def _score_board_relationship(self, candidate: dict, search: dict) -> SoftFactorScore:
        """Has worked with boards of similar composition."""
        weight = SOFT_WEIGHTS["board_relationship_experience"]

        # Infer from seniority - HOS/president roles always work with boards
        current_role = _norm(candidate.get("primary_role", ""))
        senior_roles = {"head_of_school", "president", "interim_head", "associate_head",
                       "assistant_head", "division_head", "cfao"}

        has_board_exp = current_role in senior_roles
        if not has_board_exp:
            for exp in candidate.get("experience", []):
                cat = _norm(exp.get("position_category", ""))
                if cat in senior_roles:
                    has_board_exp = True
                    break

        # Check specializations
        specs = [_norm(s) for s in (candidate.get("specializations") or [])]
        board_specs = {"board_relations", "governance", "board_development", "trustee_relations"}
        has_board_spec = bool(set(specs) & board_specs)

        if has_board_exp and has_board_spec:
            raw = 95.0
            reasoning = "Senior leadership experience with board-specific expertise"
        elif has_board_exp:
            raw = 75.0
            reasoning = "Senior leadership role implies board interaction experience"
        elif has_board_spec:
            raw = 65.0
            reasoning = "Has board-related specializations"
        else:
            raw = 30.0
            reasoning = "No evidence of board relationship experience"

        return SoftFactorScore("board_relationship_experience", weight, raw, raw * weight, reasoning)

    def _score_tenure_patterns(self, candidate: dict, search: dict) -> SoftFactorScore:
        """Healthy tenure lengths (3-7 years typical)."""
        weight = SOFT_WEIGHTS["tenure_patterns"]
        experience = candidate.get("experience", [])

        if len(experience) < 2:
            return SoftFactorScore("tenure_patterns", weight, 60, 60 * weight,
                                   "Insufficient experience history to assess tenure patterns")

        tenures = []
        for exp in experience:
            start = exp.get("start_date")
            end = exp.get("end_date") or date.today()
            if start:
                years = _years_between(start, end)
                if years is not None:
                    tenures.append(years)

        if not tenures:
            return SoftFactorScore("tenure_patterns", weight, 50, 50 * weight,
                                   "No date data in experience records")

        avg_tenure = sum(tenures) / len(tenures)
        short_stints = sum(1 for t in tenures if t < 2)
        total_stints = len(tenures)

        if 3.0 <= avg_tenure <= 7.0 and short_stints <= 1:
            raw = 90.0
            reasoning = f"Avg tenure {avg_tenure:.1f}y - ideal pattern"
        elif 2.5 <= avg_tenure <= 9.0:
            raw = 70.0
            reasoning = f"Avg tenure {avg_tenure:.1f}y - acceptable"
        elif avg_tenure < 2.5:
            hopper_ratio = short_stints / max(total_stints, 1)
            raw = max(20, 60 - hopper_ratio * 50)
            reasoning = f"Avg tenure {avg_tenure:.1f}y with {short_stints} short stints - potential job-hopper"
        else:
            raw = 65.0
            reasoning = f"Avg tenure {avg_tenure:.1f}y - very long tenures, may indicate limited breadth"

        return SoftFactorScore("tenure_patterns", weight, raw, raw * weight, reasoning)

    def _score_availability_timing(self, candidate: dict, search: dict) -> SoftFactorScore:
        """Available when the school needs someone."""
        weight = SOFT_WEIGHTS["availability_timing"]
        target_start = search.get("target_start_date")
        availability = candidate.get("availability_date")
        urgency = _norm(search.get("search_urgency", "standard"))

        if not target_start:
            return SoftFactorScore("availability_timing", weight, 60, 60 * weight,
                                   "No target start date specified")

        if availability:
            diff_days = (target_start - availability).days if isinstance(target_start, date) and isinstance(availability, date) else 0
            if diff_days >= 0:
                # Available before or on target
                if diff_days <= 90:
                    raw = 95.0
                    reasoning = "Available within target window"
                else:
                    raw = 75.0
                    reasoning = f"Available {diff_days} days before target - early availability"
            else:
                # Available after target
                late_days = abs(diff_days)
                if late_days <= 30:
                    raw = 80.0
                    reasoning = f"Available {late_days} days after target - manageable delay"
                elif late_days <= 90:
                    raw = 55.0
                    reasoning = f"Available {late_days} days after target - may cause gap"
                else:
                    raw = 25.0
                    reasoning = f"Available {late_days} days after target - significant delay"
        else:
            status = _norm(candidate.get("candidate_status", ""))
            if status == "active":
                raw = 70.0
                reasoning = "Actively looking, no specific date set"
            elif status == "passive":
                raw = 50.0
                reasoning = "Passive candidate, availability uncertain"
            else:
                raw = 40.0
                reasoning = "Availability unknown"

        if urgency == "immediate" and raw < 70:
            raw = max(raw - 10, 0)
            reasoning += "; urgent search penalizes uncertain timing"

        return SoftFactorScore("availability_timing", weight, raw, raw * weight, reasoning)

    # ----- bonuses & penalties ----------------------------------------------

    def _compute_bonuses(self, candidate: dict, search: dict) -> list[dict]:
        bonuses = []

        # +5 if placed by Knock before
        if candidate.get("knock_placement_count", 0) > 0:
            bonuses.append({
                "label": "Previously placed by Knock",
                "points": 5,
                "reasoning": f"Placed {candidate['knock_placement_count']} time(s) - proven relationship"
            })

        # +3 if referred
        source_connection = candidate.get("source_connection") or ""
        if source_connection:
            bonuses.append({
                "label": "Network referral",
                "points": 3,
                "reasoning": f"Referred by {source_connection}"
            })

        # +5 if specific regional/community connection
        candidate_state = _norm(candidate.get("state", ""))
        school_state = _norm(search.get("school_state", ""))
        if candidate_state and school_state and candidate_state == school_state:
            # Check if they have deeper community ties (current school in same state)
            current_school = candidate.get("current_school_id")
            if current_school:
                bonuses.append({
                    "label": "Regional/community connection",
                    "points": 5,
                    "reasoning": f"Currently working in the same state ({school_state.upper()})"
                })

        # -10 if rejected by similar school recently
        if candidate.get("recent_rejections", 0) > 0:
            bonuses.append({
                "label": "Recent rejection by similar school",
                "points": -10,
                "reasoning": f"{candidate['recent_rejections']} rejection(s) in last 12 months"
            })

        return bonuses

    # ----- main scoring method ----------------------------------------------

    async def score(self, candidate_id: str, search_id: str) -> MatchReport:
        """Score a single candidate against a single search. Returns a MatchReport."""

        candidate = await self._load_candidate(candidate_id)
        search = await self._load_search(search_id)

        report = MatchReport(
            candidate_id=candidate_id,
            search_id=search_id,
            school_id=str(search.get("school_id", "")),
            candidate_name=candidate.get("full_name", "Unknown"),
            school_name=search.get("school_name", "Unknown"),
            position_title=search.get("position_title", "Unknown"),
        )

        # 1. Hard factors
        report.hard_factors = self._check_hard_factors(candidate, search)
        report.hard_pass = all(v == HardFactorResult.PASS for v in report.hard_factors.values())

        if not report.hard_pass:
            report.composite_score = 0.0
            report.tier = "disqualified"
            failed = [k for k, v in report.hard_factors.items() if v == HardFactorResult.FAIL]
            report.summary = f"Disqualified - failed hard factors: {', '.join(failed)}"
            return report

        # 2. Soft factors
        scorers = [
            self._score_position_trajectory,
            self._score_school_type_alignment,
            self._score_enrollment_match,
            self._score_geographic_desirability,
            self._score_cultural_mission_fit,
            self._score_financial_acumen,
            self._score_specialization_match,
            self._score_board_relationship,
            self._score_tenure_patterns,
            self._score_availability_timing,
        ]
        for scorer_fn in scorers:
            sf = scorer_fn(candidate, search)
            report.soft_factors.append(sf)

        report.base_score = sum(sf.weighted_score for sf in report.soft_factors)

        # 3. Bonuses
        report.bonuses = self._compute_bonuses(candidate, search)
        report.bonus_total = sum(b["points"] for b in report.bonuses)

        # 4. Composite
        report.composite_score = max(0, min(100, report.base_score + report.bonus_total))
        report.tier = _tier_label(report.composite_score)

        # 5. Summary
        top_strengths = sorted(report.soft_factors, key=lambda s: s.raw_score, reverse=True)[:3]
        strengths_text = ", ".join(s.name.replace("_", " ") for s in top_strengths)
        report.summary = (
            f"{report.tier.capitalize()} match ({report.composite_score:.1f}/100). "
            f"Top strengths: {strengths_text}."
        )
        if report.bonuses:
            bonus_labels = [b["label"] for b in report.bonuses if b["points"] > 0]
            if bonus_labels:
                report.summary += f" Bonuses: {', '.join(bonus_labels)}."

        return report

    async def find_top_candidates(
        self, search_id: str, limit: int = 20, min_score: float = 0
    ) -> list[MatchReport]:
        """Find and rank the top N candidates for a given search."""
        async with self.pool.acquire() as conn:
            # Get candidate pool: active/passive candidates not already in this search
            rows = await conn.fetch(
                """
                SELECT id FROM people
                WHERE candidate_status IN ('active', 'passive', 'not_looking')
                AND id NOT IN (
                    SELECT person_id FROM search_candidates WHERE search_id = $1
                )
                ORDER BY knock_rating DESC NULLS LAST
                LIMIT 500
                """,
                search_id,
            )

        results: list[MatchReport] = []
        for row in rows:
            try:
                report = await self.score(str(row["id"]), search_id)
                if report.composite_score >= min_score:
                    results.append(report)
            except Exception:
                continue  # skip candidates with data issues

        results.sort(key=lambda r: r.composite_score, reverse=True)
        return results[:limit]
