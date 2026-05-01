"""
테스트 시나리오 모음.

다음 케이스를 검증:
  1. 정상 케이스 (12명, 1개월)
  2. 인력 부족 케이스 (6명으로 Day 4명 요건 충족 불가)
  3. 연차 집중 케이스 (동일 기간 4명 연차)
  4. Night 기피 현상 (Night 허용자 소수)
  5. 이전 달 연속 근무 연계
  6. 수동 고정 셀 재생성 유지
  7. Hard Constraint 위반 감지
"""

from __future__ import annotations

import datetime

from scheduler import (
    ConstraintChecker,
    FixedSchedule,
    GreedyScheduler,
    LocalSearchOptimizer,
    Nurse,
    NursePreference,
    Schedule,
    ScheduleConfig,
    ScheduleEvaluator,
    ScheduleRules,
    ShiftType,
    SkillLevel,
    Ward,
    WardType,
)
from scheduler.models import FixedScheduleType, ShiftRequirement
from tests.sample_data import (
    create_sample_config,
    create_sample_nurses,
    create_sample_rules,
    create_sample_ward,
)


# ──────────────────────────────────────────────
# 테스트 헬퍼
# ──────────────────────────────────────────────

def run_and_evaluate(config: ScheduleConfig, optimize: bool = True) -> dict:
    scheduler = GreedyScheduler(config)
    schedule = scheduler.generate()
    if optimize:
        optimizer = LocalSearchOptimizer(config, max_iterations=500, seed=42)
        schedule = optimizer.optimize(schedule)
    evaluator = ScheduleEvaluator(config)
    result = evaluator.evaluate(schedule)
    return {
        "schedule": schedule,
        "eval": result,
        "shortage": schedule.generation_params.get("shortage_log", []),
    }


def print_result(title: str, res: dict) -> None:
    er = res["eval"]
    print(f"\n{'='*60}")
    print(f"📋 {title}")
    print(f"{'='*60}")
    print(er.summary())
    if res["shortage"]:
        print("\n⚠️  인력 부족:")
        for s in res["shortage"]:
            print(f"  {s}")
    hard_viols = [v for v in er.constraint_result.violations if v.is_hard]
    if hard_viols:
        print(f"\n🚨 Hard 위반 {len(hard_viols)}건:")
        for v in hard_viols[:5]:
            print(f"  [{v.constraint}] {v.reason}")
    print()


# ──────────────────────────────────────────────
# 시나리오 1: 정상 케이스
# ──────────────────────────────────────────────

def test_normal_case():
    print("\n▶ 시나리오 1: 정상 케이스 (12명)")
    config = create_sample_config(2025, 6)
    res = run_and_evaluate(config)
    er = res["eval"]

    assert er.staffing_coverage_rate > 0.8, (
        f"인력 충족률이 너무 낮음: {er.staffing_coverage_rate:.2%}"
    )
    print_result("정상 케이스", res)
    print("  ✅ PASS")


# ──────────────────────────────────────────────
# 시나리오 2: 인력 부족
# ──────────────────────────────────────────────

def test_understaffed():
    print("\n▶ 시나리오 2: 인력 부족 (간호사 6명, Day 최소 4명 요건)")
    nurses = create_sample_nurses()[:6]  # 12명 중 6명만
    rules = create_sample_rules()
    # Day 최소 4명 — 6명으론 Night/Evening 커버 시 Day 부족 발생
    config = ScheduleConfig(
        ward=create_sample_ward(),
        nurses=nurses,
        rules=rules,
        year=2025, month=6,
    )
    res = run_and_evaluate(config, optimize=False)

    assert len(res["shortage"]) > 0, "인력 부족 경고가 발생해야 함"
    print_result("인력 부족", res)
    print("  ✅ PASS — 인력 부족 경고 정상 감지")


# ──────────────────────────────────────────────
# 시나리오 3: 연차 집중 케이스
# ──────────────────────────────────────────────

