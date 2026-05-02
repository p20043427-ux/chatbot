# 수정: 2026-05-02
"""
자동 수정 모듈 — 생성된 근무표의 품질을 규칙 기반으로 개선.

중요 원칙:
  - is_fixed=True 인 셀은 절대 수정하지 않음
  - 각 메서드 시작 시 copy.deepcopy(schedule) 로 원본 보호
  - 최대 변경 횟수 제한으로 과도한 수정 방지

메서드:
  1. balance_night_shifts   — 야간 근무 횟수 불균형 조정 (최대 5회 스왑)
  2. reduce_consecutive_days — 최대 연속 근무일 초과 시 OFF 삽입
  3. optimize_off_distribution — 주말 근무 많은 간호사에게 주말 OFF 배분
"""

from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import (
    NIGHT_SHIFTS,
    OFF_SHIFTS,
    WORK_SHIFTS,
    Nurse,
    Schedule,
    ScheduleEntry,
    ScheduleRules,
    ShiftType,
)


# ──────────────────────────────────────────────────────────────────────────────
# 수정 결과 데이터 클래스
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FixResult:
    """자동 수정 결과."""
    success: bool
    changes: List[str] = field(default_factory=list)   # 변경 내역 요약 (한국어)
    schedule: Optional[Schedule] = None                 # 수정된 근무표 (success=True 일 때)
    message: str = ""                                   # 요약 메시지


# ──────────────────────────────────────────────────────────────────────────────
# AutoFixer 클래스
# ──────────────────────────────────────────────────────────────────────────────

