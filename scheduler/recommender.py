# 수정: 2026-05-02
"""
스마트 추천 모듈 — 특정 날짜·근무 유형에 대해 간호사 후보를 점수화하여 순위 반환.

채점 요소:
  - 야간 공정성 (NIGHT_SHIFTS 기준)
  - 연속 근무 피로도
  - 개인 선호/기피
  - 숙련 간호사 야간 안전 기준
  - 선호 휴무 요일 침범
  - 이달 총 근무 과다
  - Hard Constraint 위반 여부
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .constraints import ConstraintChecker
from .models import (
    NIGHT_SHIFTS,
    OFF_SHIFTS,
    WORK_SHIFTS,
    Nurse,
    Schedule,
    ScheduleRules,
    ShiftType,
    SkillLevel,
)


# ──────────────────────────────────────────────────────────────────────────────
# 데이터 클래스: 후보 간호사 추천 결과
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class NurseCandidate:
    """스마트 추천의 단일 후보 항목."""
    nurse: Nurse
    score: float                    # 높을수록 적합 (Hard 위반 시 -999)
    reasons_pos: List[str] = field(default_factory=list)   # 긍정 이유 (한국어)
    reasons_neg: List[str] = field(default_factory=list)   # 부정 이유 (한국어)
    is_feasible: bool = True        # False 이면 Hard Constraint 위반으로 배정 불가


# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────────────────────────────────────

def _avg_night_count(
    matrix: Dict[str, Dict[datetime.date, ShiftType]],
    nurses: List[Nurse],
) -> float:
    """전체 간호사의 야간 근무 횟수 평균 계산."""
    if not nurses:
        return 0.0
    counts = [
        sum(1 for s in matrix[n.id].values() if s in NIGHT_SHIFTS)
        for n in nurses
        if n.id in matrix
    ]
    return sum(counts) / len(counts) if counts else 0.0


def _consecutive_before(
    hist: Dict[datetime.date, ShiftType],
    date: datetime.date,
) -> int:
    """
    date 바로 전날부터 거슬러 올라가며 연속 근무일 수 계산.
    (date 자신은 포함하지 않음)
    """
    count = 0
    d = date - datetime.timedelta(days=1)
    while True:
        shift = hist.get(d)
        if shift is None or shift in OFF_SHIFTS:
            break
        count += 1
        d -= datetime.timedelta(days=1)
    return count


# ──────────────────────────────────────────────────────────────────────────────
# SmartRecommender 클래스
# ──────────────────────────────────────────────────────────────────────────────

class SmartRecommender:
    """
    특정 날짜·근무 유형에 대해 간호사 후보를 점수 순으로 추천한다.

    사용법:
        recommender = SmartRecommender(rules, nurses)
        candidates = recommender.recommend(schedule, date, ShiftType.N, top_n=5)
    """

    def __init__(
        self,
        rules: ScheduleRules,
        nurses: List[Nurse],
    ) -> None:
        self.rules = rules
        self.nurses = nurses
        self.checker = ConstraintChecker(rules)

    def recommend(
        self,
        schedule: Schedule,
        date: datetime.date,
        shift: ShiftType,
        top_n: int = 5,
    ) -> List[NurseCandidate]:
        """
        주어진 날짜·근무에 대해 간호사 후보를 채점 후 상위 top_n명 반환.

        Args:
            schedule: 현재 근무표 (이미 배정된 항목 포함)
            date: 추천 대상 날짜
            shift: 추천 대상 근무 유형
            top_n: 반환할 최대 후보 수 (기본 5명)

        Returns:
            NurseCandidate 리스트 (score 내림차순 정렬)
        """
        matrix = schedule.as_matrix(self.nurses)
        avg_night = _avg_night_count(matrix, self.nurses)

        # 해당 날짜에 이미 근무(OFF 제외)가 배정된 간호사는 후보에서 제외
        # (O/OFF 인 간호사는 추천 대상으로 포함)
        already_assigned = {
            e.nurse_id
            for e in schedule.get_date_entries(date)
            if e.shift not in OFF_SHIFTS
        }

        candidates: List[NurseCandidate] = []

        for nurse in self.nurses:
            # 이미 그 날 다른 근무가 배정된 간호사 제외
            if nurse.id in already_assigned:
                continue

            hist = matrix.get(nurse.id, {})
            candidate = self._score_nurse(
                nurse=nurse,
                date=date,
                shift=shift,
                hist=hist,
                matrix=matrix,
                avg_night=avg_night,
            )
            candidates.append(candidate)

        # score 내림차순 정렬 (Hard 위반은 -999이므로 자동으로 후위)
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_n]

    # ──────────────────────────────────────────────────────────────────────────
    # 내부: 개별 간호사 채점
    # ──────────────────────────────────────────────────────────────────────────

    def _score_nurse(
        self,
        nurse: Nurse,
        date: datetime.date,
        shift: ShiftType,
        hist: Dict[datetime.date, ShiftType],
        matrix: Dict[str, Dict[datetime.date, ShiftType]],
        avg_night: float,
    ) -> NurseCandidate:
        """간호사 한 명에 대한 채점 수행 후 NurseCandidate 반환."""
        score: float = 0.0
        pos: List[str] = []
        neg: List[str] = []

        # ── 1. Hard Constraint 검증 ─────────────────────────────────────────
        # 고정 일정으로 블록된 날짜 집합 (이 모듈에서는 schedule의 is_fixed 항목 기준)
        fixed_dates = frozenset(
            e.date for e in schedule_entries_for_nurse(hist, nurse.id)
            if False  # ScheduleEntry 접근 없이 hist 만으로 판단
        )
        ok, reason = self.checker.can_assign(
            nurse=nurse,
            date=date,
            shift=shift,
            history=hist,
            fixed_dates=frozenset(),  # 연차/병가 고정 셀은 hist에 이미 반영됨
        )
        if not ok:
            # Hard Constraint 위반 → 배정 불가 처리
            neg.append("Hard Constraint 위반 (배정 불가)")
            return NurseCandidate(
                nurse=nurse,
                score=-999.0,
                reasons_pos=pos,
                reasons_neg=neg,
                is_feasible=False,
            )

        # ── 2. 야간 공정성 점수 ────────────────────────────────────────────
        # 야간 근무인 경우에만 적용 (N, N7, C, A 등 NIGHT_SHIFTS)
        if shift in NIGHT_SHIFTS:
            my_night = sum(1 for s in hist.values() if s in NIGHT_SHIFTS)
            deficit = avg_night - my_night
            if deficit > 0:
                # 평균보다 적게 함 → 야간 배정이 공정성에 기여
                bonus = deficit * 15.0
                score += bonus
                pos.append(
                    f"야간 횟수 {my_night}회 (평균 {avg_night:.1f}회 이하)"
                )
            # deficit <= 0 이면 이미 평균 이상 → 별도 감점은 없음 (다른 간호사 우선)

        # ── 3. 연속 근무 피로도 감점 ───────────────────────────────────────
        consec = _consecutive_before(hist, date)
        if consec > 3:
            penalty = (consec - 3) * 10.0
            score -= penalty
            neg.append(f"연속 {consec}일 근무로 피로 높음")

        # ── 4. 선호 근무 가산 ──────────────────────────────────────────────
        if shift in nurse.preference.preferred_shifts:
            score += 12.0
            pos.append(f"선호 근무({shift.value}) 반영")

        # ── 5. 기피 근무 감점 ──────────────────────────────────────────────
        if shift in nurse.preference.avoid_shifts:
            score -= 15.0
            neg.append(f"{shift.value} 기피 근무")

        # ── 6. 숙련 간호사 야간 안전 기준 가산 ────────────────────────────
        if shift in NIGHT_SHIFTS and nurse.skill_level == SkillLevel.SENIOR:
            score += 10.0
            pos.append("숙련 간호사 — 야간 안전 기준 충족")

        # ── 7. 선호 휴무 요일 침범 감점 ───────────────────────────────────
        if date.weekday() in nurse.preference.preferred_days_off and shift in WORK_SHIFTS:
            score -= 10.0
            neg.append("선호 휴무 요일 배정")

        # ── 8. 이달 총 근무 과다 감점 ─────────────────────────────────────
        total_work = sum(1 for s in hist.values() if s in WORK_SHIFTS)
        # 22일을 '과다' 기준으로 사용 (월 근무일 약 22일 이상)
        if total_work >= 22:
            score -= 8.0
            neg.append(f"이달 근무 과다({total_work}일)")

        return NurseCandidate(
            nurse=nurse,
            score=score,
            reasons_pos=pos,
            reasons_neg=neg,
            is_feasible=True,
        )


def schedule_entries_for_nurse(
    hist: Dict[datetime.date, ShiftType],
    nurse_id: str,
) -> list:
    """더미 함수 — 내부에서 실제로 사용되지 않음 (타입 힌트용)."""
    return []
