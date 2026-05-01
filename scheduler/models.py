"""
데이터 모델 정의 — 간호사, 병동, 규칙, 근무표 전체 구조.
Pydantic v2 기반으로 유효성 검증 포함.
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field, model_validator


# ──────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────

class ShiftType(str, Enum):
    DAY = "D"       # 07:00 ~ 15:00
    EVENING = "E"   # 15:00 ~ 23:00
    NIGHT = "N"     # 23:00 ~ 07:00
    OFF = "OFF"     # 휴무


class SkillLevel(str, Enum):
    NEW = "신규"        # 1년 미만
    GENERAL = "일반"   # 1~5년
    SENIOR = "숙련"    # 5년 이상


class WardType(str, Enum):
    GENERAL = "일반"
    ICU = "중환자실"
    INFECTION = "감염"
    EMERGENCY = "응급"
    PEDIATRIC = "소아과"
    SURGICAL = "외과"


# ──────────────────────────────────────────────
# 간호사 정보
# ──────────────────────────────────────────────

class NursePreference(BaseModel):
    """간호사 개인 선호 설정."""

    preferred_shifts: List[ShiftType] = Field(
        default_factory=list,
        description="선호 근무 유형 (예: [D, E])",
    )
    preferred_days_off: List[int] = Field(
        default_factory=list,
        description="선호 휴무 요일 (0=월 ~ 6=일)",
    )
    avoid_shifts: List[ShiftType] = Field(
        default_factory=list,
        description="기피 근무 유형",
    )
    max_nights_per_month: Optional[int] = Field(
        default=None,
        description="월 최대 야간 근무 횟수 (개인 상한, None=규칙 따름)",
    )


class Nurse(BaseModel):
    """간호사 마스터 데이터."""

    id: str = Field(..., description="고유 식별자")
    name: str = Field(..., description="이름")
    skill_level: SkillLevel = Field(..., description="경력 수준")
    ward_qualifications: List[WardType] = Field(
        ...,
        description="근무 가능 병동 목록",
    )
    allowed_shifts: List[ShiftType] = Field(
        default=[ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT],
        description="가능 근무 유형",
    )
    preference: NursePreference = Field(default_factory=NursePreference)
    is_part_time: bool = Field(default=False, description="파트타임 여부")

    @model_validator(mode="after")
    def off_not_in_allowed_shifts(self) -> "Nurse":
        # OFF 는 시스템이 자동 부여하므로 allowed_shifts 에서 제거
        self.allowed_shifts = [s for s in self.allowed_shifts if s != ShiftType.OFF]
        return self


# ──────────────────────────────────────────────
# 병동 정보
# ──────────────────────────────────────────────

class Ward(BaseModel):
    """병동 마스터 데이터."""

    id: str
    name: str
    ward_type: WardType
    patient_count: int = Field(ge=0)
    acuity_level: int = Field(ge=1, le=5, description="중증도 1(경증)~5(최중증)")


# ──────────────────────────────────────────────
# 근무 규칙
# ──────────────────────────────────────────────

class ShiftRequirement(BaseModel):
    """특정 Shift 의 인원 요건."""

    min_nurses: int = Field(ge=1, description="최소 간호사 수")
    min_senior_nurses: int = Field(ge=0, description="최소 숙련 간호사 수")


class ScheduleRules(BaseModel):
    """관리자가 설정하는 근무 규칙 전체."""

    # ── 연속 근무 제한
    max_consecutive_work_days: int = Field(
        default=5, ge=1, le=14,
        description="최대 연속 근무일수",
    )
    night_rest_required: bool = Field(
        default=True,
        description="Night 근무 후 다음날 반드시 OFF",
    )
    max_consecutive_nights: int = Field(
        default=3, ge=1, le=7,
        description="최대 연속 Night 근무 횟수",
    )
    min_rest_hours_between_shifts: int = Field(
        default=11,
        description="교대 간 최소 휴식 시간(시간 단위)",
    )

    # ── Shift별 인원 요건
    shift_requirements: Dict[ShiftType, ShiftRequirement] = Field(
        default_factory=lambda: {
            ShiftType.DAY:     ShiftRequirement(min_nurses=4, min_senior_nurses=1),
            ShiftType.EVENING: ShiftRequirement(min_nurses=3, min_senior_nurses=1),
            ShiftType.NIGHT:   ShiftRequirement(min_nurses=2, min_senior_nurses=1),
        }
    )

    # ── Soft 최적화 가중치
    fairness_weight_night: float = Field(
        default=1.0, ge=0, le=5,
        description="야간 근무 공정성 가중치",
    )
    fairness_weight_weekend: float = Field(
        default=1.0, ge=0, le=5,
        description="주말 근무 공정성 가중치",
    )
    fairness_weight_holiday: float = Field(
        default=1.5, ge=0, le=5,
        description="공휴일 근무 공정성 가중치",
    )
    preference_satisfaction_rate: float = Field(
        default=0.7, ge=0, le=1,
        description="개인 선호 반영 목표 비율 (0~1)",
    )

    # ── 월 근무 목표
    target_work_days_per_month: Optional[int] = Field(
        default=None,
        description="월 목표 근무일수 (None=자동 계산)",
    )


# ──────────────────────────────────────────────
# 고정 일정 (연차/교육/병가)
# ──────────────────────────────────────────────

class FixedScheduleType(str, Enum):
    ANNUAL_LEAVE = "연차"
    EDUCATION = "교육"
    SICK_LEAVE = "병가"
    SPECIAL_LEAVE = "특별휴가"


class FixedSchedule(BaseModel):
    """사전 확정된 개인 일정."""

    nurse_id: str
    date: datetime.date
    schedule_type: FixedScheduleType
    note: str = ""


# ──────────────────────────────────────────────
# 근무표 엔트리 (날짜 × 간호사)
# ──────────────────────────────────────────────

class ScheduleEntry(BaseModel):
    """단일 셀: 특정 날짜의 특정 간호사 근무."""

    nurse_id: str
    date: datetime.date
    shift: ShiftType
    is_fixed: bool = Field(
        default=False,
        description="사람이 수동 입력/고정한 셀이면 True (재생성 시 유지)",
    )
    is_holiday: bool = False
    is_weekend: bool = False
    note: str = ""


# ──────────────────────────────────────────────
# 근무표 전체 (월 단위)
# ──────────────────────────────────────────────

class Schedule(BaseModel):
    """월 단위 근무표."""

    ward_id: str
    year: int
    month: int
    entries: List[ScheduleEntry] = Field(default_factory=list)
    generated_at: Optional[datetime.datetime] = None
    generation_params: Dict = Field(default_factory=dict)

    def get_nurse_entries(self, nurse_id: str) -> List[ScheduleEntry]:
        return [e for e in self.entries if e.nurse_id == nurse_id]

    def get_date_entries(self, date: datetime.date) -> List[ScheduleEntry]:
        return [e for e in self.entries if e.date == date]

    def get_entry(self, nurse_id: str, date: datetime.date) -> Optional[ScheduleEntry]:
        for e in self.entries:
            if e.nurse_id == nurse_id and e.date == date:
                return e
        return None

    def as_matrix(self, nurses: List[Nurse]) -> Dict[str, Dict[datetime.date, ShiftType]]:
        """nurse_id → {date → ShiftType} 형태 딕셔너리 반환."""
        matrix: Dict[str, Dict[datetime.date, ShiftType]] = {
            n.id: {} for n in nurses
        }
        for entry in self.entries:
            if entry.nurse_id in matrix:
                matrix[entry.nurse_id][entry.date] = entry.shift
        return matrix


# ──────────────────────────────────────────────
# 스케줄링 실행 설정 (입력 통합 DTO)
# ──────────────────────────────────────────────

class ScheduleConfig(BaseModel):
    """스케줄러에 전달하는 모든 입력을 담는 DTO."""

    ward: Ward
    nurses: List[Nurse]
    rules: ScheduleRules
    fixed_schedules: List[FixedSchedule] = Field(default_factory=list)
    year: int
    month: int
    country_code: str = Field(default="KR", description="공휴일 계산용 국가 코드")
    previous_schedule: Optional[Schedule] = Field(
        default=None,
        description="이전 달 스케줄 (연속 근무 계산용)",
    )
    locked_entries: List[ScheduleEntry] = Field(
        default_factory=list,
        description="재생성 시 유지해야 할 수동 고정 셀",
    )

    @property
    def nurse_map(self) -> Dict[str, Nurse]:
        return {n.id: n for n in self.nurses}

    @property
    def fixed_set(self) -> Set[tuple]:
        """(nurse_id, date) 고정 집합."""
        return {(f.nurse_id, f.date) for f in self.fixed_schedules}
