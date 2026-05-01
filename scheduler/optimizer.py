"""
Local Search 최적화 모듈 (Simulated Annealing).

38종 근무 코드 대응:
  - NIGHT_SHIFTS 집합으로 야간 전환 판별
  - OFF_SHIFTS 집합으로 비근무 판별
  - 스왑 대상: ASSIGNABLE_SHIFTS 에 속하는 코드만 교환
"""

from __future__ import annotations

import copy
import datetime
import logging
import math
import random
from typing import Dict, List, Optional, Tuple

from .constraints import ConstraintChecker
from .models import (
    ASSIGNABLE_SHIFTS,
    NIGHT_SHIFTS,
    OFF_SHIFTS,
    Nurse,
    Schedule,
    ScheduleConfig,
    ScheduleEntry,
    ShiftType,
)

logger = logging.getLogger(__name__)


class LocalSearchOptimizer:
    """
    Simulated Annealing 기반 Local Search 최적화기.

    사용법:
        optimizer = LocalSearchOptimizer(config)
        improved = optimizer.optimize(initial_schedule)
    """

    def __init__(
        self,
        config: ScheduleConfig,
        max_iterations: int = 2000,
        initial_temp: float = 10.0,
        cooling_rate: float = 0.995,
        seed: Optional[int] = None,
    ) -> None:
        self.config = config
        self.checker = ConstraintChecker(config.rules)
        self.max_iterations = max_iterations
        self.initial_temp = initial_temp
        self.cooling_rate = cooling_rate
        if seed is not None:
            random.seed(seed)

        self._dates = self._build_dates()
        self._locked: frozenset = frozenset(
            (e.nurse_id, e.date) for e in config.locked_entries
        )
        self._fixed_off: frozenset = frozenset(
            (fs.nurse_id, fs.date) for fs in config.fixed_schedules
        )

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    def optimize(self, schedule: Schedule) -> Schedule:
        """초기 스케줄을 받아 최적화된 스케줄 반환."""
        logger.info("Local Search 최적화 시작 (최대 %d 반복)", self.max_iterations)

        current = self._copy_matrix(schedule)
        current_score = self._score(current)
        best = copy.deepcopy(current)
        best_score = current_score

        temp = self.initial_temp
        improved_count = 0

        for iteration in range(self.max_iterations):
            neighbor, _ = self._generate_neighbor(current)
            if neighbor is None:
                continue

            neighbor_score = self._score(neighbor)
            delta = neighbor_score - current_score

            if delta < 0 or random.random() < math.exp(-delta / max(temp, 1e-6)):
                current = neighbor
                current_score = neighbor_score
                improved_count += 1

                if current_score < best_score:
                    best = copy.deepcopy(current)
                    best_score = current_score

            temp *= self.cooling_rate

            if iteration % 500 == 0:
                logger.debug("iter=%d  T=%.3f  score=%.2f  best=%.2f",
                             iteration, temp, current_score, best_score)

        logger.info("최적화 완료: best=%.2f  (개선 %d회)", best_score, improved_count)
        return self._matrix_to_schedule(best, schedule)

    # ──────────────────────────────────────────
    # 이웃해 생성 (2-opt Swap)
    # ──────────────────────────────────────────

    def _generate_neighbor(
        self,
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """
        두 간호사의 같은 날짜 shift 를 교환.
        ASSIGNABLE_SHIFTS 에 속하는 코드만 스왑 대상 — 고정 일정 코드(Y/I/T 등) 보호.
        다음 날 forward 제약도 함께 검증.
        """
        nurses = self.config.nurses
        if len(nurses) < 2:
            return None, None

        date = random.choice(self._dates)
        n1, n2 = random.sample(nurses, 2)

        if (n1.id, date) in self._locked or (n2.id, date) in self._locked:
            return None, None
        if (n1.id, date) in self._fixed_off or (n2.id, date) in self._fixed_off:
            return None, None

        shift1 = matrix[n1.id].get(date, ShiftType.O)
        shift2 = matrix[n2.id].get(date, ShiftType.O)

        # 같은 코드이거나, 비배정 코드(O/OFF/Y 등)는 스왑 무의미
        if shift1 == shift2:
            return None, None
        if shift1 not in ASSIGNABLE_SHIFTS and shift1 not in {ShiftType.O, ShiftType.OFF}:
            return None, None
        if shift2 not in ASSIGNABLE_SHIFTS and shift2 not in {ShiftType.O, ShiftType.OFF}:
            return None, None

        neighbor = {nid: dict(hist) for nid, hist in matrix.items()}
        neighbor[n1.id][date] = shift2
        neighbor[n2.id][date] = shift1

        if not self._hard_ok(n1, date, shift2, neighbor) or \
           not self._hard_ok(n2, date, shift1, neighbor):
            return None, None

        # Forward 검증 (다음 날 연속성)
        next_date = date + datetime.timedelta(days=1)
        if next_date in self._dates:
            for nurse in (n1, n2):
                next_shift = neighbor[nurse.id].get(next_date, ShiftType.O)
                if next_shift not in OFF_SHIFTS:
                    if not self._hard_ok(nurse, next_date, next_shift, neighbor):
                        return None, None

        return neighbor, f"swap({n1.id},{n2.id},{date})"

    def _hard_ok(
        self,
        nurse: Nurse,
        date: datetime.date,
        shift: ShiftType,
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
    ) -> bool:
        if shift in OFF_SHIFTS:
            return True
        hist = matrix[nurse.id]
        fixed_dates = frozenset(d for (nid, d) in self._fixed_off if nid == nurse.id)
        ok, _ = self.checker.can_assign(
            nurse=nurse,
            date=date,
            shift=shift,
            history={d: s for d, s in hist.items() if d != date},
            fixed_dates=fixed_dates,
        )
        return ok

    # ──────────────────────────────────────────
    # 점수 계산 (낮을수록 좋음)
    # ──────────────────────────────────────────

    def _score(self, matrix: Dict[str, Dict[datetime.date, ShiftType]]) -> float:
        nurse_ids = [n.id for n in self.config.nurses]
        score = self.checker.night_distribution_penalty(nurse_ids, matrix)
        score += self.checker.weekend_distribution_penalty(nurse_ids, matrix)
        for nurse in self.config.nurses:
            score += self.checker.preference_penalty(nurse, matrix[nurse.id])
            score += self.checker.fatigue_penalty(nurse.id, matrix)
        return score

    # ──────────────────────────────────────────
    # 헬퍼
    # ──────────────────────────────────────────

    @staticmethod
    def _copy_matrix(schedule: Schedule) -> Dict[str, Dict[datetime.date, ShiftType]]:
        matrix: Dict[str, Dict[datetime.date, ShiftType]] = {}
        for entry in schedule.entries:
            matrix.setdefault(entry.nurse_id, {})[entry.date] = entry.shift
        return matrix

    def _matrix_to_schedule(
        self,
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
        original: Schedule,
    ) -> Schedule:
        orig_map = {(e.nurse_id, e.date): e for e in original.entries}
        entries = []
        for nurse_id, hist in matrix.items():
            for date, shift in hist.items():
                orig = orig_map.get((nurse_id, date))
                entries.append(ScheduleEntry(
                    nurse_id=nurse_id, date=date, shift=shift,
                    is_fixed=orig.is_fixed if orig else False,
                    is_holiday=orig.is_holiday if orig else False,
                    is_weekend=orig.is_weekend if orig else False,
                    note=orig.note if orig else "",
                ))
        return Schedule(
            ward_id=original.ward_id,
            year=original.year, month=original.month,
            entries=entries,
            generated_at=datetime.datetime.now(),
            generation_params={**original.generation_params, "optimizer": "simulated_annealing"},
        )

    def _build_dates(self) -> List[datetime.date]:
        import calendar
        _, last_day = calendar.monthrange(self.config.year, self.config.month)
        return [datetime.date(self.config.year, self.config.month, d) for d in range(1, last_day + 1)]
