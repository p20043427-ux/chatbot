"""
샘플 데이터 생성 모듈.

실제 병원 환경을 반영한 현실적인 테스트 데이터:
  - 일반 병동 12명 간호사 (신규 3 / 일반 5 / 숙련 4)
  - 다양한 선호도 패턴
  - ICU 자격자 2명 포함
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
    ShiftType,
    SkillLevel,
    Ward,
    WardType,
)
from scheduler.models import ShiftRequirement


def create_sample_ward() -> Ward:
    return Ward(
        id="W-301",
        name="내과 3병동",
        ward_type=WardType.GENERAL,
        patient_count=40,
        acuity_level=3,
    )


def create_sample_nurses() -> List[Nurse]:
    """12명 샘플 간호사 생성."""
    nurses = [
        # ── 숙련 간호사 (4명)
        Nurse(
            id="N001", name="김수진",
            skill_level=SkillLevel.SENIOR,
            ward_qualifications=[WardType.GENERAL, WardType.ICU],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT],
            preference=NursePreference(
                preferred_shifts=[ShiftType.DAY],
                preferred_days_off=[5, 6],  # 주말 OFF 선호
            ),
        ),
        Nurse(
            id="N002", name="이민정",
            skill_level=SkillLevel.SENIOR,
            ward_qualifications=[WardType.GENERAL, WardType.SURGICAL],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT],
            preference=NursePreference(
                preferred_shifts=[ShiftType.EVENING],
                preferred_days_off=[0],     # 월요일 OFF 선호
            ),
        ),
        Nurse(
            id="N003", name="박지영",
            skill_level=SkillLevel.SENIOR,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT],
            preference=NursePreference(
                avoid_shifts=[ShiftType.NIGHT],   # 야간 기피
                preferred_days_off=[6],
            ),
        ),
        Nurse(
            id="N004", name="최현숙",
            skill_level=SkillLevel.SENIOR,
            ward_qualifications=[WardType.GENERAL, WardType.INFECTION],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT],
            preference=NursePreference(
                preferred_shifts=[ShiftType.NIGHT],
                max_nights_per_month=10,
            ),
        ),
        # ── 일반 간호사 (5명)
        Nurse(
            id="N005", name="정유나",
            skill_level=SkillLevel.GENERAL,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT],
            preference=NursePreference(
                preferred_days_off=[5, 6],
            ),
        ),
        Nurse(
            id="N006", name="강민수",
            skill_level=SkillLevel.GENERAL,
            ward_qualifications=[WardType.GENERAL, WardType.SURGICAL],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT],
            preference=NursePreference(
                avoid_shifts=[ShiftType.NIGHT],
            ),
        ),
        Nurse(
            id="N007", name="윤서아",
            skill_level=SkillLevel.GENERAL,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT],
            preference=NursePreference(
                preferred_shifts=[ShiftType.DAY, ShiftType.EVENING],
            ),
        ),
        Nurse(
            id="N008", name="한지원",
            skill_level=SkillLevel.GENERAL,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT],
            preference=NursePreference(
                preferred_days_off=[0, 1],  # 월화 OFF 선호
            ),
        ),
        Nurse(
            id="N009", name="오승현",
            skill_level=SkillLevel.GENERAL,
            ward_qualifications=[WardType.GENERAL, WardType.ICU],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT],
            preference=NursePreference(),
        ),
        # ── 신규 간호사 (3명)
        Nurse(
            id="N010", name="임채은",
            skill_level=SkillLevel.NEW,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING],  # 신규: Night 불가
            preference=NursePreference(
                preferred_shifts=[ShiftType.DAY],
            ),
        ),
        Nurse(
            id="N011", name="신동현",
            skill_level=SkillLevel.NEW,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING],
            preference=NursePreference(
                preferred_shifts=[ShiftType.DAY],
            ),
        ),
        Nurse(
            id="N012", name="류하은",
            skill_level=SkillLevel.NEW,
            ward_qualifications=[WardType.GENERAL],
            allowed_shifts=[ShiftType.DAY, ShiftType.EVENING],
            preference=NursePreference(
                preferred_days_off=[5, 6],
            ),
        ),
    ]
    return nurses


def create_sample_rules() -> ScheduleRules:
    return ScheduleRules(
        max_consecutive_work_days=5,
        night_rest_required=True,
        max_consecutive_nights=3,
        min_rest_hours_between_shifts=11,
        shift_requirements={
            ShiftType.DAY:     ShiftRequirement(min_nurses=4, min_senior_nurses=1),
            ShiftType.EVENING: ShiftRequirement(min_nurses=3, min_senior_nurses=1),
            ShiftType.NIGHT:   ShiftRequirement(min_nurses=2, min_senior_nurses=1),
        },
        fairness_weight_night=1.5,
        fairness_weight_weekend=1.0,
        fairness_weight_holiday=2.0,
        preference_satisfaction_rate=0.7,
    )


def create_sample_fixed_schedules(year: int, month: int) -> List[FixedSchedule]:
    """현실적인 연차/병가 샘플."""
    return [
        FixedSchedule(
            nurse_id="N001",
            date=datetime.date(year, month, 5),
            schedule_type=FixedScheduleType.ANNUAL_LEAVE,
            note="여름 연차",
        ),
        FixedSchedule(
            nurse_id="N001",
            date=datetime.date(year, month, 6),
            schedule_type=FixedScheduleType.ANNUAL_LEAVE,
        ),
        FixedSchedule(
            nurse_id="N003",
            date=datetime.date(year, month, 10),
            schedule_type=FixedScheduleType.EDUCATION,
            note="보수 교육",
        ),
        FixedSchedule(
            nurse_id="N007",
            date=datetime.date(year, month, 15),
            schedule_type=FixedScheduleType.SICK_LEAVE,
        ),
        FixedSchedule(
            nurse_id="N007",
            date=datetime.date(year, month, 16),
            schedule_type=FixedScheduleType.SICK_LEAVE,
        ),
    ]


def create_sample_config(
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> ScheduleConfig:
    """표준 샘플 ScheduleConfig 생성."""
    today = datetime.date.today()
    y = year or today.year
    m = month or today.month
    return ScheduleConfig(
        ward=create_sample_ward(),
        nurses=create_sample_nurses(),
        rules=create_sample_rules(),
        fixed_schedules=create_sample_fixed_schedules(y, m),
        year=y,
        month=m,
        country_code="KR",
    )
