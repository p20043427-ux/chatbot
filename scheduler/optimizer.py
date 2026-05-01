"""
Local Search 최적화 모듈.

Greedy 로 생성된 초기 해(Initial Solution)를 반복적 스왑(Swap)으로 개선.

알고리즘: Simulated Annealing + 2-opt Swap
  - 이웃해: 두 간호사의 특정 날짜 shift 를 교환
  - 수용 조건: δ < 0 이면 무조건 수용, δ >= 0 이면 exp(-δ/T) 확률로 수용
  - 온도(T): 초기값 → 냉각률 × 반복으로 감소

Hard Constraint 를 항상 유지하면서 Soft Constraint 페널티를 최소화.
수동 고정 셀(is_fixed=True)은 스왑 대상에서 제외.

복잡도: O(iterations × N²) — 기본 iterations=2000, 실제 < 2초
"""

from __future__ import annotations

import copy
import datetime
import logging
import math
import random
from typing import Dict, List, Optional, Tuple

from .constraints import ConstraintChecker
from .evaluator import ScheduleEvaluator
from .models import (
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
        self.evaluator = ScheduleEvaluator(config)
        self.max_iterations = max_iterations
        self.initial_temp = initial_temp
        self.cooling_rate = cooling_rate
        if seed is not None:
            random.seed(seed)

        self._dates = self._build_dates()
        # 고정 셀: (nurse_id, date) → 스왑 불가
        self._locked: frozenset = frozenset(
            (e.nurse_id, e.date) for e in config.locked_entries
        )
        # 연차·병가 고정 날짜
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
            # 이웃해 생성 (2-opt swap)
            neighbor, swap_info = self._generate_neighbor(current)
            if neighbor is None:
                continue

            neighbor_score = self._score(neighbor)
            delta = neighbor_score - current_score

            # 수용 여부 결정
            if delta < 0 or random.random() < math.exp(-delta / max(temp, 1e-6)):
                current = neighbor
                current_score = neighbor_score
                improved_count += 1

                if current_score < best_score:
                    best = copy.deepcopy(current)
                    best_score = current_score

            temp *= self.cooling_rate

            if iteration % 500 == 0:
                logger.debug(
                    "iter=%d  T=%.3f  score=%.2f  best=%.2f",
                    iteration, temp, current_score, best_score,
                )

        logger.info(
            "최적화 완료: 초기 score=%.2f → 최종 best=%.2f  (개선 %d회)",
            self._score(self._copy_matrix(schedule)), best_score, improved_count,
        )

        return self._matrix_to_schedule(best, schedule)

    # ──────────────────────────────────────────
    # 이웃해 생성 (Swap)
    # ──────────────────────────────────────────

    def _generate_neighbor(
        self,
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """
        두 간호사의 같은 날짜 shift 를 교환.

        Hard Constraint 만족 여부를 검증 — 스왑 날짜뿐만 아니라
        다음 날(+1)의 제약 연속성(Night→* 규칙)도 함께 확인.
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

        shift1 = matrix[n1.id].get(date, ShiftType.OFF)
        shift2 = matrix[n2.id].get(date, ShiftType.OFF)

        if shift1 == shift2:
            return None, None

        # 스왑 적용
        neighbor = {nid: dict(hist) for nid, hist in matrix.items()}
        neighbor[n1.id][date] = shift2
        neighbor[n2.id][date] = shift1

        # 스왑 날짜 자체 Hard 검증
        if not self._hard_ok(n1, date, shift2, neighbor) or \
           not self._hard_ok(n2, date, shift1, neighbor):
            return None, None

        # 다음 날 forward 검증 — Night 직후 Day/Evening 전환 방지
        next_date = date + datetime.timedelta(days=1)
        if next_date in self._dates:
            for nurse in (n1, n2):
                next_shift = neighbor[nurse.id].get(next_date, ShiftType.OFF)
                if next_shift != ShiftType.OFF:
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
        """스왑 후 해당 간호사의 hard constraint 만족 여부 빠른 검사."""
        hist = matrix[nurse.id]
        fixed_dates = frozenset(
            d for (nid, d) in self._fixed_off if nid == nurse.id
        )
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
        """Soft Constraint 페널티 합산."""
        nurse_ids = [n.id for n in self.config.nurses]

        # 야간 분포 편차
        score = self.checker.night_distribution_penalty(nurse_ids, matrix)
        # 주말 분포 편차
        score += self.checker.weekend_distribution_penalty(nurse_ids, matrix)
        # 개인 선호 미반영
        for nurse in self.config.nurses:
            score += self.checker.preference_penalty(nurse, matrix[nurse.id])
        # 피로도
        for nid in nurse_ids:
            score += self.checker.fatigue_penalty(nid, matrix)

        return score

    # ──────────────────────────────────────────
    # 헬퍼
    # ──────────────────────────────────────────

    @staticmethod
    def _copy_matrix(
        schedule: Schedule,
    ) -> Dict[str, Dict[datetime.date, ShiftType]]:
        matrix: Dict[str, Dict[datetime.date, ShiftType]] = {}
        for entry in schedule.entries:
            matrix.setdefault(entry.nurse_id, {})[entry.date] = entry.shift
        return matrix

    def _matrix_to_schedule(
        self,
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
        original: Schedule,
    ) -> Schedule:
        """matrix → Schedule 객체 변환. 기존 메타(is_fixed 등) 유지."""
        orig_map: Dict[Tuple[str, datetime.date], ScheduleEntry] = {
            (e.nurse_id, e.date): e for e in original.entries
        }
        entries = []
        for nurse_id, hist in matrix.items():
            for date, shift in hist.items():
                orig = orig_map.get((nurse_id, date))
                entries.append(
                    ScheduleEntry(
                        nurse_id=nurse_id,
                        date=date,
                        shift=shift,
                        is_fixed=orig.is_fixed if orig else False,
                        is_holiday=orig.is_holiday if orig else False,
                        is_weekend=orig.is_weekend if orig else False,
                        note=orig.note if orig else "",
                    )
                )
        return Schedule(
            ward_id=original.ward_id,
            year=original.year,
            month=original.month,
            entries=entries,
            generated_at=datetime.datetime.now(),
            generation_params={**original.generation_params, "optimizer": "simulated_annealing"},
        )

    def _build_dates(self) -> List[datetime.date]:
        import calendar
        _, last_day = calendar.monthrange(self.config.year, self.config.month)
        return [
            datetime.date(self.config.year, self.config.month, day)
            for day in range(1, last_day + 1)
        ]
