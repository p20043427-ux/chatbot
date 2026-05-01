"""
제약 조건 검증 모듈.

Hard Constraint  : 위반 시 즉시 배정 불가 (bool 반환)
Soft Constraint  : 페널티 점수 계산 (float 반환, 낮을수록 좋음)

설계 원칙:
  - 모든 검사는 순수 함수 (side-effect 없음)
  - ConstraintChecker 가 규칙(ScheduleRules)을 보유하고 메서드로 노출
  - 이유(reason) 를 함께 반환해 UI 에서 위반 내용 표시 가능
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import (
    FixedSchedule,
    Nurse,
    Schedule,
    ScheduleEntry,
    ScheduleRules,
    ShiftType,
    SkillLevel,
)

SHIFT_END_HOUR: Dict[ShiftType, int] = {
    ShiftType.DAY: 15,
    ShiftType.EVENING: 23,
    ShiftType.NIGHT: 7,   # 다음날 07시
}

SHIFT_START_HOUR: Dict[ShiftType, int] = {
    ShiftType.DAY: 7,
    ShiftType.EVENING: 15,
    ShiftType.NIGHT: 23,
}


@dataclass
class ViolationReport:
    """단일 제약 위반 기록."""

    nurse_id: str
    date: datetime.date
    constraint: str
    reason: str
    is_hard: bool


@dataclass
class ConstraintCheckResult:
    """전체 검증 결과."""

    is_feasible: bool = True                       # Hard constraint 위반 없음
    violations: List[ViolationReport] = field(default_factory=list)
    soft_penalty: float = 0.0

    def add_hard(self, nurse_id: str, date: datetime.date, constraint: str, reason: str) -> None:
        self.violations.append(
            ViolationReport(nurse_id, date, constraint, reason, is_hard=True)
        )
        self.is_feasible = False

    def add_soft(self, nurse_id: str, date: datetime.date, constraint: str, reason: str, penalty: float = 1.0) -> None:
        self.violations.append(
            ViolationReport(nurse_id, date, constraint, reason, is_hard=False)
        )
        self.soft_penalty += penalty


class ConstraintChecker:
    """
    규칙(rules)을 참조해 근무 배정 가능 여부와 전체 스케줄 검증을 수행.

    사용법:
        checker = ConstraintChecker(rules)

        # 단일 배정 가능 여부 (Greedy 에서 호출)
        ok, reason = checker.can_assign(nurse, date, shift, history)

        # 전체 스케줄 검증 (Evaluator 에서 호출)
        result = checker.validate_schedule(schedule, nurses, dates)
    """

    def __init__(self, rules: ScheduleRules) -> None:
        self.rules = rules

    # ──────────────────────────────────────────
    # 단일 배정 가능 여부 (Hard Constraints)
    # ──────────────────────────────────────────

    def can_assign(
        self,
        nurse: Nurse,
        date: datetime.date,
        shift: ShiftType,
        history: Dict[datetime.date, ShiftType],
        fixed_dates: frozenset = frozenset(),
    ) -> Tuple[bool, str]:
        """
        특정 날짜에 해당 간호사에게 shift 를 배정할 수 있는지 확인.

        Args:
            nurse:       대상 간호사
            date:        배정 날짜
            shift:       배정하려는 ShiftType
            history:     {date: ShiftType} — 이미 배정된 이력
            fixed_dates: 고정 일정으로 막힌 날짜 집합

        Returns:
            (가능 여부, 위반 이유 문자열)
        """
        if shift == ShiftType.OFF:
            return True, ""

        # 1. 고정 일정 (연차/병가 등)
        if date in fixed_dates:
            return False, f"{date}: 고정 일정(연차·병가·교육)으로 배정 불가"

        # 2. 가능 근무 유형 체크
        if shift not in nurse.allowed_shifts:
            return False, f"{nurse.name}: {shift.value} 근무 불가 (allowed_shifts 미포함)"

        # 3. Night → Day/Evening 전환 금지 (Night 후 최소 휴식)
        prev_date = date - datetime.timedelta(days=1)
        prev_shift = history.get(prev_date)
        if prev_shift == ShiftType.NIGHT:
            if self.rules.night_rest_required and shift != ShiftType.NIGHT:
                return False, f"{date}: Night 직후 {shift.value} 배정 금지 (필수 휴식)"
            if not self.rules.night_rest_required:
                # 최소 휴식 시간 검사
                rest = self._rest_hours(ShiftType.NIGHT, shift)
                if rest < self.rules.min_rest_hours_between_shifts:
                    return False, (
                        f"{date}: Night → {shift.value} 전환 시 휴식 {rest}h "
                        f"< 최소 {self.rules.min_rest_hours_between_shifts}h"
                    )

        # 4. Evening → Night 전환 시 휴식 시간
        if prev_shift == ShiftType.EVENING and shift == ShiftType.NIGHT:
            rest = self._rest_hours(ShiftType.EVENING, ShiftType.NIGHT)
            if rest < self.rules.min_rest_hours_between_shifts:
                return False, (
                    f"{date}: Evening → Night 전환 시 휴식 {rest}h "
                    f"< 최소 {self.rules.min_rest_hours_between_shifts}h"
                )

        # 5. 최대 연속 근무일 초과
        consecutive = self._consecutive_work_days(date, history)
        if consecutive >= self.rules.max_consecutive_work_days:
            return False, (
                f"{date}: 연속 근무 {consecutive}일 → 최대 {self.rules.max_consecutive_work_days}일 초과"
            )

        # 6. 최대 연속 Night 초과
        if shift == ShiftType.NIGHT:
            consec_nights = self._consecutive_nights(date, history)
            if consec_nights >= self.rules.max_consecutive_nights:
                return False, (
                    f"{date}: 연속 Night {consec_nights}회 → 최대 {self.rules.max_consecutive_nights}회 초과"
                )

        return True, ""

    # ──────────────────────────────────────────
    # 전체 스케줄 유효성 검증
    # ──────────────────────────────────────────

    def validate_schedule(
        self,
        schedule: Schedule,
        nurses: List[Nurse],
        dates: List[datetime.date],
        fixed_schedules: Optional[List[FixedSchedule]] = None,
    ) -> ConstraintCheckResult:
        """완성된 스케줄 전체를 검증해 위반 목록과 soft penalty 반환."""
        result = ConstraintCheckResult()
        nurse_map = {n.id: n for n in nurses}
        matrix = schedule.as_matrix(nurses)

        fixed_map: Dict[Tuple[str, datetime.date], str] = {}
        if fixed_schedules:
            for fs in fixed_schedules:
                fixed_map[(fs.nurse_id, fs.date)] = fs.schedule_type.value

        # ── Per-nurse 검증
        for nurse in nurses:
            hist = matrix[nurse.id]
            sorted_dates = sorted(hist.keys())

            for i, d in enumerate(sorted_dates):
                shift = hist[d]
                if shift == ShiftType.OFF:
                    continue

                # Night → non-Night (hard)
                prev = hist.get(d - datetime.timedelta(days=1))
                if prev == ShiftType.NIGHT and shift != ShiftType.NIGHT:
                    if self.rules.night_rest_required:
                        result.add_hard(
                            nurse.id, d,
                            "NIGHT_REST",
                            f"{nurse.name}: Night 직후 {shift.value} 배정",
                        )

                # 최대 연속 근무
                consec = self._consecutive_work_days(d, hist)
                if consec > self.rules.max_consecutive_work_days:
                    result.add_hard(
                        nurse.id, d,
                        "MAX_CONSECUTIVE",
                        f"{nurse.name}: {d} 연속 근무 {consec}일 초과",
                    )

                # 연속 Night
                if shift == ShiftType.NIGHT:
                    cn = self._consecutive_nights(d, hist)
                    if cn > self.rules.max_consecutive_nights:
                        result.add_hard(
                            nurse.id, d,
                            "MAX_CONSEC_NIGHTS",
                            f"{nurse.name}: {d} 연속 Night {cn}회 초과",
                        )

        # ── Per-date 검증 (인원 요건)
        for d in dates:
            entries = schedule.get_date_entries(d)
            for shift_type in [ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT]:
                req = self.rules.shift_requirements.get(shift_type)
                if req is None:
                    continue
                assigned = [e for e in entries if e.shift == shift_type]
                if len(assigned) < req.min_nurses:
                    result.add_hard(
                        "", d,
                        "MIN_NURSES",
                        f"{d} {shift_type.value}: 배정 {len(assigned)}명 < 최소 {req.min_nurses}명",
                    )
                senior_count = sum(
                    1 for e in assigned
                    if nurse_map.get(e.nurse_id, Nurse(
                        id="", name="", skill_level=SkillLevel.NEW,
                        ward_qualifications=[]
                    )).skill_level == SkillLevel.SENIOR
                )
                if senior_count < req.min_senior_nurses:
                    result.add_hard(
                        "", d,
                        "MIN_SENIOR",
                        f"{d} {shift_type.value}: 숙련 {senior_count}명 < 최소 {req.min_senior_nurses}명",
                    )

        return result

    # ──────────────────────────────────────────
    # Soft Constraint 페널티 (Optimizer 에서 사용)
    # ──────────────────────────────────────────

    def night_distribution_penalty(
        self, nurse_ids: List[str], matrix: Dict[str, Dict[datetime.date, ShiftType]]
    ) -> float:
        """야간 근무 횟수 편차 페널티 (표준편차 기반)."""
        import statistics
        counts = [
            sum(1 for s in matrix[nid].values() if s == ShiftType.NIGHT)
            for nid in nurse_ids
        ]
        if len(counts) < 2:
            return 0.0
        return statistics.stdev(counts) * self.rules.fairness_weight_night

    def weekend_distribution_penalty(
        self, nurse_ids: List[str], matrix: Dict[str, Dict[datetime.date, ShiftType]]
    ) -> float:
        """주말 근무 횟수 편차 페널티."""
        import statistics
        counts = [
            sum(
                1 for d, s in matrix[nid].items()
                if d.weekday() >= 5 and s != ShiftType.OFF
            )
            for nid in nurse_ids
        ]
        if len(counts) < 2:
            return 0.0
        return statistics.stdev(counts) * self.rules.fairness_weight_weekend

    def preference_penalty(
        self,
        nurse: Nurse,
        matrix: Dict[datetime.date, ShiftType],
    ) -> float:
        """선호 미반영 페널티."""
        penalty = 0.0
        for d, shift in matrix.items():
            if shift == ShiftType.OFF:
                continue
            if shift in nurse.preference.avoid_shifts:
                penalty += 2.0
            if nurse.preference.preferred_shifts and shift not in nurse.preference.preferred_shifts:
                penalty += 0.5
            if d.weekday() in nurse.preference.preferred_days_off and shift != ShiftType.OFF:
                penalty += 1.0
        return penalty

    def fatigue_penalty(
        self, nurse_id: str, matrix: Dict[str, Dict[datetime.date, ShiftType]]
    ) -> float:
        """피로도 페널티: 연속 근무·야간 집중 보정."""
        hist = matrix[nurse_id]
        penalty = 0.0
        sorted_dates = sorted(hist.keys())
        run = 0
        night_run = 0
        for d in sorted_dates:
            shift = hist[d]
            if shift == ShiftType.OFF:
                run = 0
                night_run = 0
            else:
                run += 1
                if shift == ShiftType.NIGHT:
                    night_run += 1
                    penalty += night_run * 0.5  # 연속 야간일수록 가중
                else:
                    night_run = 0
                if run > 3:
                    penalty += (run - 3) * 1.0  # 4일 이상 연속 근무 페널티
        return penalty

    # ──────────────────────────────────────────
    # 내부 유틸리티
    # ──────────────────────────────────────────

    @staticmethod
    def _rest_hours(from_shift: ShiftType, to_shift: ShiftType) -> int:
        """두 근무 사이 휴식 시간 (단순 계산, 날짜 무시)."""
        end = SHIFT_END_HOUR[from_shift]
        start = SHIFT_START_HOUR[to_shift]
        diff = start - end
        if diff < 0:
            diff += 24
        return diff

    @staticmethod
    def _consecutive_work_days(date: datetime.date, history: Dict[datetime.date, ShiftType]) -> int:
        """date 직전까지 연속 근무일 수 (date 포함하지 않음)."""
        count = 0
        d = date - datetime.timedelta(days=1)
        while True:
            shift = history.get(d)
            if shift is None or shift == ShiftType.OFF:
                break
            count += 1
            d -= datetime.timedelta(days=1)
        return count

    @staticmethod
    def _consecutive_nights(date: datetime.date, history: Dict[datetime.date, ShiftType]) -> int:
        """date 직전까지 연속 Night 수 (date 포함하지 않음)."""
        count = 0
        d = date - datetime.timedelta(days=1)
        while True:
            shift = history.get(d)
            if shift != ShiftType.NIGHT:
                break
            count += 1
            d -= datetime.timedelta(days=1)
        return count