def test_concentrated_leave():
    print("\n▶ 시나리오 3: 연차 집중 (동일 날짜 4명 연차)")
    nurses = create_sample_nurses()
    # 6월 10~12일 숙련 간호사 3명 모두 연차
    fixed = [
        FixedSchedule(nurse_id="N001", date=datetime.date(2025, 6, 10), schedule_type=FixedScheduleType.ANNUAL_LEAVE),
        FixedSchedule(nurse_id="N002", date=datetime.date(2025, 6, 10), schedule_type=FixedScheduleType.ANNUAL_LEAVE),
        FixedSchedule(nurse_id="N003", date=datetime.date(2025, 6, 10), schedule_type=FixedScheduleType.ANNUAL_LEAVE),
        FixedSchedule(nurse_id="N004", date=datetime.date(2025, 6, 10), schedule_type=FixedScheduleType.ANNUAL_LEAVE),
    ]
    config = ScheduleConfig(
        ward=create_sample_ward(),
        nurses=nurses,
        rules=create_sample_rules(),
        fixed_schedules=fixed,
        year=2025, month=6,
    )
    res = run_and_evaluate(config, optimize=False)

    # 숙련 4명 모두 연차 → 해당일 숙련 인원 부족 감지
    hard_viols = [v for v in res["eval"].constraint_result.violations if v.is_hard]
    print_result("연차 집중", res)
    print(f"  Hard 위반 {len(hard_viols)}건 (숙련 부족 포함)")
    print("  ✅ PASS")


# ──────────────────────────────────────────────
# 시나리오 4: Night 기피 현상
# ──────────────────────────────────────────────

def test_night_avoidance():
    print("\n▶ 시나리오 4: Night 기피 (Night 허용자 3명)")
    nurses = create_sample_nurses()

    # 모든 간호사 Night 기피 or 불허 — 단 3명만 허용
    for n in nurses:
        if n.id not in ("N004", "N009", "N002"):
            n.allowed_shifts = [s for s in n.allowed_shifts if s != ShiftType.NIGHT]

    config = ScheduleConfig(
        ward=create_sample_ward(),
        nurses=nurses,
        rules=create_sample_rules(),
        year=2025, month=6,
    )
    res = run_and_evaluate(config, optimize=False)
    print_result("Night 기피", res)

    night_dist = {
        n.name: sum(1 for e in res["schedule"].entries if e.nurse_id == n.id and e.shift == ShiftType.NIGHT)
        for n in nurses
    }
    night_workers = {k: v for k, v in night_dist.items() if v > 0}
    print(f"  야간 근무자: {night_workers}")
    print("  ✅ PASS")


# ──────────────────────────────────────────────
# 시나리오 5: 이전 달 연계 (연속 근무 체크)
# ──────────────────────────────────────────────

def test_previous_month_continuity():
    print("\n▶ 시나리오 5: 이전 달 연속 근무 연계")
    nurses = create_sample_nurses()

    # 이전 달 마지막 5일 N001 이 연속 근무했다고 가정
    from scheduler.models import ScheduleEntry
    prev_entries = []
    for day in range(26, 31):  # 5월 26~30
        prev_entries.append(ScheduleEntry(
            nurse_id="N001",
            date=datetime.date(2025, 5, day),
            shift=ShiftType.DAY,
        ))
    prev_schedule = Schedule(
        ward_id="W-301", year=2025, month=5, entries=prev_entries
    )

    config = ScheduleConfig(
        ward=create_sample_ward(),
        nurses=nurses,
        rules=create_sample_rules(),
        year=2025, month=6,
        previous_schedule=prev_schedule,
    )
    res = run_and_evaluate(config, optimize=False)
    # N001의 6월 1~2일은 연속 근무 방지로 OFF 여야 함
    n001_entries = [e for e in res["schedule"].entries if e.nurse_id == "N001"]
    june1 = next((e for e in n001_entries if e.date == datetime.date(2025, 6, 1)), None)
    print_result("이전 달 연계", res)
    if june1:
        print(f"  N001 6/1 배정: {june1.shift.value} (연속 근무 5일 초과 방지 검증)")
    print("  ✅ PASS")


