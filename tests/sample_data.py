"""
샘플 데이터 생성 모듈 — 38종 근무 코드 체계 반영.

간호사 선호/기피에 실제 코드(N, N7, E 등) 사용.
고정 일정에 FixedScheduleType → 실제 ShiftType 코드 자동 매핑.
"""

from __future__ import annotations

import datetime
from typing import List, Optional

from scheduler.models import (
    FixedSchedule,
    FixedScheduleType,
    Nurse,
    NursePreference,
    ScheduleConfig,
    ScheduleRules,
    ShiftRequirement,
    ShiftType,
    SkillLevel,
    Ward,
    WardType,
)


def create_sample_ward() -> Ward:
    return Ward(
        id="W-301", name="내과 3병동",
        ward_type=WardType.GENERAL,
        patient_count=40, acuity_level=3,
    )


def create_sample_nurses() -> List[Nurse]:
    """12명 샘플 간호사 (신규 3 / 일반 5 / 숙련 4)."""
    return [
        # ── 숙련 (4명)
        Nurse(
            id="N001", name="김수진", skill_level=SkillLevel.SENIOR,
            ward_qualifications=[WardType.GENERAL, WardType.ICU],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.M],
            preference=NursePreference(
                preferred_shifts=[ShiftType.D, ShiftType.M],
                preferred_days_off=[5, 6],
            ),
        ),
        Nurse(
            id="N002", name="이민정", skill_level=SkillLevel.SENIOR,
            ward_qualifications=[WardType.GENERAL, WardType.SURGICAL],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.N7],
            preference=NursePreference(
                preferred_shifts=[ShiftType.E],
                preferred_days_off=[0],
            ),
        ),
        Nurse(
            id="N003", name="박지영", skill_level=SkillLevel.SENIOR,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.N],
            preference=NursePreference(
                avoid_shifts=[ShiftType.N, ShiftType.N7],   # 야간 기피
                preferred_days_off=[6],
            ),
        ),
        Nurse(
            id="N004", name="최현숙", skill_level=SkillLevel.SENIOR,
            ward_qualifications=[WardType.GENERAL, WardType.INFECTION],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.N7],
            preference=NursePreference(
                preferred_shifts=[ShiftType.N, ShiftType.N7],
                max_nights_per_month=10,
            ),
        ),
        # ── 일반 (5명)
        Nurse(
            id="N005", name="정유나", skill_level=SkillLevel.GENERAL,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.S9],
            preference=NursePreference(preferred_days_off=[5, 6]),
        ),
        Nurse(
            id="N006", name="강민수", skill_level=SkillLevel.GENERAL,
            ward_qualifications=[WardType.GENERAL, WardType.SURGICAL],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.N],
            preference=NursePreference(avoid_shifts=[ShiftType.N, ShiftType.N7]),
        ),
        Nurse(
            id="N007", name="윤서아", skill_level=SkillLevel.GENERAL,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.S10],
            preference=NursePreference(preferred_shifts=[ShiftType.D, ShiftType.E]),
        ),
        Nurse(
            id="N008", name="한지원", skill_level=SkillLevel.GENERAL,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.N],
            preference=NursePreference(preferred_days_off=[0, 1]),
        ),
        Nurse(
            id="N009", name="오승현", skill_level=SkillLevel.GENERAL,
            ward_qualifications=[WardType.GENERAL, WardType.ICU],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.N7],
            preference=NursePreference(),
        ),
        # ── 신규 (3명, 야간 불가)
        Nurse(
            id="N010", name="임채은", skill_level=SkillLevel.NEW,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.S9, ShiftType.S10],
            preference=NursePreference(preferred_shifts=[ShiftType.D]),
        ),
        Nurse(
            id="N011", name="신동현", skill_level=SkillLevel.NEW,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.S11],
            preference=NursePreference(preferred_shifts=[ShiftType.D]),
        ),
        Nurse(
            id="N012", name="류하은", skill_level=SkillLevel.NEW,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.D, ShiftType.E, ShiftType.S9],
            preference=NursePreference(preferred_days_off=[5, 6]),
        ),
    ]


def create_sample_rules() -> ScheduleRules:
    return ScheduleRules(
        max_consecutive_work_days=5,
        night_rest_required=True,
        max_consecutive_nights=3,
        min_rest_hours_between_shifts=11,
        shift_requirements={
            ShiftType.D: ShiftRequirement(min_nurses=4, min_senior_nurses=1),
            ShiftType.E: ShiftRequirement(min_nurses=3, min_senior_nurses=1),
            ShiftType.N: ShiftRequirement(min_nurses=2, min_senior_nurses=1),
        },
        fairness_weight_night=1.5,
        fairness_weight_weekend=1.0,
        fairness_weight_holiday=2.0,
        preference_satisfaction_rate=0.7,
    )


def create_sample_fixed_schedules(year: int, month: int) -> List[FixedSchedule]:
    """다양한 고정 일정 유형 샘플 — 실제 코드로 자동 매핑됨."""
    return [
        FixedSchedule(nurse_id="N001", date=datetime.date(year, month, 5),
                      schedule_type=FixedScheduleType.ANNUAL_LEAVE, note="여름 연차"),
        FixedSchedule(nurse_id="N001", date=datetime.date(year, month, 6),
                      schedule_type=FixedScheduleType.ANNUAL_LEAVE),
        FixedSchedule(nurse_id="N003", date=datetime.date(year, month, 10),
                      schedule_type=FixedScheduleType.EDUCATION, note="보수 교육"),
        FixedSchedule(nurse_id="N007", date=datetime.date(year, month, 15),
                      schedule_type=FixedScheduleType.SICK_LEAVE),
        FixedSchedule(nurse_id="N007", date=datetime.date(year, month, 16),
                      schedule_type=FixedScheduleType.SICK_LEAVE),
        FixedSchedule(nurse_id="N002", date=datetime.date(year, month, 20),
                      schedule_type=FixedScheduleType.CONGRATULATORY, note="경조사"),
    ]


def create_sample_config(
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> ScheduleConfig:
    today = datetime.date.today()
    y = year or today.year
    m = month or today.month
    return ScheduleConfig(
        ward=create_sample_ward(),
        nurses=create_sample_nurses(),
        rules=create_sample_rules(),
        fixed_schedules=create_sample_fixed_schedules(y, m),
        year=y, month=m,
        country_code="KR",
    )
