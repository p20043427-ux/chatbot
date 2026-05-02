"""
데이터 모델 정의 — 간호사, 병동, 규칙, 근무표 전체 구조.
병원 실무 38종 근무 코드 완전 지원.
Pydantic v2 기반으로 유효성 검증 포함.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from pydantic import BaseModel, Field, model_validator


# ──────────────────────────────────────────────
# 근무 코드 Enum  (병원 실무 38종)
# ──────────────────────────────────────────────

class ShiftType(str, Enum):
    # ── 정규 근무
    O    = "O"     # 비번
    M    = "M"     # 상근          09:00~18:00
    C    = "C"     # 당직          (24h 포함 야간 대기)
    D    = "D"     # 낮근무        07:00~15:00
    DE   = "DE"    # 낮/저녁근무   07:00~23:00 (연장)
    E    = "E"     # 저녁근무      15:00~23:00
    N    = "N"     # 밤근무        23:00~07:00
    N7   = "N7"    # 밤근무(19시출근) 19:00~07:00
    # ── 반차 근무
    HD   = "HD"    # 반차낮근무    07:00~11:00 or 11:00~15:00
    HE   = "HE"    # 반차저녁근무  15:00~19:00 or 19:00~23:00
    HN   = "HN"    # 반차밤근무    23:00~03:00 or 03:00~07:00
    # ── 당직 파생
    CC   = "CC"    # 홀 당직
    KC   = "KC"    # 킵 당직
    CO   = "CO"    # 당직오프
    CH   = "CH"    # 당직하프
    # ── 스프린트 (탄력근무)
    S9   = "S9"    # 스프린트 09:00~17:00
    S10  = "S10"   # 스프린트 10:00~18:00
    S11  = "S11"   # 스프린트 11:00~19:00
    # ── 특수 근무
    DF   = "DF"    # 토요일 07:00~15:00
    A    = "A"     # 24시간 근무교대
    # ── 휴가 계열
    Y    = "Y"     # 연차
    YH   = "YH"   # 연차반휴
    G    = "G"     # 공가
    GH   = "GH"   # 공가(반휴)
    KV   = "KV"   # 경조휴가
    DV   = "DV"   # 분만휴가
    IV   = "IV"   # 육아휴직
    X    = "X"     # 사용X
    XV   = "XV"   # 무급휴직
    HXV  = "HXV"  # 무급휴직반차
    MV   = "MV"   # 한달 이상 휴가
    # ── 교육
    T    = "T"     # 전일 교육
    TH   = "TH"   # 반일 교육
    # ── 병가
    I    = "I"     # 병가
    IH   = "IH"   # 병가(반휴)
    # ── 제한·기타
    S    = "S"     # 사용금지
    S1   = "S1"   # 사용금지1
    K    = "K"     # 사용금지
    # ── 시스템 내부 (레거시 호환)
    OFF  = "OFF"   # 시스템 미배정 (O 와 동일 처리)


# ──────────────────────────────────────────────
# 근무 코드 메타데이터
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class ShiftMeta:
    """근무 코드 한 줄 메타."""
    label: str           # 한국어 명칭
    category: str        # 카테고리 (work / off / leave / sick / edu / limit)
    is_work: bool        # 근무일수 산정 여부
    is_night: bool       # 야간 유형 (다음날 휴식 필요)
    start_h: int         # 근무 시작 시간 (0~23, 비근무=0)
    end_h: int           # 근무 종료 시간 (0~23, 익일=+24)
    color_hex: str       # UI 셀 배경 색상


SHIFT_META: Dict[ShiftType, ShiftMeta] = {
    # 정규 근무 ────────────────────────────────
    ShiftType.O:   ShiftMeta("비번",             "off",   False, False,  0,  0,  "EFEFEF"),
    ShiftType.M:   ShiftMeta("상근",             "work",  True,  False,  9, 18,  "DDEEFF"),
    ShiftType.C:   ShiftMeta("당직",             "work",  True,  True,   9, 33,  "FFD699"),  # 익일 09시
    ShiftType.D:   ShiftMeta("낮근무",           "work",  True,  False,  7, 15,  "B8E4F9"),
    ShiftType.DE:  ShiftMeta("낮/저녁근무",      "work",  True,  False,  7, 23,  "A8D8F0"),
    ShiftType.E:   ShiftMeta("저녁근무",         "work",  True,  False, 15, 23,  "FFD966"),
    ShiftType.N:   ShiftMeta("밤근무",           "work",  True,  True,  23, 31,  "9FC5E8"),  # 익일 07시
    ShiftType.N7:  ShiftMeta("밤근무(19시출근)", "work",  True,  True,  19, 31,  "7EB3E0"),
    # 반차 근무 ────────────────────────────────
    ShiftType.HD:  ShiftMeta("반차낮근무",       "work",  True,  False,  7, 11,  "D4EDFF"),
    ShiftType.HE:  ShiftMeta("반차저녁근무",     "work",  True,  False, 15, 19,  "FFF0A0"),
    ShiftType.HN:  ShiftMeta("반차밤근무",       "work",  True,  True,  23, 27,  "C5DAEF"),
    # 당직 파생 ────────────────────────────────
    ShiftType.CC:  ShiftMeta("홀 당직",          "work",  True,  True,   9, 33,  "FFCC80"),
    ShiftType.KC:  ShiftMeta("킵 당직",          "work",  True,  True,   9, 33,  "FFB74D"),
    ShiftType.CO:  ShiftMeta("당직오프",         "off",   False, False,  0,  0,  "E0E0E0"),
    ShiftType.CH:  ShiftMeta("당직하프",         "work",  True,  False,  9, 18,  "FFECB3"),
    # 스프린트 ─────────────────────────────────
    ShiftType.S9:  ShiftMeta("스프린트(09~17)",  "work",  True,  False,  9, 17,  "C8F0C8"),
    ShiftType.S10: ShiftMeta("스프린트(10~18)",  "work",  True,  False, 10, 18,  "B8EAB8"),
    ShiftType.S11: ShiftMeta("스프린트(11~19)",  "work",  True,  False, 11, 19,  "A8E4A8"),
    # 특수 근무 ────────────────────────────────
    ShiftType.DF:  ShiftMeta("토요일(07~15)",    "work",  True,  False,  7, 15,  "B8E4F9"),
    ShiftType.A:   ShiftMeta("24시간 근무교대",  "work",  True,  True,   7, 31,  "FF8A80"),
    # 휴가 계열 ────────────────────────────────
    ShiftType.Y:   ShiftMeta("연차",             "leave", False, False,  0,  0,  "A8E6CF"),
    ShiftType.YH:  ShiftMeta("연차반휴",         "leave", False, False,  0,  0,  "C8F0DC"),
    ShiftType.G:   ShiftMeta("공가",             "leave", False, False,  0,  0,  "D4B3FF"),
    ShiftType.GH:  ShiftMeta("공가(반휴)",       "leave", False, False,  0,  0,  "E2CCFF"),
    ShiftType.KV:  ShiftMeta("경조휴가",         "leave", False, False,  0,  0,  "BBDEFB"),
    ShiftType.DV:  ShiftMeta("분만휴가",         "leave", False, False,  0,  0,  "F8BBD9"),
    ShiftType.IV:  ShiftMeta("육아휴직",         "leave", False, False,  0,  0,  "FCE4EC"),
    ShiftType.X:   ShiftMeta("사용X",            "limit", False, False,  0,  0,  "BDBDBD"),
    ShiftType.XV:  ShiftMeta("무급휴직",         "leave", False, False,  0,  0,  "F5F5F5"),
    ShiftType.HXV: ShiftMeta("무급휴직반차",     "leave", False, False,  0,  0,  "FAFAFA"),
    ShiftType.MV:  ShiftMeta("한달 이상 휴가",   "leave", False, False,  0,  0,  "E8EAF6"),
    # 교육 ─────────────────────────────────────
    ShiftType.T:   ShiftMeta("전일 교육",        "edu",   False, False,  0,  0,  "FFF9C4"),
    ShiftType.TH:  ShiftMeta("반일 교육",        "edu",   False, False,  0,  0,  "FFFDE7"),
    # 병가 ─────────────────────────────────────
    ShiftType.I:   ShiftMeta("병가",             "sick",  False, False,  0,  0,  "FFCDD2"),
    ShiftType.IH:  ShiftMeta("병가(반휴)",       "sick",  False, False,  0,  0,  "FFEBEE"),
    # 제한 ─────────────────────────────────────
    ShiftType.S:   ShiftMeta("사용금지",         "limit", False, False,  0,  0,  "757575"),
    ShiftType.S1:  ShiftMeta("사용금지1",        "limit", False, False,  0,  0,  "9E9E9E"),
    ShiftType.K:   ShiftMeta("사용금지",         "limit", False, False,  0,  0,  "616161"),
    # 시스템 내부 ──────────────────────────────
    ShiftType.OFF: ShiftMeta("미배정",           "off",   False, False,  0,  0,  "EFEFEF"),
}

# ── 편의 집합 (자주 쓰는 분류) ─────────────────

# 스케줄러가 자동 배정할 수 있는 근무 유형
ASSIGNABLE_SHIFTS: FrozenSet[ShiftType] = frozenset({
    ShiftType.D, ShiftType.E, ShiftType.N,
    ShiftType.N7, ShiftType.DE,
    ShiftType.M, ShiftType.C,
    ShiftType.S9, ShiftType.S10, ShiftType.S11,
    ShiftType.DF, ShiftType.A,
    ShiftType.HD, ShiftType.HE, ShiftType.HN,
    ShiftType.CC, ShiftType.KC, ShiftType.CH,
})

# 근무일수에 포함되는 유형
WORK_SHIFTS: FrozenSet[ShiftType] = frozenset(
    s for s, m in SHIFT_META.items() if m.is_work
)

# 야간 유형 (다음날 휴식이 필요)
NIGHT_SHIFTS: FrozenSet[ShiftType] = frozenset(
    s for s, m in SHIFT_META.items() if m.is_night
)

# 비근무(휴무/휴가/병가/교육 등)
OFF_SHIFTS: FrozenSet[ShiftType] = frozenset(
    s for s, m in SHIFT_META.items() if not m.is_work
)

# 고정 OFF 처리할 코드 (연차·병가·교육·제한)
FORCED_OFF_SHIFTS: FrozenSet[ShiftType] = frozenset({
    ShiftType.Y, ShiftType.YH, ShiftType.G, ShiftType.GH,
    ShiftType.KV, ShiftType.DV, ShiftType.IV,
    ShiftType.X, ShiftType.XV, ShiftType.HXV, ShiftType.MV,
    ShiftType.T, ShiftType.TH,
    ShiftType.I, ShiftType.IH,
    ShiftType.S, ShiftType.S1, ShiftType.K,
})

# 카테고리 → ShiftType 목록
SHIFTS_BY_CATEGORY: Dict[str, List[ShiftType]] = {}
for _s, _m in SHIFT_META.items():
    SHIFTS_BY_CATEGORY.setdefault(_m.category, []).append(_s)


def get_shift_label(shift: ShiftType) -> str:
    """근무 코드 → 한국어 명칭."""
    return SHIFT_META[shift].label if shift in SHIFT_META else shift.value


def shift_rest_gap(from_shift: ShiftType, to_shift: ShiftType) -> int:
    """
    두 근무 사이 휴식 시간(시간) 계산.
    end_h > 24 인 경우 익일 시간으로 처리.
    """
    if from_shift not in SHIFT_META or to_shift not in SHIFT_META:
        return 99
    end_h   = SHIFT_META[from_shift].end_h
    start_h = SHIFT_META[to_shift].start_h
    gap = start_h + 24 - end_h if start_h < (end_h % 24) else start_h - end_h
    return max(gap, 0)


# ──────────────────────────────────────────────
# 경력 / 병동 Enum
# ──────────────────────────────────────────────

class SkillLevel(str, Enum):
    NEW     = "신규"   # 1년 미만
    GENERAL = "일반"  # 1~5년
    SENIOR  = "숙련"  # 5년 이상


class WardType(str, Enum):
    GENERAL   = "일반"
    ICU       = "중환자실"
    INFECTION = "감염"
    EMERGENCY = "응급"
    PEDIATRIC = "소아과"
    SURGICAL  = "외과"


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
        ..., description="근무 가능 병동 목록",
    )
    allowed_shifts: List[ShiftType] = Field(
        default_factory=lambda: [ShiftType.D, ShiftType.E, ShiftType.N],
        description="배정 가능 근무 유형",
    )
    preference: NursePreference = Field(default_factory=NursePreference)
    is_part_time: bool = Field(default=False, description="파트타임 여부")

    @model_validator(mode="after")
    def _clean_allowed_shifts(self) -> "Nurse":
        # 비근무 코드는 allowed_shifts 에서 제거 (시스템 자동 부여)
        self.allowed_shifts = [
            s for s in self.allowed_shifts if s in ASSIGNABLE_SHIFTS
        ]
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
        default=5, ge=1, le=14, description="최대 연속 근무일수",
    )
    night_rest_required: bool = Field(
        default=True, description="야간 근무(N/N7/C/A 등) 후 다음날 반드시 OFF",
    )
    max_consecutive_nights: int = Field(
        default=3, ge=1, le=7, description="최대 연속 야간 근무 횟수",
    )
    min_rest_hours_between_shifts: int = Field(
        default=11, description="교대 간 최소 휴식 시간(시간 단위)",
    )

    # ── Shift별 인원 요건 (기본: D/E/N 3가지)
    shift_requirements: Dict[ShiftType, ShiftRequirement] = Field(
        default_factory=lambda: {
            ShiftType.D: ShiftRequirement(min_nurses=4, min_senior_nurses=1),
            ShiftType.E: ShiftRequirement(min_nurses=3, min_senior_nurses=1),
            ShiftType.N: ShiftRequirement(min_nurses=2, min_senior_nurses=1),
        }
    )

    # ── Soft 최적화 가중치
    fairness_weight_night: float = Field(default=1.0, ge=0, le=5)
    fairness_weight_weekend: float = Field(default=1.0, ge=0, le=5)
    fairness_weight_holiday: float = Field(default=1.5, ge=0, le=5)
    preference_satisfaction_rate: float = Field(default=0.7, ge=0, le=1)
    target_work_days_per_month: Optional[int] = Field(default=None)


# ──────────────────────────────────────────────
# 고정 일정 (연차/교육/병가 등)
# ──────────────────────────────────────────────

class FixedScheduleType(str, Enum):
    ANNUAL_LEAVE  = "연차"
    HALF_LEAVE    = "연차반휴"
    OFFICIAL_LEAVE = "공가"
    CONGRATULATORY = "경조휴가"
    MATERNITY     = "분만휴가"
    PARENTAL      = "육아휴직"
    UNPAID_LEAVE  = "무급휴직"
    LONG_LEAVE    = "한달이상휴가"
    EDUCATION     = "전일교육"
    HALF_EDUCATION = "반일교육"
    SICK_LEAVE    = "병가"
    HALF_SICK     = "병가반휴"
    SPECIAL_LEAVE = "특별휴가"

    @property
    def shift_code(self) -> ShiftType:
        """고정 일정 유형 → 해당 ShiftType 코드 매핑."""
        _map = {
            "연차":         ShiftType.Y,
            "연차반휴":     ShiftType.YH,
            "공가":         ShiftType.G,
            "경조휴가":     ShiftType.KV,
            "분만휴가":     ShiftType.DV,
            "육아휴직":     ShiftType.IV,
            "무급휴직":     ShiftType.XV,
            "한달이상휴가": ShiftType.MV,
            "전일교육":     ShiftType.T,
            "반일교육":     ShiftType.TH,
            "병가":         ShiftType.I,
            "병가반휴":     ShiftType.IH,
            "특별휴가":     ShiftType.KV,
        }
        return _map.get(self.value, ShiftType.O)


class FixedSchedule(BaseModel):
    """사전 확정된 개인 일정."""

    nurse_id: str
    date: datetime.date
    schedule_type: FixedScheduleType
    note: str = ""

    @property
    def shift_code(self) -> ShiftType:
        return self.schedule_type.shift_code


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
        description="수동 고정 셀 — 재생성 시 유지",
    )
    is_holiday: bool = False
    is_weekend: bool = False
    note: str = ""

    @property
    def is_work(self) -> bool:
        return self.shift in WORK_SHIFTS

    @property
    def label(self) -> str:
        return get_shift_label(self.shift)


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
        """nurse_id → {date → ShiftType} 딕셔너리."""
        matrix: Dict[str, Dict[datetime.date, ShiftType]] = {n.id: {} for n in nurses}
        for entry in self.entries:
            if entry.nurse_id in matrix:
                matrix[entry.nurse_id][entry.date] = entry.shift
        return matrix


# ──────────────────────────────────────────────
# 병동별 특수 설정
# ──────────────────────────────────────────────

class WardSpecialSettings(BaseModel):
    """병동별 특수성 설정."""

    require_ward_qualification: bool = Field(
        default=True,
        description="병동 자격이 있는 간호사만 배정 (ward_qualifications 필터)",
    )
    min_skill_level: Optional[SkillLevel] = Field(
        default=None,
        description="최소 경력 수준 (None=제한 없음)",
    )
    senior_night_required: bool = Field(
        default=True,
        description="야간 근무에 숙련 간호사 1명 이상 필요",
    )
    allow_sprint_shifts: bool = Field(
        default=True,
        description="스프린트 근무(S9/S10/S11) 허용 여부",
    )
    weekend_min_nurses: int = Field(
        default=2,
        ge=0,
        description="주말 최소 근무 인원",
    )
    nurse_patient_ratio: float = Field(
        default=0.167,
        description="간호사:환자 비율 (기본 1:6 = 0.167)",
    )


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
    country_code: str = Field(default="KR")
    previous_schedule: Optional[Schedule] = Field(default=None)
    locked_entries: List[ScheduleEntry] = Field(default_factory=list)
    ward_settings: WardSpecialSettings = Field(default_factory=WardSpecialSettings)

    @property
    def nurse_map(self) -> Dict[str, Nurse]:
        return {n.id: n for n in self.nurses}

    @property
    def fixed_set(self) -> Set[Tuple]:
        """(nurse_id, date) 고정 집합."""
        return {(f.nurse_id, f.date) for f in self.fixed_schedules}
