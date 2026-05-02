"""
근무표 평가 모듈.

38종 근무 코드 대응:
  - 근무일수: WORK_SHIFTS 집합 사용
  - 야간 횟수: NIGHT_SHIFTS 집합 사용
  - 공정성/피로도: 확장 코드 포함
"""

from __future__ import annotations

import datetime
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import holidays

from .constraints import ConstraintChecker, ConstraintCheckResult
from .models import (
    NIGHT_SHIFTS,
    OFF_SHIFTS,
    WORK_SHIFTS,
    SHIFT_META,
    Nurse,
    Schedule,
    ScheduleConfig,
    ShiftType,
    SkillLevel,
)


@dataclass
class NurseStats:
    """개인별 근무 통계."""
    nurse_id: str
    nurse_name: str
    total_work_days: int = 0
    # 주요 근무 유형별 카운트
    shift_counts: Dict[str, int] = field(default_factory=dict)
    weekend_shifts: int = 0
    holiday_shifts: int = 0
    off_days: int = 0
    max_consecutive_work: int = 0
    preference_satisfied: int = 0
    preference_total: int = 0
    fatigue_score: float = 0.0

    @property
    def night_shifts(self) -> int:
        return sum(v for k, v in self.shift_counts.items() if k in {s.value for s in NIGHT_SHIFTS})

    @property
    def preference_rate(self) -> float:
        return self.preference_satisfied / self.preference_total if self.preference_total else 1.0


@dataclass
class EvaluationResult:
    """전체 평가 결과."""
    constraint_result: ConstraintCheckResult = field(default_factory=ConstraintCheckResult)
    night_fairness_score: float = 0.0
    weekend_fairness_score: float = 0.0
    holiday_fairness_score: float = 0.0
    average_fatigue_score: float = 0.0
    preference_satisfaction_rate: float = 0.0
    staffing_coverage_rate: float = 0.0
    nurse_stats: List[NurseStats] = field(default_factory=list)
    overall_score: float = 0.0
    daily_coverage: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            "=" * 50,
            "📊 근무표 평가 요약",
            "=" * 50,
            f"종합 점수       : {self.overall_score:.1f} / 100",
            f"Hard 위반 건수  : {sum(1 for v in self.constraint_result.violations if v.is_hard)}",
            f"공정성 (야간)   : {self.night_fairness_score:.2f} (편차, 낮을수록 좋음)",
            f"공정성 (주말)   : {self.weekend_fairness_score:.2f}",
            f"피로도 평균     : {self.average_fatigue_score:.2f}",
            f"선호 반영률     : {self.preference_satisfaction_rate * 100:.1f}%",
            f"인력 충족률     : {self.staffing_coverage_rate * 100:.1f}%",
        ]
        return "\n".join(lines)


