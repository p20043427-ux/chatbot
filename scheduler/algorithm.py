"""
Greedy 스케줄링 알고리즘.

선택 이유:
  - OR-Tools CP-SAT: 수십 명 이상 규모에서 강력하지만 의존성이 무거움
  - Genetic Algorithm: 탐색 범위가 넓으나 수렴 시간이 오래 걸림
  - Greedy + Local Search (채택):
      * 규칙이 명확한 경우 탐욕 배정만으로도 60~80% 품질 확보
      * Local Search(optimizer.py)로 나머지 20~40% 개선
      * 실행 시간 < 5초 (30명 × 31일 기준)
      * 디버깅·설명이 쉬워 현업 수용도 높음

알고리즘 개요:
  1. 날짜별로 순회 (날짜 오름차순)
  2. 각 날짜마다 Shift 우선순위(Night > Evening > Day)로 배정
  3. 간호사 우선순위 = 공정성 점수(야간·주말 누적) 가장 낮은 순
  4. ConstraintChecker.can_assign() 통과한 첫 번째 간호사에게 배정
  5. 배정 불가 시 "인력 부족 경고" 기록

시간 복잡도: O(D × S × N)
  D = 일수, S = Shift 수(3), N = 간호사 수
"""

from __future__ import annotations

import datetime
import logging
import random
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import holidays

from .constraints import ConstraintChecker
from .models import (
    FixedSchedule,
    FixedScheduleType,
    Nurse,
    Schedule,
    ScheduleConfig,
    ScheduleEntry,
    ShiftType,
    SkillLevel,
)

logger = logging.getLogger(__name__)

