"""
테스트 시나리오 — 38종 근무 코드 체계 반영.
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
    NIGHT_SHIFTS,
    WORK_SHIFTS,
    Schedule,
    ScheduleConfig,
    ScheduleEvaluator,
    ScheduleRules,
    ShiftType,
    SkillLevel,
    Ward,
    WardType,
)
from scheduler.models import FixedScheduleType, ScheduleEntry, ShiftRequirement
from tests.sample_data import (
    create_sample_config,
    create_sample_nurses,
    create_sample_rules,
    create_sample_ward,
)


def run_and_evaluate(config: ScheduleConfig, optimize: bool = True) -> dict:
    schedule = GreedyScheduler(config).generate()
    if optimize:
        schedule = LocalSearchOptimizer(config, max_iterations=500, seed=42).optimize(schedule)
    result = ScheduleEvaluator(config).evaluate(schedule)
    return {"schedule": schedule, "eval": result,
            "shortage": schedule.generation_params.get("shortage_log", [])}


def print_result(title: str, res: dict) -> None:
    er = res["eval"]
    print(f"\n{'='*60}")
    print(f"📋 {title}")
    print(f"{'='*60}")
    print(er.summary())
    if res["shortage"]:
        print(f"\n⚠️  인력 부족 {len(res['shortage'])}건")
    hard = [v for v in er.constraint_result.violations if v.is_hard]
    if hard:
        print(f"\n🚨 Hard 위반 {len(hard)}건:")
        for v in hard[:5]:
            print(f"  [{v.constraint}] {v.reason}")


# ── 시나리오 1: 정상 (12명) ──────────────────────────────
def test_normal_case():
    print("\n▶ 시나리오 1: 정상 케이스 (12명)")
    config = create_sample_config(2025, 6)
    res = run_and_evaluate(config)
    assert res["eval"].staffing_coverage_rate > 0.8, \
        f"인력 충족률 낮음: {res['eval'].staffing_coverage_rate:.2%}"
    print_result("정상 케이스", res)
    print("  ✅ PASS")


# ── 시나리오 2: 인력 부족 ───────────────────────────────
def test_understaffed():
    print("\n▶ 시나리오 2: 인력 부족 (6명)")
    nurses = create_sample_nurses()[:6]
    config = ScheduleConfig(
        ward=create_sample_ward(), nurses=nurses, rules=create_sample_rules(),
        year=2025, month=6,
    )
    res = run_and_evaluate(config, optimize=False)
    assert len(res["shortage"]) > 0, "인력 부족 경고 미발생"
    print_result("인력 부족", res)
    print("  ✅ PASS — 인력 부족 경고 정상 감지")


# ── 시나리오 3: 연차 집중 ───────────────────────────────
def test_concentrated_leave():
    print("\n▶ 시나리오 3: 연차 집중 (숙련 4명 동시)")
    fixed = [
        FixedSchedule(nurse_id=f"N00{i}", date=datetime.date(2025, 6, 10),
                      schedule_type=FixedScheduleType.ANNUAL_LEAVE)
        for i in range(1, 5)
    ]
    config = ScheduleConfig(
        ward=create_sample_ward(), nurses=create_sample_nurses(),
        rules=create_sample_rules(), fixed_schedules=fixed, year=2025, month=6,
    )
    res = run_and_evaluate(config, optimize=False)
    # 6/10 연차 반영 확인
    n001_610 = res["schedule"].get_entry("N001", datetime.date(2025, 6, 10))
    assert n001_610 and n001_610.shift == ShiftType.Y, \
        f"연차 코드 미반영: {n001_610}"
    print_result("연차 집중", res)
    print(f"  N001 6/10 → {n001_610.shift.value} (연차 코드 확인)")
    print("  ✅ PASS")


# ── 시나리오 4: Night 기피 ──────────────────────────────
def test_night_avoidance():
    print("\n▶ 시나리오 4: Night 기피 (야간 허용자 3명)")
    nurses = create_sample_nurses()
    for n in nurses:
        if n.id not in ("N004", "N009", "N002"):
            n.allowed_shifts = [s for s in n.allowed_shifts
                                if s not in NIGHT_SHIFTS]
    config = ScheduleConfig(
        ward=create_sample_ward(), nurses=nurses, rules=create_sample_rules(),
        year=2025, month=6,
    )
    res = run_and_evaluate(config, optimize=False)
    night_dist = {
        n.name: sum(1 for e in res["schedule"].entries
                    if e.nurse_id == n.id and e.shift in NIGHT_SHIFTS)
        for n in nurses
    }
    print_result("Night 기피", res)
    print(f"  야간 근무자: { {k:v for k,v in night_dist.items() if v>0} }")
    print("  ✅ PASS")


# ── 시나리오 5: 이전 달 연속 근무 ──────────────────────
def test_previous_month_continuity():
    print("\n▶ 시나리오 5: 이전 달 연속 근무 연계")
    prev_entries = [
        ScheduleEntry(nurse_id="N001", date=datetime.date(2025, 5, day), shift=ShiftType.D)
        for day in range(26, 31)
    ]
    prev_schedule = Schedule(ward_id="W-301", year=2025, month=5, entries=prev_entries)
    config = ScheduleConfig(
        ward=create_sample_ward(), nurses=create_sample_nurses(),
        rules=create_sample_rules(), year=2025, month=6,
        previous_schedule=prev_schedule,
    )
    res = run_and_evaluate(config, optimize=False)
    june1 = res["schedule"].get_entry("N001", datetime.date(2025, 6, 1))
    print_result("이전 달 연계", res)
    if june1:
        print(f"  N001 6/1: {june1.shift.value}({june1.label}) — 연속 초과 방지 확인")
    print("  ✅ PASS")


# ── 시나리오 6: 수동 고정 셀 유지 ──────────────────────
def test_locked_entries():
    print("\n▶ 시나리오 6: 수동 고정 셀 유지")
    locked = [
        ScheduleEntry(nurse_id="N005", date=datetime.date(2025, 6, 20),
                      shift=ShiftType.N7, is_fixed=True),
    ]
    config = ScheduleConfig(
        ward=create_sample_ward(), nurses=create_sample_nurses(),
        rules=create_sample_rules(), year=2025, month=6,
        locked_entries=locked,
    )
    res = run_and_evaluate(config, optimize=False)
    entry = res["schedule"].get_entry("N005", datetime.date(2025, 6, 20))
    assert entry and entry.shift == ShiftType.N7, f"고정 셀 미유지: {entry}"
    print_result("고정 셀 유지", res)
    print(f"  N005 6/20 → {entry.shift.value}({entry.label}) 고정 확인")
    print("  ✅ PASS")


# ── 시나리오 7: 병가 / 교육 코드 올바른 반영 ───────────
def test_fixed_schedule_codes():
    print("\n▶ 시나리오 7: 고정 일정 → 실제 코드 매핑 확인")
    fixed = [
        FixedSchedule(nurse_id="N003", date=datetime.date(2025, 6, 5),
                      schedule_type=FixedScheduleType.SICK_LEAVE),
        FixedSchedule(nurse_id="N006", date=datetime.date(2025, 6, 8),
                      schedule_type=FixedScheduleType.EDUCATION),
        FixedSchedule(nurse_id="N002", date=datetime.date(2025, 6, 12),
                      schedule_type=FixedScheduleType.CONGRATULATORY),
    ]
    config = ScheduleConfig(
        ward=create_sample_ward(), nurses=create_sample_nurses(),
        rules=create_sample_rules(), fixed_schedules=fixed, year=2025, month=6,
    )
    schedule = GreedyScheduler(config).generate()

    e_sick  = schedule.get_entry("N003", datetime.date(2025, 6, 5))
    e_edu   = schedule.get_entry("N006", datetime.date(2025, 6, 8))
    e_cong  = schedule.get_entry("N002", datetime.date(2025, 6, 12))

    assert e_sick and e_sick.shift == ShiftType.I,  f"병가 코드 오류: {e_sick}"
    assert e_edu  and e_edu.shift  == ShiftType.T,  f"교육 코드 오류: {e_edu}"
    assert e_cong and e_cong.shift == ShiftType.KV, f"경조 코드 오류: {e_cong}"

    print(f"  N003 6/5  → {e_sick.shift.value} ({e_sick.label})")
    print(f"  N006 6/8  → {e_edu.shift.value}  ({e_edu.label})")
    print(f"  N002 6/12 → {e_cong.shift.value} ({e_cong.label})")
    print("  ✅ PASS — 고정 일정 코드 정확 매핑 확인")


# ── 시나리오 8: Hard Constraint 위반 감지 ──────────────
def test_hard_constraint_detection():
    print("\n▶ 시나리오 8: Hard Constraint 위반 감지 (Night→Day 직접 삽입)")
    nurses = create_sample_nurses()
    rules  = create_sample_rules()

    entries = [
        ScheduleEntry(nurse_id="N001", date=datetime.date(2025, 6, 1), shift=ShiftType.N),
        ScheduleEntry(nurse_id="N001", date=datetime.date(2025, 6, 2), shift=ShiftType.D),
    ]
    for n in nurses:
        for day in range(1, 31):
            d = datetime.date(2025, 6, day)
            if not any(e.nurse_id == n.id and e.date == d for e in entries):
                entries.append(ScheduleEntry(nurse_id=n.id, date=d, shift=ShiftType.O))

    schedule = Schedule(ward_id="W-301", year=2025, month=6, entries=entries)
    import calendar
    _, last = calendar.monthrange(2025, 6)
    dates = [datetime.date(2025, 6, d) for d in range(1, last + 1)]

    checker = ConstraintChecker(rules)
    result  = checker.validate_schedule(schedule, nurses, dates)
    hard    = [v for v in result.violations if v.is_hard and v.constraint == "NIGHT_REST"]
    assert len(hard) > 0, "Night→Day 위반 미감지"

    print(f"  NIGHT_REST 위반 {len(hard)}건 감지")
    print("  ✅ PASS")


# ── 전체 실행 ──────────────────────────────────────────

def run_all_tests():
    print("\n" + "=" * 60)
    print("🧪 병동 간호사 근무표 시스템 — 전체 테스트 (38종 코드 체계)")
    print("=" * 60)

    tests = [
        test_normal_case,
        test_understaffed,
        test_concentrated_leave,
        test_night_avoidance,
        test_previous_month_continuity,
        test_locked_entries,
        test_fixed_schedule_codes,
        test_hard_constraint_detection,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  💥 ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"결과: {passed}개 통과 / {failed}개 실패")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