class ScheduleEvaluator:
    """스케줄 품질 평가기."""

    def __init__(self, config: ScheduleConfig) -> None:
        self.config = config
        self.checker = ConstraintChecker(config.rules)
        self._dates = self._build_dates()
        self._kr_holidays = self._load_holidays()

    def evaluate(self, schedule: Schedule) -> EvaluationResult:
        result = EvaluationResult()

        # 1. Hard Constraint 검증
        result.constraint_result = self.checker.validate_schedule(
            schedule=schedule,
            nurses=self.config.nurses,
            dates=self._dates,
            fixed_schedules=self.config.fixed_schedules,
        )

        matrix = schedule.as_matrix(self.config.nurses)
        nurse_ids = [n.id for n in self.config.nurses]

        # 2. 개인별 통계
        nurse_stats_list: List[NurseStats] = []
        for nurse in self.config.nurses:
            stats = NurseStats(nurse_id=nurse.id, nurse_name=nurse.name)
            hist = matrix[nurse.id]
            consec = max_consec = 0

            for d in sorted(hist.keys()):
                shift = hist[d]
                code = shift.value
                if shift in OFF_SHIFTS:
                    consec = 0
                    stats.off_days += 1
                else:
                    stats.total_work_days += 1
                    consec += 1
                    max_consec = max(max_consec, consec)
                    stats.shift_counts[code] = stats.shift_counts.get(code, 0) + 1

                if shift in WORK_SHIFTS:
                    if d.weekday() >= 5:
                        stats.weekend_shifts += 1
                    if d in self._kr_holidays:
                        stats.holiday_shifts += 1

                # 선호 반영 체크
                if nurse.preference.preferred_shifts:
                    stats.preference_total += 1
                    if shift in nurse.preference.preferred_shifts:
                        stats.preference_satisfied += 1

            stats.max_consecutive_work = max_consec
            stats.fatigue_score = self.checker.fatigue_penalty(nurse.id, matrix)
            nurse_stats_list.append(stats)

        result.nurse_stats = nurse_stats_list

        # 3. 공정성 점수 (표준편차)
        night_counts   = [s.night_shifts for s in result.nurse_stats]
        weekend_counts = [s.weekend_shifts for s in result.nurse_stats]
        holiday_counts = [s.holiday_shifts for s in result.nurse_stats]

        result.night_fairness_score   = statistics.stdev(night_counts)   if len(night_counts) > 1   else 0.0
        result.weekend_fairness_score = statistics.stdev(weekend_counts) if len(weekend_counts) > 1 else 0.0
        result.holiday_fairness_score = statistics.stdev(holiday_counts) if len(holiday_counts) > 1 else 0.0

        # 4. 피로도 평균
        fatigue_list = [s.fatigue_score for s in result.nurse_stats]
        result.average_fatigue_score = sum(fatigue_list) / len(fatigue_list) if fatigue_list else 0.0

        # 5. 선호 반영률
        total_pref = sum(s.preference_total for s in result.nurse_stats)
        total_sat  = sum(s.preference_satisfied for s in result.nurse_stats)
        result.preference_satisfaction_rate = total_sat / total_pref if total_pref > 0 else 1.0

        # 6. 인력 충족률
        result.daily_coverage, cov_rate = self._calc_coverage(schedule)
        result.staffing_coverage_rate = cov_rate

        # 7. 종합 점수
        result.overall_score = self._calc_overall_score(result)

        return result

    def get_night_distribution(self, schedule: Schedule) -> Dict[str, int]:
        matrix = schedule.as_matrix(self.config.nurses)
        return {
            nurse.name: sum(1 for s in matrix[nurse.id].values() if s in NIGHT_SHIFTS)
            for nurse in self.config.nurses
        }

    def get_weekend_distribution(self, schedule: Schedule) -> Dict[str, int]:
        matrix = schedule.as_matrix(self.config.nurses)
        return {
            nurse.name: sum(
                1 for d, s in matrix[nurse.id].items()
                if d.weekday() >= 5 and s in WORK_SHIFTS
            )
            for nurse in self.config.nurses
        }

    def get_fatigue_matrix(self, schedule: Schedule) -> Dict[str, Dict[datetime.date, float]]:
        """피로도 heatmap 용 {nurse_name: {date: value}}."""
        matrix = schedule.as_matrix(self.config.nurses)
        result: Dict[str, Dict[datetime.date, float]] = {}
        for nurse in self.config.nurses:
            hist = matrix[nurse.id]
            fatigue_map: Dict[datetime.date, float] = {}
            run = night_run = 0
            for d in sorted(hist.keys()):
                shift = hist[d]
                if shift in OFF_SHIFTS:
                    run = night_run = 0
                    fatigue_map[d] = 0.0
                else:
                    run += 1
                    night_run = night_run + 1 if shift in NIGHT_SHIFTS else 0
                    fatigue_map[d] = run + night_run * 1.5
            result[nurse.name] = fatigue_map
        return result

    # ──────────────────────────────────────────
    def _calc_coverage(self, schedule: Schedule) -> tuple:
        daily: Dict[str, Dict[str, int]] = {}
        required_slots = filled_slots = 0
        for date in self._dates:
            entries = schedule.get_date_entries(date)
            date_str = date.isoformat()
            daily[date_str] = {}
            for entry in entries:
                if entry.shift in WORK_SHIFTS:
                    daily[date_str][entry.shift.value] = daily[date_str].get(entry.shift.value, 0) + 1
            for shift_type, req in self.config.rules.shift_requirements.items():
                required_slots += req.min_nurses
                filled_slots += min(daily[date_str].get(shift_type.value, 0), req.min_nurses)
        rate = filled_slots / required_slots if required_slots > 0 else 1.0
        return daily, rate

    def _calc_overall_score(self, result: EvaluationResult) -> float:
        score = 0.0
        hard_violations = sum(1 for v in result.constraint_result.violations if v.is_hard)
        score += max(0, 40 - hard_violations * 5)
        score += result.staffing_coverage_rate * 20
        fairness = (
            result.night_fairness_score * self.config.rules.fairness_weight_night
            + result.weekend_fairness_score * self.config.rules.fairness_weight_weekend
        ) / 2
        score += max(0, 20 - fairness * 5)
        score += result.preference_satisfaction_rate * 10
        fatigue_norm = min(result.average_fatigue_score / 50, 1.0)
        score += (1 - fatigue_norm) * 10
        return min(score, 100.0)

    def _build_dates(self) -> List[datetime.date]:
        import calendar
        _, last_day = calendar.monthrange(self.config.year, self.config.month)
        return [datetime.date(self.config.year, self.config.month, d) for d in range(1, last_day + 1)]

    def _load_holidays(self):
        try:
            kr = holidays.country_holidays(self.config.country_code, years=self.config.year)
            return {d for d in kr if d.month == self.config.month}
        except Exception:
            return set()