# Night → OFF → Night 패턴 최소화를 위한 Night 블록 크기 기본값
DEFAULT_NIGHT_BLOCK = 3


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
        self._fixed_map: Dict[Tuple[str, datetime.date], FixedScheduleType] = {
            (fs.nurse_id, fs.date): fs.schedule_type
            for fs in config.fixed_schedules
        }
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

        # nurse_id → {date → ShiftType}
        matrix: Dict[str, Dict[datetime.date, ShiftType]] = {
            n.id: {} for n in self.config.nurses
        }

        # 이전 달 스케줄 이력 주입 (연속 근무 판단용)
        if self.config.previous_schedule:
            prev = self.config.previous_schedule
            for entry in prev.entries:
                if entry.nurse_id in matrix:
                    matrix[entry.nurse_id][entry.date] = entry.shift

        # 수동 고정 셀 먼저 주입
        for (nid, d), shift in self._locked_map.items():
            if nid in matrix:
                matrix[nid][d] = shift

        # ── 연차·병가·교육 OFF 처리
        for (nid, d), ftype in self._fixed_map.items():
            if nid in matrix:
                matrix[nid][d] = ShiftType.OFF

        # ── 날짜 × Shift 순회 배정
        shortage_log: List[str] = []

        for date in self._dates:
            is_weekend = date.weekday() >= 5
            is_holiday = date in self._kr_holidays

            for shift in [ShiftType.NIGHT, ShiftType.EVENING, ShiftType.DAY]:
                req = self.config.rules.shift_requirements.get(shift)
                if req is None:
                    continue

                already_assigned = [
                    nid for nid, hist in matrix.items()
                    if hist.get(date) == shift
                ]
                needed = req.min_nurses - len(already_assigned)
                if needed <= 0:
                    continue

                # 숙련자 먼저, 그 다음 공정성 점수 낮은 순 정렬
                candidates = self._rank_candidates(
                    date=date,
                    shift=shift,
                    matrix=matrix,
                    already_assigned=set(already_assigned),
                )

                assigned_count = 0
                for nurse in candidates:
                    if assigned_count >= needed:
                        break
                    fixed_dates = frozenset(
                        d for (nid, d), _ in self._fixed_map.items()
                        if nid == nurse.id
                    )
                    ok, reason = self.checker.can_assign(
                        nurse=nurse,
                        date=date,
                        shift=shift,
                        history=matrix[nurse.id],
                        fixed_dates=fixed_dates,
                    )
                    if ok:
                        matrix[nurse.id][date] = shift
                        assigned_count += 1
                    else:
                        logger.debug("배정 불가 [%s %s %s]: %s", nurse.name, date, shift.value, reason)

                if assigned_count < needed:
                    msg = (
                        f"⚠️  {date} {shift.value}: "
                        f"필요 {req.min_nurses}명 중 {assigned_count}명만 배정 (인력 부족)"
                    )
                    logger.warning(msg)
                    shortage_log.append(msg)

        # ── 배정되지 않은 날짜는 모두 OFF 처리
        for nurse in self.config.nurses:
            for date in self._dates:
                if date not in matrix[nurse.id]:
                    matrix[nurse.id][date] = ShiftType.OFF

        # ── Schedule 객체 조립
        entries: List[ScheduleEntry] = []
        for nurse in self.config.nurses:
            for date in self._dates:
                shift = matrix[nurse.id][date]
                is_locked = (nurse.id, date) in self._locked_map
                entries.append(
                    ScheduleEntry(
                        nurse_id=nurse.id,
                        date=date,
                        shift=shift,
                        is_fixed=is_locked,
                        is_holiday=date in self._kr_holidays,
                        is_weekend=date.weekday() >= 5,
                    )
                )

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

    def _rank_candidates(
        self,
        date: datetime.date,
        shift: ShiftType,
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
        already_assigned: Set[str],
    ) -> List[Nurse]:
        """
        배정 우선순위로 간호사 정렬.

        우선순위 기준 (낮을수록 먼저):
          1. 해당 날 이미 다른 shift 배정 → 제외
          2. 숙련자를 먼저 고려 (min_senior 충족 전까지)
          3. 공정성 점수 (해당 shift 의 누적 횟수가 낮은 간호사 우선)
          4. 동점 시 랜덤 (매 실행마다 다른 결과 방지 위해 nurse.id 정렬)
        """
        req = self.config.rules.shift_requirements[shift]

        # 이미 배정됐거나 오늘 다른 shift 잡힌 간호사 제외
        blocked: Set[str] = set(already_assigned)
        for nid, hist in matrix.items():
            if hist.get(date) is not None:
                blocked.add(nid)

        candidates: List[Nurse] = [
            n for n in self.config.nurses if n.id not in blocked
        ]

        # 날짜가 고정 OFF 인 간호사 제외
        candidates = [
            n for n in candidates
            if (n.id, date) not in self._fixed_map
        ]

        def sort_key(nurse: Nurse) -> Tuple:
            hist = matrix[nurse.id]
            # shift 별 누적 횟수 (공정성)
            shift_count = sum(1 for s in hist.values() if s == shift)
            # 숙련자 우선 (숙련=0, 일반=1, 신규=2)
            skill_order = {
                SkillLevel.SENIOR: 0,
                SkillLevel.GENERAL: 1,
                SkillLevel.NEW: 2,
            }.get(nurse.skill_level, 1)
            # 선호 shift 여부 (선호=0, 기피=2, 중립=1)
            pref_order = 1
            if shift in nurse.preference.preferred_shifts:
                pref_order = 0
            elif shift in nurse.preference.avoid_shifts:
                pref_order = 2
            return (skill_order, shift_count, pref_order, nurse.id)

        candidates.sort(key=sort_key)
        return candidates

    def _load_holidays(self) -> Set[datetime.date]:
        """한국 공휴일 로드."""
        try:
            kr = holidays.country_holidays(
                self.config.country_code,
                years=self.config.year,
            )
            return {d for d in kr if d.month == self.config.month}
        except Exception:
            return set()

    def _build_dates(self) -> List[datetime.date]:
        """해당 월의 날짜 목록 생성."""
        import calendar
        _, last_day = calendar.monthrange(self.config.year, self.config.month)
        return [
            datetime.date(self.config.year, self.config.month, day)
            for day in range(1, last_day + 1)
        ]


# ──────────────────────────────────────────────
# 편의 함수
# ──────────────────────────────────────────────

def generate_schedule(config: ScheduleConfig) -> Schedule:
    """GreedyScheduler 를 직접 쓰지 않을 때 사용하는 간편 API."""
    scheduler = GreedyScheduler(config)
    return scheduler.generate()
