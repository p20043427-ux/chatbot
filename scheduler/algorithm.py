"""
Greedy 스케줄링 알고리즘.

38종 근무 코드 대응:
  - 배정 대상 Shift: ASSIGNABLE_SHIFTS 집합 (scheduler가 자동 배정 가능한 코드)
  - 비근무 판별: OFF_SHIFTS 집합 사용
  - 야간 판별: NIGHT_SHIFTS 집합 사용
  - 고정 일정 코드: FixedSchedule.shift_code 프로퍼티로 해당 ShiftType 코드 주입

알고리즘 개요:
  1. 날짜 오름차순 순회
  2. 각 날짜마다 Shift 우선순위 (야간 → 저녁 → 주간) 로 배정
  3. 간호사 우선순위 = 숙련도 → 공정성 누적 → 개인 선호
  4. ConstraintChecker.can_assign() 통과 시 배정
  5. 배정 불가 시 인력 부족 경고 기록

시간 복잡도: O(D × S × N)
"""

from __future__ import annotations

import datetime
import logging
from typing import Dict, List, Optional, Set, Tuple

import holidays

from .constraints import ConstraintChecker
from .models import (
    ASSIGNABLE_SHIFTS,
    NIGHT_SHIFTS,
    OFF_SHIFTS,
    WORK_SHIFTS,
    FixedSchedule,
    Nurse,
    Schedule,
    ScheduleConfig,
    ScheduleEntry,
    ShiftType,
    SkillLevel,
)

logger = logging.getLogger(__name__)

# Greedy 에서 시도할 Shift 우선순위 (야간 인력 확보 우선)
SHIFT_PRIORITY: List[ShiftType] = [
    ShiftType.N,   # 밤근무 최우선
    ShiftType.N7,  # 밤근무(19시출근)
    ShiftType.C,   # 당직
    ShiftType.CC,  # 홀 당직
    ShiftType.A,   # 24시간
    ShiftType.E,   # 저녁근무
    ShiftType.DE,  # 낮/저녁
    ShiftType.D,   # 낮근무
    ShiftType.M,   # 상근
    ShiftType.S9, ShiftType.S10, ShiftType.S11,  # 스프린트
    ShiftType.DF,  # 토요
    ShiftType.HD, ShiftType.HE, ShiftType.HN,    # 반차
    ShiftType.KC, ShiftType.CH,                  # 당직 파생
]