class AutoFixer:
    """
    규칙 기반 자동 근무표 수정기.

    사용법:
        fixer = AutoFixer(rules, nurses)
        result = fixer.balance_night_shifts(schedule)
        if result.success:
            st.session_state.schedule = result.schedule
    """

    def __init__(self, rules: ScheduleRules, nurses: List[Nurse]) -> None:
        self.rules = rules
        self.nurses = nurses

    # ──────────────────────────────────────────────────────────────────────────
    # 1. 야간 근무 균형 조정
    # ──────────────────────────────────────────────────────────────────────────

    def balance_night_shifts(self, schedule: Schedule) -> FixResult:
        """
        야간 근무 횟수가 많은 간호사와 적은 간호사 사이에서
        야간 셀을 스왑하여 균형을 맞춘다 (최대 5회 스왑).

        is_fixed=True 셀은 수정하지 않는다.
        """
        # 원본 보호 — deepcopy 로 완전 복사 후 작업
        new_schedule = copy.deepcopy(schedule)
        changes: List[str] = []

        nurse_map = {n.id: n for n in self.nurses}
        matrix = new_schedule.as_matrix(self.nurses)

        # 각 간호사의 야간 횟수 계산
        night_counts: Dict[str, int] = {
            n.id: sum(1 for s in matrix[n.id].values() if s in NIGHT_SHIFTS)
            for n in self.nurses
            if n.id in matrix
        }

        max_swaps = 5
        swap_count = 0

        for _ in range(max_swaps):
            if not night_counts:
                break

            # 야간 횟수 가장 많은/적은 간호사 찾기
            over_id  = max(night_counts, key=lambda nid: night_counts[nid])
            under_id = min(night_counts, key=lambda nid: night_counts[nid])

            # 차이가 2 미만이면 균형 잡힌 것으로 간주 → 중단
            if night_counts[over_id] - night_counts[under_id] < 2:
                break

            over_nurse  = nurse_map.get(over_id)
            under_nurse = nurse_map.get(under_id)
            if over_nurse is None or under_nurse is None:
                break

            # over 간호사의 야간 셀 중 is_fixed=False 인 것 찾기
            over_night_entries = [
                e for e in new_schedule.entries
                if e.nurse_id == over_id
                and e.shift in NIGHT_SHIFTS
                and not e.is_fixed
            ]
            if not over_night_entries:
                break

            # under 간호사가 그 날짜에 배정 가능한지 확인:
            # 해당 날짜에 다른 근무가 없고, 야간 근무 허용 shift 가 있어야 함
            swapped = False
            for over_entry in over_night_entries:
                target_date = over_entry.date
                # under 간호사가 그날 이미 배정됐는지 확인
                under_entry_today = next(
                    (e for e in new_schedule.entries
                     if e.nurse_id == under_id and e.date == target_date),
                    None,
                )
                # under 간호사가 그날 비번(OFF)이고, is_fixed=False 여야 교환 가능
                if (under_entry_today is None
                        or (under_entry_today.shift in OFF_SHIFTS and not under_entry_today.is_fixed)):

                    # under 간호사가 야간 가능한 Shift 를 허용하는지 확인
                    if over_entry.shift not in under_nurse.allowed_shifts:
                        continue

                    # 스왑 실행
                    # over → O (비번)로 변경
                    over_entry.shift = ShiftType.O

                    if under_entry_today is not None:
                        # 기존 O 셀을 야간으로 변경
                        under_entry_today.shift = over_entry.shift if over_entry.shift != ShiftType.O else over_entry.shift
                        # 실제로는 over_entry 의 원래 shift 로 바꿔야 함 → 이미 O 로 바꿨으므로 별도 처리
                        under_entry_today.shift = ShiftType.N  # 야간 근무 기본값
                    else:
                        # under 간호사에게 새 야간 셀 추가
                        new_schedule.entries.append(ScheduleEntry(
                            nurse_id=under_id,
                            date=target_date,
                            shift=ShiftType.N,
                            is_fixed=False,
                            is_weekend=target_date.weekday() >= 5,
                        ))

                    # 카운트 업데이트
                    night_counts[over_id] -= 1
                    night_counts[under_id] += 1
                    swap_count += 1

                    over_name  = over_nurse.name
                    under_name = under_nurse.name
                    changes.append(
                        f"{target_date} 야간 스왑: {over_name} → {under_name} "
                        f"({over_name} {night_counts[over_id]}회 / {under_name} {night_counts[under_id]}회)"
                    )
                    swapped = True
                    break

            if not swapped:
                break

        if swap_count > 0:
            return FixResult(
                success=True,
                changes=changes,
                schedule=new_schedule,
                message=f"야간 균형 조정 완료: {swap_count}회 스왑",
            )
        else:
            return FixResult(
                success=False,
                changes=[],
                schedule=schedule,
                message="야간 근무 횟수 편차가 적어 수정이 필요하지 않습니다.",
            )

    # ──────────────────────────────────────────────────────────────────────────
    # 2. 연속 근무 완화 (최대 연속 근무일 초과 시 OFF 삽입)
    # ──────────────────────────────────────────────────────────────────────────

    def reduce_consecutive_days(self, schedule: Schedule) -> FixResult:
        """
        max_consecutive_work_days 를 초과하는 연속 근무 구간에 OFF 를 삽입한다.
        is_fixed=True 셀은 건드리지 않는다.
        """
        new_schedule = copy.deepcopy(schedule)
        changes: List[str] = []
        max_consec = self.rules.max_consecutive_work_days

        for nurse in self.nurses:
            # 해당 간호사의 엔트리를 날짜 순으로 정렬
            nurse_entries = sorted(
                [e for e in new_schedule.entries if e.nurse_id == nurse.id],
                key=lambda e: e.date,
            )

            # 연속 근무 구간 탐색
            run: List[ScheduleEntry] = []
            for entry in nurse_entries:
                if entry.shift not in OFF_SHIFTS:
                    run.append(entry)
                else:
                    # OFF 가 나오면 구간 검사 후 초기화
                    if len(run) > max_consec:
                        self._insert_off_in_run(run, max_consec, changes, nurse.name)
                    run = []

            # 마지막 구간 검사
            if len(run) > max_consec:
                self._insert_off_in_run(run, max_consec, changes, nurse.name)

        if changes:
            return FixResult(
                success=True,
                changes=changes,
                schedule=new_schedule,
                message=f"연속 근무 완화 완료: {len(changes)}곳 수정",
            )
        else:
            return FixResult(
                success=False,
                changes=[],
                schedule=schedule,
                message="연속 근무 초과 구간이 없습니다.",
            )

    def _insert_off_in_run(
        self,
        run: List[ScheduleEntry],
        max_consec: int,
        changes: List[str],
        nurse_name: str,
    ) -> None:
        """
        연속 근무 구간(run) 에서 max_consec+1 번째 날부터 비고정 셀을 OFF 로 변경.
        """
        # max_consec 일 이후 셀부터 처리
        for entry in run[max_consec:]:
            if not entry.is_fixed:
                old_shift = entry.shift.value
                entry.shift = ShiftType.O
                changes.append(
                    f"{nurse_name} {entry.date}: {old_shift} → O "
                    f"(연속 {max_consec}일 초과 방지)"
                )

    # ──────────────────────────────────────────────────────────────────────────
    # 3. 주말 OFF 최적화
    # ──────────────────────────────────────────────────────────────────────────

    def optimize_off_distribution(self, schedule: Schedule) -> FixResult:
        """
        주말(토·일) 근무 횟수가 가장 많은 간호사에게 주말 OFF 를 제공한다.
        비고정 주말 근무 셀 중 교체 가능한 것을 찾아 OFF 로 변환한다.
        """
        new_schedule = copy.deepcopy(schedule)
        changes: List[str] = []

        # 간호사별 주말 근무 횟수 계산
        weekend_work: Dict[str, int] = {}
        for nurse in self.nurses:
            weekend_work[nurse.id] = sum(
                1 for e in new_schedule.entries
                if e.nurse_id == nurse.id
                and e.is_weekend
                and e.shift in WORK_SHIFTS
                and not e.is_fixed
            )

        if not weekend_work:
            return FixResult(
                success=False,
                changes=[],
                schedule=schedule,
                message="처리할 주말 근무 데이터가 없습니다.",
            )

        # 주말 근무 많은 순으로 간호사 정렬
        sorted_nurses = sorted(
            [n for n in self.nurses if n.id in weekend_work],
            key=lambda n: weekend_work[n.id],
            reverse=True,
        )

        nurse_map = {n.id: n for n in self.nurses}

        for nurse in sorted_nurses:
            # 주말 근무가 평균 이하면 중단 (과도하게 많은 간호사만 처리)
            avg = sum(weekend_work.values()) / len(weekend_work) if weekend_work else 0
            if weekend_work[nurse.id] <= avg:
                break

            # 해당 간호사의 비고정 주말 근무 셀 찾기 (날짜 오름차순)
            weekend_entries = sorted(
                [e for e in new_schedule.entries
                 if e.nurse_id == nurse.id
                 and e.is_weekend
                 and e.shift in WORK_SHIFTS
                 and not e.is_fixed],
                key=lambda e: e.date,
            )

            # 최신 주말 1개를 OFF 로 변환 (가장 최근 주말)
            if weekend_entries:
                target = weekend_entries[-1]
                old_shift = target.shift.value
                target.shift = ShiftType.O
                weekend_work[nurse.id] -= 1
                changes.append(
                    f"{nurse.name} {target.date}({['월','화','수','목','금','토','일'][target.date.weekday()]}): "
                    f"{old_shift} → O (주말 OFF 배분, 주말 근무 {weekend_work[nurse.id]+1}→{weekend_work[nurse.id]}회)"
                )

        if changes:
            return FixResult(
                success=True,
                changes=changes,
                schedule=new_schedule,
                message=f"주말 OFF 최적화 완료: {len(changes)}명 조정",
            )
        else:
            return FixResult(
                success=False,
                changes=[],
                schedule=schedule,
                message="주말 근무 편차가 적어 수정이 필요하지 않습니다.",
            )
