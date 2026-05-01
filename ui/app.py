"""
병동 간호사 근무표 자동 생성 시스템 — Streamlit UI.

화면 구성:
  1. 사이드바  : 근무 규칙 설정 (슬라이더, 체크박스)
  2. 탭 1      : 근무표 Grid (Excel 스타일, 수동 편집 가능)
  3. 탭 2      : 평가 대시보드 (차트, Heatmap)
  4. 탭 3      : 간호사 관리 (추가/편집)
  5. 탭 4      : 고정 일정 관리 (연차/병가/교육)

실행: streamlit run ui/app.py
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

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
    ScheduleExporter,
    ScheduleRules,
    ShiftType,
    SkillLevel,
    Ward,
    WardType,
)
from scheduler.models import (
    FixedScheduleType,
    ShiftRequirement,
)
from tests.sample_data import (
    create_sample_config,
    create_sample_nurses,
    create_sample_ward,
)

# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="🏥 간호사 근무표 시스템",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# CSS 스타일
# ──────────────────────────────────────────────

st.markdown(
    """
<style>
    .shift-D  { background:#B8E4F9; padding:2px 6px; border-radius:4px; font-weight:600; }
    .shift-E  { background:#FFD966; padding:2px 6px; border-radius:4px; font-weight:600; }
    .shift-N  { background:#9FC5E8; padding:2px 6px; border-radius:4px; font-weight:600; color:#fff; }
    .shift-OFF{ background:#EFEFEF; padding:2px 6px; border-radius:4px; color:#aaa; }
    .metric-card { background:#f0f2f6; padding:12px; border-radius:8px; text-align:center; }
    .violation-hard { color:#ff4444; font-weight:600; }
    .violation-soft { color:#ff8800; }
</style>
""",
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Session State 초기화
# ──────────────────────────────────────────────

def _init_state() -> None:
    if "nurses" not in st.session_state:
        st.session_state.nurses = create_sample_nurses()
    if "ward" not in st.session_state:
        st.session_state.ward = create_sample_ward()
    if "schedule" not in st.session_state:
        st.session_state.schedule = None
    if "eval_result" not in st.session_state:
        st.session_state.eval_result = None
    if "fixed_schedules" not in st.session_state:
        st.session_state.fixed_schedules: list[FixedSchedule] = []
    if "locked_entries" not in st.session_state:
        st.session_state.locked_entries = []
    if "year" not in st.session_state:
        today = datetime.date.today()
        st.session_state.year = today.year
    if "month" not in st.session_state:
        today = datetime.date.today()
        st.session_state.month = today.month


_init_state()


# ──────────────────────────────────────────────
# 사이드바: 규칙 설정
# ──────────────────────────────────────────────

def render_sidebar() -> ScheduleRules:
    st.sidebar.title("⚙️ 근무 규칙 설정")

    st.sidebar.subheader("📅 대상 기간")
    col1, col2 = st.sidebar.columns(2)
    st.session_state.year = col1.number_input(
        "연도", value=st.session_state.year, min_value=2020, max_value=2030, step=1
    )
    st.session_state.month = col2.number_input(
        "월", value=st.session_state.month, min_value=1, max_value=12, step=1
    )

    st.sidebar.divider()
    st.sidebar.subheader("🔒 Hard Constraint")

    max_consec = st.sidebar.slider(
        "최대 연속 근무일", min_value=3, max_value=10, value=5
    )
    night_rest = st.sidebar.checkbox("Night 후 다음날 OFF 강제", value=True)
    max_nights = st.sidebar.slider(
        "최대 연속 Night 횟수", min_value=1, max_value=7, value=3
    )
    min_rest_h = st.sidebar.slider(
        "교대 간 최소 휴식(시간)", min_value=8, max_value=16, value=11
    )

    st.sidebar.divider()
    st.sidebar.subheader("👥 Shift 최소 인원")

    d_min = st.sidebar.number_input("Day 최소 인원", value=4, min_value=1, max_value=20)
    d_snr = st.sidebar.number_input("Day 최소 숙련", value=1, min_value=0, max_value=10)
    e_min = st.sidebar.number_input("Evening 최소 인원", value=3, min_value=1, max_value=20)
    e_snr = st.sidebar.number_input("Evening 최소 숙련", value=1, min_value=0, max_value=10)
    n_min = st.sidebar.number_input("Night 최소 인원", value=2, min_value=1, max_value=20)
    n_snr = st.sidebar.number_input("Night 최소 숙련", value=1, min_value=0, max_value=10)

    st.sidebar.divider()
    st.sidebar.subheader("⚖️ Soft Constraint 가중치")

    w_night = st.sidebar.slider("야간 공정성 가중치", 0.0, 5.0, 1.0, 0.1)
    w_weekend = st.sidebar.slider("주말 공정성 가중치", 0.0, 5.0, 1.0, 0.1)
    w_holiday = st.sidebar.slider("공휴일 공정성 가중치", 0.0, 5.0, 1.5, 0.1)
    pref_rate = st.sidebar.slider(
        "개인 선호 반영 목표 (%)", 0, 100, 70, 5
    ) / 100

    return ScheduleRules(
        max_consecutive_work_days=max_consec,
        night_rest_required=night_rest,
        max_consecutive_nights=max_nights,
        min_rest_hours_between_shifts=min_rest_h,
        shift_requirements={
            ShiftType.DAY:     ShiftRequirement(min_nurses=d_min, min_senior_nurses=d_snr),
            ShiftType.EVENING: ShiftRequirement(min_nurses=e_min, min_senior_nurses=e_snr),
            ShiftType.NIGHT:   ShiftRequirement(min_nurses=n_min, min_senior_nurses=n_snr),
        },
        fairness_weight_night=w_night,
        fairness_weight_weekend=w_weekend,
        fairness_weight_holiday=w_holiday,
        preference_satisfaction_rate=pref_rate,
    )


# ──────────────────────────────────────────────
# 탭 1: 근무표 생성 & Grid
# ──────────────────────────────────────────────

def render_schedule_tab(rules: ScheduleRules) -> None:
    st.header("📋 근무표")

    col_gen, col_opt, col_exp = st.columns([2, 2, 2])

    with col_gen:
        if st.button("🚀 근무표 자동 생성", type="primary", use_container_width=True):
            _run_generation(rules, optimize=False)

    with col_opt:
        if st.button("✨ 생성 + 최적화", use_container_width=True):
            _run_generation(rules, optimize=True)

    with col_exp:
        if st.session_state.schedule:
            exporter = ScheduleExporter(st.session_state.nurses)
            excel_bytes = exporter.to_excel(st.session_state.schedule)
            st.download_button(
                "📥 Excel 다운로드",
                data=excel_bytes,
                file_name=f"schedule_{st.session_state.year}_{st.session_state.month:02d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    # Excel 업로드
    uploaded = st.file_uploader(
        "📤 Excel/CSV 업로드 (기존 근무표 불러오기)", type=["xlsx", "csv"]
    )
    if uploaded:
        exporter = ScheduleExporter(st.session_state.nurses)
        try:
            if uploaded.name.endswith(".xlsx"):
                sched = exporter.from_excel(
                    uploaded.read(),
                    st.session_state.ward.id,
                    st.session_state.year,
                    st.session_state.month,
                )
            else:
                sched = exporter.from_csv(
                    uploaded.read().decode("utf-8-sig"),
                    st.session_state.ward.id,
                    st.session_state.year,
                    st.session_state.month,
                )
            st.session_state.schedule = sched
            st.session_state.locked_entries = [e for e in sched.entries if e.is_fixed]
            st.success("근무표를 불러왔습니다.")
        except Exception as ex:
            st.error(f"파일 파싱 오류: {ex}")

    # ── 근무표 표시
    if st.session_state.schedule:
        _render_schedule_grid(st.session_state.schedule, rules)
    else:
        st.info("'근무표 자동 생성' 버튼을 눌러 근무표를 생성하세요.")


def _run_generation(rules: ScheduleRules, optimize: bool) -> None:
    """근무표 생성 (+ 옵션 최적화)."""
    with st.spinner("근무표 생성 중..."):
        config = ScheduleConfig(
            ward=st.session_state.ward,
            nurses=st.session_state.nurses,
            rules=rules,
            fixed_schedules=st.session_state.fixed_schedules,
            year=st.session_state.year,
            month=st.session_state.month,
            locked_entries=st.session_state.locked_entries,
        )
        scheduler = GreedyScheduler(config)
        schedule = scheduler.generate()

        if optimize:
            with st.spinner("Local Search 최적화 중..."):
                optimizer = LocalSearchOptimizer(config, max_iterations=1500)
                schedule = optimizer.optimize(schedule)

        # 평가
        evaluator = ScheduleEvaluator(config)
        st.session_state.eval_result = evaluator.evaluate(schedule)
        st.session_state.schedule = schedule

    shortage = schedule.generation_params.get("shortage_log", [])
    if shortage:
        with st.expander(f"⚠️ 인력 부족 경고 ({len(shortage)}건)", expanded=True):
            for msg in shortage:
                st.warning(msg)
    else:
        st.success("근무표 생성 완료! 인력 부족 없음.")


def _render_schedule_grid(schedule: Schedule, rules: ScheduleRules) -> None:
    """Excel 스타일 근무표 Grid 렌더링 + 수동 편집."""
    st.subheader("📊 근무표 Grid")

    # 근무표 DataFrame
    exporter = ScheduleExporter(st.session_state.nurses)
    df = exporter.to_dataframe(schedule)

    # 색상 포함 styler
    def color_shift(val):
        colors = {"D": "#B8E4F9", "E": "#FFD966", "N": "#9FC5E8", "OFF": "#EFEFEF"}
        return f"background-color: {colors.get(str(val).strip(), '#fff')}; font-weight:600"

    st.dataframe(
        df.style.map(color_shift),
        use_container_width=True,
        height=min(50 + len(st.session_state.nurses) * 35, 600),
    )

    # 수동 수정 UI
    with st.expander("✏️ 수동 셀 수정 (수정 후 재생성 시 유지됨)", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        nurse_options = {n.name: n.id for n in st.session_state.nurses}
        sel_nurse_name = col1.selectbox("간호사", list(nurse_options.keys()))
        sel_nurse_id = nurse_options[sel_nurse_name]

        import calendar
        _, last_day = calendar.monthrange(st.session_state.year, st.session_state.month)
        sel_day = col2.number_input("날짜", 1, last_day, 1)
        sel_date = datetime.date(st.session_state.year, st.session_state.month, sel_day)

        sel_shift = col3.selectbox(
            "Shift", [s.value for s in ShiftType], index=3
        )

        if col4.button("✅ 적용", use_container_width=True):
            from scheduler.models import ScheduleEntry
            new_entry = ScheduleEntry(
                nurse_id=sel_nurse_id,
                date=sel_date,
                shift=ShiftType(sel_shift),
                is_fixed=True,
                is_weekend=sel_date.weekday() >= 5,
            )
            # locked_entries 업데이트
            st.session_state.locked_entries = [
                e for e in st.session_state.locked_entries
                if not (e.nurse_id == sel_nurse_id and e.date == sel_date)
            ]
            st.session_state.locked_entries.append(new_entry)

            # 현재 스케줄 즉시 반영
            for i, e in enumerate(schedule.entries):
                if e.nurse_id == sel_nurse_id and e.date == sel_date:
                    schedule.entries[i] = new_entry
                    break
            st.session_state.schedule = schedule
            st.success(f"{sel_nurse_name} {sel_date}: {sel_shift} 고정 설정")
            st.rerun()

    # Hard Constraint 위반 표시
    if st.session_state.eval_result:
        er = st.session_state.eval_result
        hard_viols = [v for v in er.constraint_result.violations if v.is_hard]
        if hard_viols:
            with st.expander(f"🚨 Hard Constraint 위반 {len(hard_viols)}건", expanded=True):
                for v in hard_viols:
                    st.markdown(
                        f"<span class='violation-hard'>❌ [{v.constraint}] {v.reason}</span>",
                        unsafe_allow_html=True,
                    )
        else:
            st.success("✅ Hard Constraint 위반 없음")

    # 요약 통계
    summary_df = exporter.to_summary_dataframe(schedule)
    st.subheader("📈 개인별 근무 요약")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)


# ──────────────────────────────────────────────
# 탭 2: 분석 대시보드
# ──────────────────────────────────────────────

def render_dashboard_tab() -> None:
    st.header("📊 분석 대시보드")

    if st.session_state.schedule is None or st.session_state.eval_result is None:
        st.info("먼저 근무표를 생성해주세요.")
        return

    er = st.session_state.eval_result
    schedule = st.session_state.schedule

    # ── 종합 점수 지표 카드
    st.subheader("🎯 종합 평가 지표")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("종합 점수", f"{er.overall_score:.1f}/100")
    c2.metric("Hard 위반", sum(1 for v in er.constraint_result.violations if v.is_hard))
    c3.metric("인력 충족률", f"{er.staffing_coverage_rate * 100:.1f}%")
    c4.metric("선호 반영률", f"{er.preference_satisfaction_rate * 100:.1f}%")
    c5.metric("평균 피로도", f"{er.average_fatigue_score:.2f}")

    st.divider()

    col_left, col_right = st.columns(2)

    # ── 야간 근무 분포 차트
    with col_left:
        st.subheader("🌙 야간 근무 분포")
        evaluator = ScheduleEvaluator(
            ScheduleConfig(
                ward=st.session_state.ward,
                nurses=st.session_state.nurses,
                rules=ScheduleRules(),
                year=st.session_state.year,
                month=st.session_state.month,
            )
        )
        night_dist = evaluator.get_night_distribution(schedule)
        fig_night = px.bar(
            x=list(night_dist.keys()),
            y=list(night_dist.values()),
            labels={"x": "간호사", "y": "야간 근무 횟수"},
            color=list(night_dist.values()),
            color_continuous_scale="Blues",
        )
        fig_night.update_layout(
            showlegend=False, margin=dict(l=20, r=20, t=30, b=20), height=300
        )
        st.plotly_chart(fig_night, use_container_width=True)

    # ── 주말 근무 분포 차트
    with col_right:
        st.subheader("📅 주말 근무 분포")
        weekend_dist = evaluator.get_weekend_distribution(schedule)
        fig_we = px.bar(
            x=list(weekend_dist.keys()),
            y=list(weekend_dist.values()),
            labels={"x": "간호사", "y": "주말 근무 횟수"},
            color=list(weekend_dist.values()),
            color_continuous_scale="Oranges",
        )
        fig_we.update_layout(
            showlegend=False, margin=dict(l=20, r=20, t=30, b=20), height=300
        )
        st.plotly_chart(fig_we, use_container_width=True)

    # ── Shift 분포 레이더 차트 (개인별)
    st.subheader("📡 Shift 유형별 분포")
    shift_data = []
    for stat in er.nurse_stats:
        shift_data.append({
            "이름": stat.nurse_name,
            "D(주간)": stat.day_shifts,
            "E(저녁)": stat.evening_shifts,
            "N(야간)": stat.night_shifts,
            "주말": stat.weekend_shifts,
            "공휴일": stat.holiday_shifts,
        })
    shift_df = pd.DataFrame(shift_data).set_index("이름")
    st.dataframe(
        shift_df.style.background_gradient(cmap="YlOrRd", axis=None),
        use_container_width=True,
    )

    # ── 피로도 Heatmap
    st.subheader("🔥 피로도 Heatmap")
    fatigue_matrix = evaluator.get_fatigue_matrix(schedule)

    import calendar
    _, last_day = calendar.monthrange(st.session_state.year, st.session_state.month)
    dates = [
        datetime.date(st.session_state.year, st.session_state.month, d)
        for d in range(1, last_day + 1)
    ]
    date_labels = [f"{d.month}/{d.day}" for d in dates]
    nurse_names = [n.name for n in st.session_state.nurses]

    z_data = [
        [fatigue_matrix.get(name, {}).get(d, 0) for d in dates]
        for name in nurse_names
    ]

    fig_heat = go.Figure(
        data=go.Heatmap(
            z=z_data,
            x=date_labels,
            y=nurse_names,
            colorscale="YlOrRd",
            showscale=True,
            hoverongaps=False,
        )
    )
    fig_heat.update_layout(
        height=max(300, len(nurse_names) * 30),
        margin=dict(l=20, r=20, t=30, b=20),
        xaxis_nticks=15,
    )
    st.plotly_chart(fig_heat, use_container_width=True)

    # ── 공정성 레이더
    st.subheader("⚖️ 공정성 분석")
    c1, c2, c3 = st.columns(3)
    c1.metric("야간 편차 (std)", f"{er.night_fairness_score:.2f}")
    c2.metric("주말 편차 (std)", f"{er.weekend_fairness_score:.2f}")
    c3.metric("공휴일 편차 (std)", f"{er.holiday_fairness_score:.2f}")


# ──────────────────────────────────────────────
# 탭 3: 간호사 관리
# ──────────────────────────────────────────────

def render_nurses_tab() -> None:
    st.header("👩‍⚕️ 간호사 관리")

    nurses = st.session_state.nurses

    # 현재 목록
    st.subheader("현재 등록 간호사")
    data = [
        {
            "ID": n.id,
            "이름": n.name,
            "경력": n.skill_level.value,
            "가능 병동": ", ".join(w.value for w in n.ward_qualifications),
            "가능 Shift": ", ".join(s.value for s in n.allowed_shifts),
            "선호 OFF 요일": ", ".join(
                ["월","화","수","목","금","토","일"][d]
                for d in n.preference.preferred_days_off
            ),
        }
        for n in nurses
    ]
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

    # 신규 간호사 추가
    with st.expander("➕ 간호사 추가"):
        c1, c2, c3 = st.columns(3)
        new_id = c1.text_input("ID (고유)", key="new_nurse_id")
        new_name = c2.text_input("이름", key="new_nurse_name")
        new_skill = c3.selectbox(
            "경력",
            [s.value for s in SkillLevel],
            key="new_nurse_skill",
        )
        new_shifts = st.multiselect(
            "가능 Shift",
            [s.value for s in ShiftType if s != ShiftType.OFF],
            default=["D", "E", "N"],
            key="new_nurse_shifts",
        )
        new_wards = st.multiselect(
            "가능 병동",
            [w.value for w in WardType],
            default=["일반"],
            key="new_nurse_wards",
        )
        if st.button("추가", key="btn_add_nurse"):
            if new_id and new_name:
                try:
                    nurse = Nurse(
                        id=new_id,
                        name=new_name,
                        skill_level=SkillLevel(new_skill),
                        ward_qualifications=[WardType(w) for w in new_wards],
                        allowed_shifts=[ShiftType(s) for s in new_shifts],
                    )
                    st.session_state.nurses.append(nurse)
                    st.success(f"{new_name} 추가 완료")
                    st.rerun()
                except Exception as ex:
                    st.error(f"오류: {ex}")
            else:
                st.warning("ID와 이름을 입력하세요.")

    # 샘플 데이터 재로드
    if st.button("🔄 샘플 데이터로 초기화"):
        st.session_state.nurses = create_sample_nurses()
        st.session_state.schedule = None
        st.session_state.eval_result = None
        st.success("샘플 데이터로 초기화되었습니다.")
        st.rerun()


# ──────────────────────────────────────────────
# 탭 4: 고정 일정 관리
# ──────────────────────────────────────────────

def render_fixed_tab() -> None:
    st.header("📌 고정 일정 관리 (연차/병가/교육)")

    nurses = st.session_state.nurses
    fixed = st.session_state.fixed_schedules

    if fixed:
        data = [
            {
                "간호사": next((n.name for n in nurses if n.id == f.nurse_id), f.nurse_id),
                "날짜": f.date.isoformat(),
                "유형": f.schedule_type.value,
                "비고": f.note,
            }
            for f in fixed
        ]
        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
    else:
        st.info("등록된 고정 일정이 없습니다.")

    st.subheader("➕ 고정 일정 추가")
    c1, c2, c3, c4 = st.columns(4)
    nurse_options = {n.name: n.id for n in nurses}
    sel_name = c1.selectbox("간호사", list(nurse_options.keys()), key="fs_nurse")
    sel_date = c2.date_input(
        "날짜",
        value=datetime.date(st.session_state.year, st.session_state.month, 1),
        key="fs_date",
    )
    sel_type = c3.selectbox(
        "유형",
        [t.value for t in FixedScheduleType],
        key="fs_type",
    )
    note = c4.text_input("비고", key="fs_note")

    if st.button("추가", key="btn_add_fs"):
        fs = FixedSchedule(
            nurse_id=nurse_options[sel_name],
            date=sel_date,
            schedule_type=FixedScheduleType(sel_type),
            note=note,
        )
        st.session_state.fixed_schedules.append(fs)
        st.success(f"{sel_name} {sel_date} {sel_type} 등록 완료")
        st.rerun()

    if fixed and st.button("🗑️ 전체 초기화", key="btn_clear_fs"):
        st.session_state.fixed_schedules = []
        st.rerun()


# ──────────────────────────────────────────────
# 탭 5: 시스템 정보
# ──────────────────────────────────────────────

def render_info_tab() -> None:
    st.header("ℹ️ 시스템 정보 및 알고리즘 설명")

    st.markdown("""
### 🧠 알고리즘 아키텍처

```
입력 데이터
    │
    ├─ GreedyScheduler (1단계: 초기해 생성)
    │      └─ 날짜×Shift 순회
    │         간호사 우선순위 정렬 (숙련도 → 공정성 → 선호)
    │         ConstraintChecker.can_assign() → Hard Constraint 검증
    │
    └─ LocalSearchOptimizer (2단계: 품질 개선)
           └─ Simulated Annealing
              이웃해: 2-opt Swap (두 간호사 날짜 교환)
              수용: δ < 0 무조건 / δ ≥ 0 확률적 수용
              Soft Constraint 페널티 최소화
```

### ⚠️ Hard Constraint
| 제약 | 설명 |
|------|------|
| 최소 인원 충족 | Shift별 최소 간호사 수 |
| Night → Day 금지 | Night 직후 휴식 필수 |
| 최대 연속 근무 | 설정 일수 초과 금지 |
| 숙련자 최소 포함 | Shift별 숙련 간호사 수 |
| 고정 일정 준수 | 연차/병가/교육 날짜 |

### 🔄 Soft Constraint (최적화 목표)
| 제약 | 페널티 방식 |
|------|------------|
| 야간 균등 분배 | 표준편차 × 가중치 |
| 주말 균등 분배 | 표준편차 × 가중치 |
| 개인 선호 반영 | 미반영 건수 × 2 |
| 피로도 최소화 | 연속 근무 / 야간 집중 |

### 📊 평가 지표 (0~100점)
- Hard 위반 없음: 40점
- 인력 충족률:   20점
- 공정성 편차:   20점
- 선호 반영률:   10점
- 피로도:        10점
    """)


# ──────────────────────────────────────────────
# 메인 렌더링
# ──────────────────────────────────────────────

def main() -> None:
    st.title("🏥 병동 간호사 근무표 자동 생성 시스템")

    rules = render_sidebar()

    tab_schedule, tab_dashboard, tab_nurses, tab_fixed, tab_info = st.tabs([
        "📋 근무표",
        "📊 대시보드",
        "👩‍⚕️ 간호사",
        "📌 고정 일정",
        "ℹ️ 시스템 정보",
    ])

    with tab_schedule:
        render_schedule_tab(rules)

    with tab_dashboard:
        render_dashboard_tab()

    with tab_nurses:
        render_nurses_tab()

    with tab_fixed:
        render_fixed_tab()

    with tab_info:
        render_info_tab()


if __name__ == "__main__":
    main()