class GreedyScheduler:
    """
    제약 기반 Greedy 스케줄러.

    사용법:
        scheduler = GreedyScheduler(config)
        schedule = scheduler.generate()
    """

    def __init__(self, config: ScheduleConfig) -> None:
        self.config = config
        self.checker = ConstraintChecker(config.rules)
        self._kr_holidays = self._load_holidays()
        self._dates = self._build_dates()
        # 고정 일정 (nurse_id, date) → ShiftType
        self._fixed_map: Dict[Tuple[str, datetime.date], ShiftType] = {
            (fs.nurse_id, fs.date): fs.shift_code
            for fs in config.fixed_schedules
        }
        # 수동 고정 셀
        self._locked_map: Dict[Tuple[str, datetime.date], ShiftType] = {
            (e.nurse_id, e.date): e.shift
            for e in config.locked_entries
        }

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    def generate(self) -> Schedule:
        """근무표 생성 후 Schedule 반환."""
        logger.info(
            "Greedy 스케줄 생성 시작: %d년 %d월, 간호사 %d명",
            self.config.year, self.config.month, len(self.config.nurses),
        )

        matrix: Dict[str, Dict[datetime.date, ShiftType]] = {
            n.id: {} for n in self.config.nurses
        }

        # 이전 달 이력 주입
        if self.config.previous_schedule:
            for entry in self.config.previous_schedule.entries:
                if entry.nurse_id in matrix:
                    matrix[entry.nurse_id][entry.date] = entry.shift

        # 수동 고정 셀 주입
        for (nid, d), shift in self._locked_map.items():
            if nid in matrix:
                matrix[nid][d] = shift

        # 고정 일정 코드 주입 (Y/I/T 등 실제 코드로 기록)
        for (nid, d), shift_code in self._fixed_map.items():
            if nid in matrix:
                matrix[nid][d] = shift_code

        # ── 날짜 × Shift 순회 배정
        shortage_log: List[str] = []

        for date in self._dates:
            for shift in self._get_required_shifts():
                req = self.config.rules.shift_requirements.get(shift)
                if req is None:
                    continue

                already = [
                    nid for nid, hist in matrix.items()
                    if hist.get(date) == shift
                ]
                needed = req.min_nurses - len(already)
                if needed <= 0:
                    continue

                candidates = self._rank_candidates(
                    date=date, shift=shift, matrix=matrix,
                    already_assigned=set(already),
                )

                assigned_count = 0
                for nurse in candidates:
                    if assigned_count >= needed:
                        break
                    fixed_dates = frozenset(
                        d for (nid, d) in self._fixed_map if nid == nurse.id
                    )
                    ok, reason = self.checker.can_assign(
                        nurse=nurse, date=date, shift=shift,
                        history=matrix[nurse.id], fixed_dates=fixed_dates,
                    )
                    if ok:
                        matrix[nurse.id][date] = shift
                        assigned_count += 1
                    else:
                        logger.debug("배정 불가 [%s %s %s]: %s", nurse.name, date, shift.value, reason)

                if assigned_count < needed:
                    msg = (
                        f"⚠️  {date} {shift.value}: "
                        f"필요 {req.min_nurses}명 중 {assigned_count}명만 배정"
                    )
                    logger.warning(msg)
                    shortage_log.append(msg)

        # 미배정 날짜 → O (비번)
        for nurse in self.config.nurses:
            for date in self._dates:
                if date not in matrix[nurse.id]:
                    matrix[nurse.id][date] = ShiftType.O

        # Schedule 객체 조립
        entries: List[ScheduleEntry] = []
        for nurse in self.config.nurses:
            for date in self._dates:
                shift = matrix[nurse.id][date]
                entries.append(ScheduleEntry(
                    nurse_id=nurse.id,
                    date=date,
                    shift=shift,
                    is_fixed=(nurse.id, date) in self._locked_map,
                    is_holiday=date in self._kr_holidays,
                    is_weekend=date.weekday() >= 5,
                ))

        schedule = Schedule(
            ward_id=self.config.ward.id,
            year=self.config.year,
            month=self.config.month,
            entries=entries,
            generated_at=datetime.datetime.now(),
            generation_params={"algorithm": "greedy", "shortage_log": shortage_log},
        )
        logger.info("Greedy 생성 완료: 총 %d 셀", len(entries))
        return schedule

    # ──────────────────────────────────────────
    # 내부 메서드
    # ──────────────────────────────────────────

    def _get_required_shifts(self) -> List[ShiftType]:
        """규칙에 정의된 Shift 를 SHIFT_PRIORITY 순서로 반환."""
        required = set(self.config.rules.shift_requirements.keys())
        ordered = [s for s in SHIFT_PRIORITY if s in required]
        # 정의됐지만 PRIORITY 목록 외 코드 뒤에 추가
        for s in required:
            if s not in ordered:
                ordered.append(s)
        return ordered

    def _rank_candidates(
        self,
        date: datetime.date,
        shift: ShiftType,
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
        already_assigned: Set[str],
    ) -> List[Nurse]:
        """배정 우선순위로 간호사 정렬."""
        # 오늘 이미 다른 shift 또는 같은 shift 배정됐거나 고정 일정인 간호사 제외
        blocked: Set[str] = set(already_assigned)
        for nid, hist in matrix.items():
            if hist.get(date) is not None:
                blocked.add(nid)
        blocked |= {nid for (nid, d) in self._fixed_map if d == date}

        candidates = [n for n in self.config.nurses if n.id not in blocked]

        # 병동 자격 필터 (ward_settings.require_ward_qualification)
        ward_settings = getattr(self.config, "ward_settings", None)
        if ward_settings is not None and ward_settings.require_ward_qualification:
            ward_type = self.config.ward.ward_type
            qualified = [n for n in candidates if ward_type in n.ward_qualifications]
            if qualified:  # 자격자가 없을 경우 필터 무시 (graceful degradation)
                candidates = qualified

        # 최소 경력 필터
        if ward_settings is not None and ward_settings.min_skill_level is not None:
            skill_order = {SkillLevel.NEW: 0, SkillLevel.GENERAL: 1, SkillLevel.SENIOR: 2}
            min_order = skill_order.get(ward_settings.min_skill_level, 0)
            skill_filtered = [n for n in candidates if skill_order.get(n.skill_level, 0) >= min_order]
            if skill_filtered:
                candidates = skill_filtered

        def sort_key(nurse: Nurse) -> Tuple:
            hist = matrix[nurse.id]
            # 해당 shift 누적 (공정성)
            shift_count = sum(1 for s in hist.values() if s == shift)
            # 야간 전체 누적 (공정성)
            night_count = sum(1 for s in hist.values() if s in NIGHT_SHIFTS)
            # 숙련도 우선 (숙련=0, 일반=1, 신규=2)
            skill_order = {SkillLevel.SENIOR: 0, SkillLevel.GENERAL: 1, SkillLevel.NEW: 2}.get(
                nurse.skill_level, 1
            )
            # 선호 (선호=0, 중립=1, 기피=2)
            pref_order = 0 if shift in nurse.preference.preferred_shifts else (
                2 if shift in nurse.preference.avoid_shifts else 1
            )
            return (skill_order, shift_count, night_count, pref_order, nurse.id)

        candidates.sort(key=sort_key)
        return candidates

    def _load_holidays(self) -> Set[datetime.date]:
        try:
            kr = holidays.country_holidays(self.config.country_code, years=self.config.year)
            return {d for d in kr if d.month == self.config.month}
        except Exception:
            return set()

    def _build_dates(self) -> List[datetime.date]:
        import calendar
        _, last_day = calendar.monthrange(self.config.year, self.config.month)
        return [datetime.date(self.config.year, self.config.month, d) for d in range(1, last_day + 1)]


def generate_schedule(config: ScheduleConfig) -> Schedule:
    """간편 API."""
    return GreedyScheduler(config).generate()