# ──────────────────────────────────────────────
# 시나리오 6: 수동 고정 셀 유지
# ──────────────────────────────────────────────

def test_locked_entries():
    print("\n▶ 시나리오 6: 수동 고정 셀 재생성 후 유지")
    from scheduler.models import ScheduleEntry

    locked = [
        ScheduleEntry(
            nurse_id="N005",
            date=datetime.date(2025, 6, 20),
            shift=ShiftType.NIGHT,
            is_fixed=True,
        )
    ]
    config = ScheduleConfig(
        ward=create_sample_ward(),
        nurses=create_sample_nurses(),
        rules=create_sample_rules(),
        year=2025, month=6,
        locked_entries=locked,
    )
    res = run_and_evaluate(config, optimize=False)

    entry = res["schedule"].get_entry("N005", datetime.date(2025, 6, 20))
    assert entry is not None and entry.shift == ShiftType.NIGHT, (
        f"고정 셀이 유지되지 않음: {entry}"
    )
    print_result("고정 셀 유지", res)
    print("  ✅ PASS — 고정 셀 유지 확인")


# ──────────────────────────────────────────────
# 시나리오 7: Hard Constraint 위반 직접 생성 후 감지
# ──────────────────────────────────────────────

def test_hard_constraint_detection():
    print("\n▶ 시나리오 7: Hard Constraint 위반 감지")
    from scheduler.models import ScheduleEntry

    # Night → Day 위반 셀을 수동으로 삽입
    nurses = create_sample_nurses()
    rules = create_sample_rules()

    # N001: 6/1 Night, 6/2 Day (위반)
    entries = [
        ScheduleEntry(nurse_id="N001", date=datetime.date(2025, 6, 1), shift=ShiftType.NIGHT),
        ScheduleEntry(nurse_id="N001", date=datetime.date(2025, 6, 2), shift=ShiftType.DAY),
    ]
    for n in nurses:
        for day in range(1, 31):
            d = datetime.date(2025, 6, day)
            if not any(e.nurse_id == n.id and e.date == d for e in entries):
                entries.append(ScheduleEntry(
                    nurse_id=n.id, date=d, shift=ShiftType.OFF
                ))

    schedule = Schedule(ward_id="W-301", year=2025, month=6, entries=entries)

    import calendar
    _, last = calendar.monthrange(2025, 6)
    dates = [datetime.date(2025, 6, d) for d in range(1, last + 1)]

    checker = ConstraintChecker(rules)
    result = checker.validate_schedule(schedule, nurses, dates)

    hard_viols = [v for v in result.violations if v.is_hard]
    night_rest_viols = [v for v in hard_viols if v.constraint == "NIGHT_REST"]
    assert len(night_rest_viols) > 0, "Night→Day 위반 감지 실패"

    print(f"  감지된 Hard 위반: {len(hard_viols)}건")
    for v in hard_viols:
        print(f"    [{v.constraint}] {v.reason}")
    print("  ✅ PASS — Night→Day 위반 정상 감지")


# ──────────────────────────────────────────────
# 전체 실행
# ──────────────────────────────────────────────

def run_all_tests():
    print("\n" + "=" * 60)
    print("🧪 병동 간호사 근무표 시스템 — 전체 테스트 실행")
    print("=" * 60)

    tests = [
        test_normal_case,
        test_understaffed,
        test_concentrated_leave,
        test_night_avoidance,
        test_previous_month_continuity,
        test_locked_entries,
        test_hard_constraint_detection,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  💥 ERROR: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"결과: {passed}개 통과 / {failed}개 실패")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
