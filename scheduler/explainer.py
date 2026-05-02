# 수정: 2026-05-02
"""
배정 설명 모듈 — 특정 간호사가 특정 날짜·근무에 배정된 이유를 한국어로 설명.

AssignmentExplainer.explain() 메서드는 추천 로직과 동일한 채점 기준을 역으로 해석해
"왜 이 간호사가 배정되었는가"를 사람이 읽을 수 있는 문장으로 반환한다.
"""

from __future__ import annotations

import datetime
from typing import Dict, List

from .models import (
    NIGHT_SHIFTS,
    OFF_SHIFTS,
    WORK_SHIFTS,
    Nurse,
    Schedule,
    ShiftType,
    SkillLevel,
)
from .recommender import _avg_night_count, _consecutive_before


class AssignmentExplainer:
    """
    배정 결정 설명기.

    사용법:
        explainer = AssignmentExplainer()
        reasons = explainer.explain(nurse, date, shift, schedule, all_nurses)
    """

    def explain(
        self,
        nurse: Nurse,
        date: datetime.date,
        shift: ShiftType,
        schedule: Schedule,
        all_nurses: List[Nurse],
    ) -> List[str]:
        """
        해당 간호사가 해당 날짜·근무에 배정된 이유를 한국어 문장 리스트로 반환.

        Args:
            nurse:      설명 대상 간호사
            date:       배정 날짜
            shift:      배정 근무 유형
            schedule:   현재 근무표
            all_nurses: 전체 간호사 목록 (평균 계산용)

        Returns:
            한국어 이유 문장 리스트 (1개 이상 보장)
        """
        matrix = schedule.as_matrix(all_nurses)
        hist = matrix.get(nurse.id, {})

        reasons: List[str] = []

        # ── 1. 야간 공정성 ──────────────────────────────────────────────────
        if shift in NIGHT_SHIFTS:
            avg_night = _avg_night_count(matrix, all_nurses)
            my_night = sum(1 for s in hist.values() if s in NIGHT_SHIFTS)
            if my_night <= avg_night:
                reasons.append(
                    f"야간 횟수({my_night}회)가 평균({avg_night:.1f}회) 이하 → 공정성 우선 배정"
                )

        # ── 2. 숙련 간호사 야간 안전 기준 ─────────────────────────────────
        if shift in NIGHT_SHIFTS and nurse.skill_level == SkillLevel.SENIOR:
            reasons.append("숙련 간호사 → 야간 안전 기준 충족")

        # ── 3. 선호 근무 반영 ──────────────────────────────────────────────
        if shift in nurse.preference.preferred_shifts:
            reasons.append(f"선호 근무({shift.value}) 반영")

        # ── 4. 연속 근무 현황 ──────────────────────────────────────────────
        consec = _consecutive_before(hist, date)
        if consec <= 2:
            # 연속 근무가 짧으면 피로가 낮음 → 긍정적 이유
            reasons.append(f"연속 근무 {consec}일 → 피로 낮음")
        elif consec > 3:
            # 연속 근무가 이미 많은 경우에도 배정된 경우 (인력 부족 등)
            reasons.append(f"연속 근무 {consec}일 (인력 부족으로 불가피 배정)")

        # ── 5. 주말/공휴일 근무 ────────────────────────────────────────────
        if date.weekday() >= 5 and shift in WORK_SHIFTS:
            # 주말 근무 배정 이유: 주말 근무 적음 또는 역할 필요
            weekend_count = sum(
                1 for d, s in hist.items() if d.weekday() >= 5 and s in WORK_SHIFTS
            )
            reasons.append(f"주말 근무 {weekend_count}회 (공정 배분)")

        # ── 6. 해당 근무 유형 경험 적음 (공정성) ──────────────────────────
        shift_count = sum(1 for s in hist.values() if s == shift)
        if shift_count == 0:
            reasons.append(f"이달 {shift.value} 근무 첫 배정 → 부담 분산")

        # ── 최소 1개 이유 보장 ─────────────────────────────────────────────
        if not reasons:
            reasons.append("스케줄러 자동 배정 (다른 후보 배정 불가)")

        return reasons
