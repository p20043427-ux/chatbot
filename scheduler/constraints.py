"""
제약 조건 검증 모듈.

Hard Constraint  : 위반 시 즉시 배정 불가 (bool 반환)
Soft Constraint  : 페널티 점수 계산 (float, 낮을수록 좋음)

38종 근무 코드를 WORK_SHIFTS / NIGHT_SHIFTS / OFF_SHIFTS 집합으로 분류해
기존 D/E/N 기반 제약 로직을 자연스럽게 확장한다.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import (
    FixedSchedule,
    Nurse,
    NIGHT_SHIFTS,
    OFF_SHIFTS,
    WORK_SHIFTS,
    Schedule,
    ScheduleEntry,
    ScheduleRules,
    ShiftType,
    ShiftMeta,
    SHIFT_META,
    SkillLevel,
    shift_rest_gap,
)


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
    is_feasible: bool = True
    violations: List[ViolationReport] = field(default_factory=list)
    soft_penalty: float = 0.0

    def add_hard(self, nurse_id: str, date: datetime.date, constraint: str, reason: str) -> None:
        self.violations.append(ViolationReport(nurse_id, date, constraint, reason, True))
        self.is_feasible = False

    def add_soft(self, nurse_id: str, date: datetime.date, constraint: str, reason: str, penalty: float = 1.0) -> None:
        self.violations.append(ViolationReport(nurse_id, date, constraint, reason, False))
        self.soft_penalty += penalty


class ConstraintChecker:
    """
    규칙(ScheduleRules)을 참조해 근무 배정 가능 여부와 전체 스케줄 검증 수행.

    변경점 (38종 코드 대응):
      - 야간 판별: ShiftType.NIGHT 단일 비교 → NIGHT_SHIFTS 집합 사용
      - 근무 여부: ShiftType.OFF 비교 → OFF_SHIFTS 집합 사용
      - 교대 간 휴식: SHIFT_META 의 start_h/end_h 기반 정확한 계산
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

        Returns (가능 여부, 위반 이유)
        """
        # 비근무 코드 배정 요청은 항상 허용 (고정 일정 처리용)
        if shift in OFF_SHIFTS:
            return True, ""

        # 1. 고정 일정 (연차/병가 등 선점된 날)
        if date in fixed_dates:
            return False, f"{date}: 고정 일정으로 배정 불가"

        # 2. 가능 근무 유형 체크
        if shift not in nurse.allowed_shifts:
            return False, f"{nurse.name}: {shift.value}({SHIFT_META.get(shift, ShiftMeta('?','',False,False,0,0,''))}.label) 근무 불가"

        prev_date = date - datetime.timedelta(days=1)
        prev_shift = history.get(prev_date)

        # 3. 야간 근무 직후 비야간 배정 금지 (NIGHT_SHIFTS 집합으로 확장 판별)
        if prev_shift and prev_shift in NIGHT_SHIFTS:
            if self.rules.night_rest_required:
                if shift not in NIGHT_SHIFTS:
                    return False, (
                        f"{date}: 야간({prev_shift.value}) 직후 "
                        f"{shift.value} 배정 금지 (필수 휴식)"
                    )
            else:
                # 강제 OFF 불필요 시 최소 휴식 시간만 체크
                rest = shift_rest_gap(prev_shift, shift)
                if rest < self.rules.min_rest_hours_between_shifts:
                    return False, (
                        f"{date}: {prev_shift.value}→{shift.value} 교대 시 "
                        f"휴식 {rest}h < 최소 {self.rules.min_rest_hours_between_shifts}h"
                    )

        # 4. 야간이 아닌 근무 간 최소 휴식 시간 (예: E→N 체크)
        if prev_shift and prev_shift not in NIGHT_SHIFTS and prev_shift in WORK_SHIFTS:
            rest = shift_rest_gap(prev_shift, shift)
            if rest < self.rules.min_rest_hours_between_shifts:
                return False, (
                    f"{date}: {prev_shift.value}→{shift.value} 교대 시 "
                    f"휴식 {rest}h < 최소 {self.rules.min_rest_hours_between_shifts}h"
                )

        # 5. 최대 연속 근무일 초과
        consecutive = self._consecutive_work_days(date, history)
        if consecutive >= self.rules.max_consecutive_work_days:
            return False, (
                f"{date}: 연속 근무 {consecutive}일 → "
                f"최대 {self.rules.max_consecutive_work_days}일 초과"
            )

        # 6. 최대 연속 야간 초과
        if shift in NIGHT_SHIFTS:
            consec_nights = self._consecutive_nights(date, history)
            if consec_nights >= self.rules.max_consecutive_nights:
                return False, (
                    f"{date}: 연속 야간 {consec_nights}회 → "
                    f"최대 {self.rules.max_consecutive_nights}회 초과"
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
        """완성된 스케줄 전체 검증."""
        result = ConstraintCheckResult()
        nurse_map = {n.id: n for n in nurses}
        matrix = schedule.as_matrix(nurses)

        # ── Per-nurse 검증
        for nurse in nurses:
            hist = matrix[nurse.id]
            for d in sorted(hist.keys()):
                shift = hist[d]
                if shift in OFF_SHIFTS:
                    continue

                prev = hist.get(d - datetime.timedelta(days=1))

                # 야간 직후 비야간 (Hard)
                if prev and prev in NIGHT_SHIFTS and shift not in NIGHT_SHIFTS:
                    if self.rules.night_rest_required:
                        result.add_hard(
                            nurse.id, d, "NIGHT_REST",
                            f"{nurse.name}: {prev.value} 직후 {shift.value} 배정",
                        )

                # 최대 연속 근무
                consec = self._consecutive_work_days(d, hist)
                if consec > self.rules.max_consecutive_work_days:
                    result.add_hard(
                        nurse.id, d, "MAX_CONSECUTIVE",
                        f"{nurse.name}: {d} 연속 근무 {consec}일 초과",
                    )

                # 연속 야간
                if shift in NIGHT_SHIFTS:
                    cn = self._consecutive_nights(d, hist)
                    if cn > self.rules.max_consecutive_nights:
                        result.add_hard(
                            nurse.id, d, "MAX_CONSEC_NIGHTS",
                            f"{nurse.name}: {d} 연속 야간 {cn}회 초과",
                        )

        # ── Per-date 인원 요건 검증
        for d in dates:
            entries = schedule.get_date_entries(d)
            for shift_type, req in self.rules.shift_requirements.items():
                assigned = [e for e in entries if e.shift == shift_type]
                if len(assigned) < req.min_nurses:
                    result.add_hard(
                        "", d, "MIN_NURSES",
                        f"{d} {shift_type.value}: 배정 {len(assigned)}명 < 최소 {req.min_nurses}명",
                    )
                senior_count = sum(
                    1 for e in assigned
                    if nurse_map.get(e.nurse_id) and
                    nurse_map[e.nurse_id].skill_level == SkillLevel.SENIOR
                )
                if senior_count < req.min_senior_nurses:
                    result.add_hard(
                        "", d, "MIN_SENIOR",
                        f"{d} {shift_type.value}: 숙련 {senior_count}명 < 최소 {req.min_senior_nurses}명",
                    )

        return result

    # ──────────────────────────────────────────
    # Soft Constraint 페널티
    # ──────────────────────────────────────────

    def night_distribution_penalty(
        self,
        nurse_ids: List[str],
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
    ) -> float:
        """야간 근무 횟수 편차 페널티 (표준편차)."""
        import statistics
        counts = [
            sum(1 for s in matrix[nid].values() if s in NIGHT_SHIFTS)
            for nid in nurse_ids
        ]
        return statistics.stdev(counts) * self.rules.fairness_weight_night if len(counts) > 1 else 0.0

    def weekend_distribution_penalty(
        self,
        nurse_ids: List[str],
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
    ) -> float:
        """주말 근무 횟수 편차 페널티."""
        import statistics
        counts = [
            sum(1 for d, s in matrix[nid].items() if d.weekday() >= 5 and s in WORK_SHIFTS)
            for nid in nurse_ids
        ]
        return statistics.stdev(counts) * self.rules.fairness_weight_weekend if len(counts) > 1 else 0.0

    def preference_penalty(
        self,
        nurse: Nurse,
        matrix: Dict[datetime.date, ShiftType],
    ) -> float:
        """선호 미반영 페널티."""
        penalty = 0.0
        for d, shift in matrix.items():
            if shift in OFF_SHIFTS:
                continue
            if shift in nurse.preference.avoid_shifts:
                penalty += 2.0
            if nurse.preference.preferred_shifts and shift not in nurse.preference.preferred_shifts:
                penalty += 0.5
            if d.weekday() in nurse.preference.preferred_days_off and shift in WORK_SHIFTS:
                penalty += 1.0
        return penalty

    def fatigue_penalty(
        self,
        nurse_id: str,
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
    ) -> float:
        """피로도 페널티: 연속 근무·야간 집중 가중치."""
        hist = matrix[nurse_id]
        penalty = 0.0
        run = night_run = 0
        for d in sorted(hist.keys()):
            shift = hist[d]
            if shift in OFF_SHIFTS:
                run = night_run = 0
            else:
                run += 1
                if shift in NIGHT_SHIFTS:
                    night_run += 1
                    penalty += night_run * 0.5
                else:
                    night_run = 0
                if run > 3:
                    penalty += (run - 3) * 1.0
        return penalty

    # ──────────────────────────────────────────
    # 내부 유틸리티
    # ──────────────────────────────────────────

    @staticmethod
    def _consecutive_work_days(date: datetime.date, history: Dict[datetime.date, ShiftType]) -> int:
        """date 직전까지 연속 근무일 수 (date 미포함)."""
        count = 0
        d = date - datetime.timedelta(days=1)
        while True:
            shift = history.get(d)
            if shift is None or shift in OFF_SHIFTS:
                break
            count += 1
            d -= datetime.timedelta(days=1)
        return count

    @staticmethod
    def _consecutive_nights(date: datetime.date, history: Dict[datetime.date, ShiftType]) -> int:
        """date 직전까지 연속 야간 수 (date 미포함)."""
        count = 0
        d = date - datetime.timedelta(days=1)
        while True:
            shift = history.get(d)
            if shift not in NIGHT_SHIFTS:
                break
            count += 1
            d -= datetime.timedelta(days=1)
        return count
