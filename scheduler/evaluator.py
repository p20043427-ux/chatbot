"""
근무표 평가 모듈.

근무표 품질을 수치화해 UI 대시보드와 관리자 요약 리포트에 제공.

평가 항목:
  - Hard Constraint 위반 여부 및 건수
  - 공정성 점수 (야간·주말·공휴일 분포 편차)
  - 피로도 점수 (연속 근무·야간 집중도)
  - 선호 반영률
  - 인력 충족률
"""

from __future__ import annotations

import datetime
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import holidays

from .constraints import ConstraintChecker, ConstraintCheckResult
from .models import (
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
    day_shifts: int = 0
    evening_shifts: int = 0
    night_shifts: int = 0
    weekend_shifts: int = 0
    holiday_shifts: int = 0
    off_days: int = 0
    max_consecutive_work: int = 0
    preference_satisfied: int = 0
    preference_total: int = 0
    fatigue_score: float = 0.0

    @property
    def preference_rate(self) -> float:
        if self.preference_total == 0:
            return 1.0
        return self.preference_satisfied / self.preference_total


@dataclass
class EvaluationResult:
    """전체 평가 결과."""

    # Hard constraint
    constraint_result: ConstraintCheckResult = field(
        default_factory=ConstraintCheckResult
    )

    # 공정성 (낮을수록 공평)
    night_fairness_score: float = 0.0     # 야간 횟수 표준편차
    weekend_fairness_score: float = 0.0   # 주말 횟수 표준편차
    holiday_fairness_score: float = 0.0   # 공휴일 횟수 표준편차

    # 피로도 (낮을수록 좋음)
    average_fatigue_score: float = 0.0

    # 선호 반영률 (높을수록 좋음, 0~1)
    preference_satisfaction_rate: float = 0.0

    # 인력 충족률 (1.0 = 완전 충족)
    staffing_coverage_rate: float = 0.0

    # 개인별 통계
    nurse_stats: List[NurseStats] = field(default_factory=list)

    # 종합 점수 (0~100, 높을수록 좋음)
    overall_score: float = 0.0

    # Shift 별 일자 충족 여부
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
    """
    스케줄 품질 평가기.

    사용법:
        evaluator = ScheduleEvaluator(config)
        result = evaluator.evaluate(schedule)
        print(result.summary())
    """

    def __init__(self, config: ScheduleConfig) -> None:
        self.config = config
        self.checker = ConstraintChecker(config.rules)
        self._dates = self._build_dates()
        self._kr_holidays = self._load_holidays()

    def evaluate(self, schedule: Schedule) -> EvaluationResult:
        """스케줄 전체 평가."""
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
        nurse_map = self.config.nurse_map

        # 2. 개인별 통계
        nurse_stats_map: Dict[str, NurseStats] = {}
        for nurse in self.config.nurses:
            stats = NurseStats(nurse_id=nurse.id, nurse_name=nurse.name)
            hist = matrix[nurse.id]

            consec = 0
            max_consec = 0

            for d in sorted(hist.keys()):
                shift = hist[d]
                if shift == ShiftType.OFF:
                    consec = 0
                    stats.off_days += 1
                    continue

                stats.total_work_days += 1
                consec += 1
                max_consec = max(max_consec, consec)

                if shift == ShiftType.DAY:
                    stats.day_shifts += 1
                elif shift == ShiftType.EVENING:
                    stats.evening_shifts += 1
                elif shift == ShiftType.NIGHT:
                    stats.night_shifts += 1

                if d.weekday() >= 5:
                    stats.weekend_shifts += 1
                if d in self._kr_holidays:
                    stats.holiday_shifts += 1

                # 선호 반영 체크
                if nurse.preference.preferred_shifts:
                    stats.preference_total += 1
                    if shift in nurse.preference.preferred_shifts:
                        stats.preference_satisfied += 1
                if d.weekday() in nurse.preference.preferred_days_off:
                    stats.preference_total += 1
                    # OFF 인 경우 이미 continue 처리됨 — 이 코드에선 미도달
                    # 즉 근무인데 선호 OFF 요일 → 미반영

            stats.max_consecutive_work = max_consec
            stats.fatigue_score = self.checker.fatigue_penalty(nurse.id, matrix)
            nurse_stats_map[nurse.id] = stats

        result.nurse_stats = list(nurse_stats_map.values())

        # 3. 공정성 점수 (표준편차)
        night_counts = [s.night_shifts for s in result.nurse_stats]
        weekend_counts = [s.weekend_shifts for s in result.nurse_stats]
        holiday_counts = [s.holiday_shifts for s in result.nurse_stats]

        result.night_fairness_score = statistics.stdev(night_counts) if len(night_counts) > 1 else 0.0
        result.weekend_fairness_score = statistics.stdev(weekend_counts) if len(weekend_counts) > 1 else 0.0
        result.holiday_fairness_score = statistics.stdev(holiday_counts) if len(holiday_counts) > 1 else 0.0

        # 4. 피로도 평균
        fatigue_scores = [s.fatigue_score for s in result.nurse_stats]
        result.average_fatigue_score = (
            sum(fatigue_scores) / len(fatigue_scores) if fatigue_scores else 0.0
        )

        # 5. 선호 반영률
        total_pref = sum(s.preference_total for s in result.nurse_stats)
        total_sat = sum(s.preference_satisfied for s in result.nurse_stats)
        result.preference_satisfaction_rate = (
            total_sat / total_pref if total_pref > 0 else 1.0
        )

        # 6. 인력 충족률
        result.daily_coverage, coverage_rate = self._calc_coverage(schedule)
        result.staffing_coverage_rate = coverage_rate

        # 7. 종합 점수 (100점 만점)
        result.overall_score = self._calc_overall_score(result)

        return result

    def get_night_distribution(
        self, schedule: Schedule
    ) -> Dict[str, int]:
        """간호사별 야간 근무 횟수 딕셔너리."""
        matrix = schedule.as_matrix(self.config.nurses)
        return {
            nurse.name: sum(
                1 for s in matrix[nurse.id].values() if s == ShiftType.NIGHT
            )
            for nurse in self.config.nurses
        }

    def get_weekend_distribution(
        self, schedule: Schedule
    ) -> Dict[str, int]:
        """간호사별 주말 근무 횟수 딕셔너리."""
        matrix = schedule.as_matrix(self.config.nurses)
        return {
            nurse.name: sum(
                1 for d, s in matrix[nurse.id].items()
                if d.weekday() >= 5 and s != ShiftType.OFF
            )
            for nurse in self.config.nurses
        }

    def get_fatigue_matrix(
        self, schedule: Schedule
    ) -> Dict[str, Dict[datetime.date, float]]:
        """
        피로도 heatmap 용 데이터.
        {nurse_name: {date: fatigue_value}} 형태.
        """
        matrix = schedule.as_matrix(self.config.nurses)
        result: Dict[str, Dict[datetime.date, float]] = {}

        for nurse in self.config.nurses:
            hist = matrix[nurse.id]
            fatigue_map: Dict[datetime.date, float] = {}
            run = 0
            night_run = 0
            for d in sorted(hist.keys()):
                shift = hist[d]
                if shift == ShiftType.OFF:
                    run = 0
                    night_run = 0
                    fatigue_map[d] = 0.0
                else:
                    run += 1
                    if shift == ShiftType.NIGHT:
                        night_run += 1
                    else:
                        night_run = 0
                    # 피로도 = 연속 근무 + 야간 집중 가중치
                    fatigue_map[d] = run + night_run * 1.5
            result[nurse.name] = fatigue_map

        return result

    # ──────────────────────────────────────────
    # 내부 계산
    # ──────────────────────────────────────────

    def _calc_coverage(
        self, schedule: Schedule
    ) -> tuple:
        """일자별 Shift 인원 충족 여부."""
        daily: Dict[str, Dict[str, int]] = {}  # date_str → {shift: count}
        required_slots = 0
        filled_slots = 0

        for date in self._dates:
            entries = schedule.get_date_entries(date)
            date_str = date.isoformat()
            daily[date_str] = {s.value: 0 for s in ShiftType if s != ShiftType.OFF}

            for entry in entries:
                if entry.shift != ShiftType.OFF:
                    daily[date_str][entry.shift.value] = (
                        daily[date_str].get(entry.shift.value, 0) + 1
                    )

            for shift_type, req in self.config.rules.shift_requirements.items():
                required_slots += req.min_nurses
                assigned = daily[date_str].get(shift_type.value, 0)
                filled_slots += min(assigned, req.min_nurses)

        rate = filled_slots / required_slots if required_slots > 0 else 1.0
        return daily, rate

    def _calc_overall_score(self, result: EvaluationResult) -> float:
        """
        종합 점수 (0~100).

        가중치:
          - Hard 위반 없음   : 40점
          - 인력 충족률      : 20점
          - 공정성            : 20점
          - 선호 반영률      : 10점
          - 피로도            : 10점
        """
        score = 0.0

        # Hard 위반
        hard_violations = sum(
            1 for v in result.constraint_result.violations if v.is_hard
        )
        score += max(0, 40 - hard_violations * 5)

        # 인력 충족률
        score += result.staffing_coverage_rate * 20

        # 공정성 (편차가 0에 가까울수록 만점)
        fairness = (
            result.night_fairness_score * self.config.rules.fairness_weight_night
            + result.weekend_fairness_score * self.config.rules.fairness_weight_weekend
        ) / 2
        score += max(0, 20 - fairness * 5)

        # 선호 반영률
        score += result.preference_satisfaction_rate * 10

        # 피로도 (낮을수록 좋음)
        fatigue_norm = min(result.average_fatigue_score / 50, 1.0)
        score += (1 - fatigue_norm) * 10

        return min(score, 100.0)

    def _build_dates(self) -> List[datetime.date]:
        import calendar
        _, last_day = calendar.monthrange(self.config.year, self.config.month)
        return [
            datetime.date(self.config.year, self.config.month, day)
            for day in range(1, last_day + 1)
        ]

    def _load_holidays(self):
        try:
            kr = holidays.country_holidays(
                self.config.country_code, years=self.config.year
            )
            return {d for d in kr if d.month == self.config.month}
        except Exception:
            return set()
