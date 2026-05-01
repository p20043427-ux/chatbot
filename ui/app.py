"""
병동 간호사 근무표 자동 생성 시스템 — Streamlit UI.

화면 구성:
  사이드바  : 근무 규칙 설정 (슬라이더, 체크박스)
  탭 1      : 근무표 Grid (38종 코드 색상, 수동 편집)
  탭 2      : 평가 대시보드 (분포 차트, 피로도 Heatmap)
  탭 3      : 간호사 관리
  탭 4      : 고정 일정 관리
  탭 5      : 근무 코드 참조표

실행: streamlit run ui/app.py
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

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
    ASSIGNABLE_SHIFTS,
    SHIFT_META,
    NIGHT_SHIFTS,
    WORK_SHIFTS,
    FixedScheduleType,
    ShiftRequirement,
    get_shift_label,
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

st.markdown("""
<style>
  .metric-card { background:#f0f2f6; padding:12px; border-radius:8px; text-align:center; }
  .violation-hard { color:#ff4444; font-weight:600; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────
# Session State 초기화
# ──────────────────────────────────────────────

def _init_state() -> None:
    if "nurses"           not in st.session_state: st.session_state.nurses           = create_sample_nurses()
    if "ward"             not in st.session_state: st.session_state.ward             = create_sample_ward()
    if "schedule"         not in st.session_state: st.session_state.schedule         = None
    if "eval_result"      not in st.session_state: st.session_state.eval_result      = None
    if "fixed_schedules"  not in st.session_state: st.session_state.fixed_schedules  = []
    if "locked_entries"   not in st.session_state: st.session_state.locked_entries   = []
    if "year"             not in st.session_state: st.session_state.year             = datetime.date.today().year
    if "month"            not in st.session_state: st.session_state.month            = datetime.date.today().month

_init_state()


# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────

def render_sidebar() -> ScheduleRules:
    st.sidebar.title("⚙️ 근무 규칙 설정")

    st.sidebar.subheader("📅 대상 기간")
    c1, c2 = st.sidebar.columns(2)
    st.session_state.year  = c1.number_input("연도", value=st.session_state.year,  min_value=2020, max_value=2030)
    st.session_state.month = c2.number_input("월",   value=st.session_state.month, min_value=1,    max_value=12)

    st.sidebar.divider()
    st.sidebar.subheader("🔒 Hard Constraint")
    max_consec  = st.sidebar.slider("최대 연속 근무일",      3, 10, 5)
    night_rest  = st.sidebar.checkbox("야간 후 다음날 OFF 강제", value=True)
    max_nights  = st.sidebar.slider("최대 연속 야간",         1,  7, 3)
    min_rest_h  = st.sidebar.slider("교대 간 최소 휴식(시간)", 8, 16, 11)

    st.sidebar.divider()
    st.sidebar.subheader("👥 Shift 최소 인원")
    d_min = st.sidebar.number_input("D 최소 인원", value=4, min_value=1)
    d_snr = st.sidebar.number_input("D 최소 숙련", value=1, min_value=0)
    e_min = st.sidebar.number_input("E 최소 인원", value=3, min_value=1)
    e_snr = st.sidebar.number_input("E 최소 숙련", value=1, min_value=0)
    n_min = st.sidebar.number_input("N 최소 인원", value=2, min_value=1)
    n_snr = st.sidebar.number_input("N 최소 숙련", value=1, min_value=0)

    st.sidebar.divider()
    st.sidebar.subheader("⚖️ 공정성 가중치")
    w_night   = st.sidebar.slider("야간",   0.0, 5.0, 1.5, 0.1)
    w_weekend = st.sidebar.slider("주말",   0.0, 5.0, 1.0, 0.1)
    w_holiday = st.sidebar.slider("공휴일", 0.0, 5.0, 2.0, 0.1)
    pref_rate = st.sidebar.slider("선호 반영 목표(%)", 0, 100, 70, 5) / 100

    return ScheduleRules(
        max_consecutive_work_days=max_consec,
        night_rest_required=night_rest,
        max_consecutive_nights=max_nights,
        min_rest_hours_between_shifts=min_rest_h,
        shift_requirements={
            ShiftType.D: ShiftRequirement(min_nurses=d_min, min_senior_nurses=d_snr),
            ShiftType.E: ShiftRequirement(min_nurses=e_min, min_senior_nurses=e_snr),
            ShiftType.N: ShiftRequirement(min_nurses=n_min, min_senior_nurses=n_snr),
        },
        fairness_weight_night=w_night,
        fairness_weight_weekend=w_weekend,
        fairness_weight_holiday=w_holiday,
        preference_satisfaction_rate=pref_rate,
    )


# ──────────────────────────────────────────────
# 탭 1: 근무표
# ──────────────────────────────────────────────

def render_schedule_tab(rules: ScheduleRules) -> None:
    st.header("📋 근무표")

    col_gen, col_opt, col_exp = st.columns(3)
    with col_gen:
        if st.button("🚀 자동 생성", type="primary", use_container_width=True):
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

    uploaded = st.file_uploader("📤 Excel/CSV 업로드", type=["xlsx", "csv"])
    if uploaded:
        exporter = ScheduleExporter(st.session_state.nurses)
        try:
            if uploaded.name.endswith(".xlsx"):
                sched = exporter.from_excel(
                    uploaded.read(), st.session_state.ward.id,
                    st.session_state.year, st.session_state.month)
            else:
                sched = exporter.from_csv(
                    uploaded.read().decode("utf-8-sig"), st.session_state.ward.id,
                    st.session_state.year, st.session_state.month)
            st.session_state.schedule = sched
            st.session_state.locked_entries = [e for e in sched.entries if e.is_fixed]
            st.success("근무표를 불러왔습니다.")
        except Exception as ex:
            st.error(f"파싱 오류: {ex}")

    if st.session_state.schedule:
        _render_schedule_grid(st.session_state.schedule, rules)
    else:
        st.info("'자동 생성' 버튼을 눌러 근무표를 생성하세요.")


def _run_generation(rules: ScheduleRules, optimize: bool) -> None:
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
        schedule = GreedyScheduler(config).generate()
        if optimize:
            with st.spinner("최적화 중..."):
                schedule = LocalSearchOptimizer(config, max_iterations=1500).optimize(schedule)
        evaluator = ScheduleEvaluator(config)
        st.session_state.eval_result = evaluator.evaluate(schedule)
        st.session_state.schedule = schedule

    shortage = schedule.generation_params.get("shortage_log", [])
    if shortage:
        with st.expander(f"⚠️ 인력 부족 경고 ({len(shortage)}건)", expanded=True):
            for msg in shortage:
                st.warning(msg)
    else:
        st.success("근무표 생성 완료!")


def _render_schedule_grid(schedule: Schedule, rules: ScheduleRules) -> None:
    st.subheader("📊 근무표 Grid")

    exporter = ScheduleExporter(st.session_state.nurses)
    df = exporter.to_dataframe(schedule)

    # 38종 코드 색상 styler
    def color_shift(val: str):
        raw = str(val).strip()
        try:
            shift = ShiftType(raw)
            color = f"#{SHIFT_META[shift].color_hex}" if shift in SHIFT_META else "#ffffff"
            bold  = "600" if shift in WORK_SHIFTS else "400"
        except (ValueError, KeyError):
            color, bold = "#ffffff", "400"
        return f"background-color:{color}; font-weight:{bold}; text-align:center"

    st.dataframe(
        df.style.map(color_shift),
        use_container_width=True,
        height=min(55 + len(st.session_state.nurses) * 36, 650),
    )

    # ── 수동 셀 편집
    with st.expander("✏️ 수동 셀 수정 (고정 → 재생성 시 유지)", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        nurse_options = {n.name: n.id for n in st.session_state.nurses}
        sel_name = c1.selectbox("간호사", list(nurse_options.keys()), key="mc_nurse")
        sel_nid  = nurse_options[sel_name]

        import calendar
        _, last_day = calendar.monthrange(st.session_state.year, st.session_state.month)
        sel_day  = c2.number_input("날짜", 1, last_day, 1, key="mc_day")
        sel_date = datetime.date(st.session_state.year, st.session_state.month, sel_day)

        # 배정 가능 코드 + 비번/연차 선택 허용
        selectable = sorted(
            list(ASSIGNABLE_SHIFTS) + [ShiftType.O, ShiftType.Y, ShiftType.I, ShiftType.T],
            key=lambda s: s.value
        )
        sel_shift_val = c3.selectbox(
            "근무 코드",
            [s.value for s in selectable],
            format_func=lambda v: f"{v} — {get_shift_label(ShiftType(v))}",
            key="mc_shift",
        )
        if c4.button("✅ 적용", key="mc_apply", use_container_width=True):
            from scheduler.models import ScheduleEntry
            new_entry = ScheduleEntry(
                nurse_id=sel_nid, date=sel_date,
                shift=ShiftType(sel_shift_val), is_fixed=True,
                is_weekend=sel_date.weekday() >= 5,
            )
            st.session_state.locked_entries = [
                e for e in st.session_state.locked_entries
                if not (e.nurse_id == sel_nid and e.date == sel_date)
            ]
            st.session_state.locked_entries.append(new_entry)
            for i, e in enumerate(schedule.entries):
                if e.nurse_id == sel_nid and e.date == sel_date:
                    schedule.entries[i] = new_entry
                    break
            st.session_state.schedule = schedule
            st.success(f"{sel_name} {sel_date}: {sel_shift_val}({get_shift_label(ShiftType(sel_shift_val))}) 고정")
            st.rerun()

    # ── Hard 위반
    if st.session_state.eval_result:
        er = st.session_state.eval_result
        hard_viols = [v for v in er.constraint_result.violations if v.is_hard]
        if hard_viols:
            with st.expander(f"🚨 Hard 위반 {len(hard_viols)}건", expanded=True):
                for v in hard_viols:
                    st.markdown(f"<span class='violation-hard'>❌ [{v.constraint}] {v.reason}</span>",
                                unsafe_allow_html=True)
        else:
            st.success("✅ Hard Constraint 위반 없음")

    # ── 요약 통계
    st.subheader("📈 개인별 근무 요약")
    st.dataframe(exporter.to_summary_dataframe(schedule), use_container_width=True, hide_index=True)


# ──────────────────────────────────────────────
# 탭 2: 대시보드
# ──────────────────────────────────────────────

def render_dashboard_tab() -> None:
    st.header("📊 분석 대시보드")
    if not st.session_state.schedule or not st.session_state.eval_result:
        st.info("먼저 근무표를 생성해주세요.")
        return

    er  = st.session_state.eval_result
    sch = st.session_state.schedule

    # 종합 지표
    st.subheader("🎯 종합 평가 지표")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("종합 점수",   f"{er.overall_score:.1f}/100")
    c2.metric("Hard 위반",   sum(1 for v in er.constraint_result.violations if v.is_hard))
    c3.metric("인력 충족률", f"{er.staffing_coverage_rate*100:.1f}%")
    c4.metric("선호 반영률", f"{er.preference_satisfaction_rate*100:.1f}%")
    c5.metric("평균 피로도", f"{er.average_fatigue_score:.2f}")

    st.divider()

    evaluator = ScheduleEvaluator(ScheduleConfig(
        ward=st.session_state.ward, nurses=st.session_state.nurses,
        rules=ScheduleRules(), year=st.session_state.year, month=st.session_state.month,
    ))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🌙 야간 근무 분포")
        night_dist = evaluator.get_night_distribution(sch)
        fig = px.bar(x=list(night_dist.keys()), y=list(night_dist.values()),
                     labels={"x": "간호사", "y": "야간 횟수"},
                     color=list(night_dist.values()), color_continuous_scale="Blues")
        fig.update_layout(showlegend=False, margin=dict(l=20,r=20,t=30,b=20), height=300)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("📅 주말 근무 분포")
        we_dist = evaluator.get_weekend_distribution(sch)
        fig = px.bar(x=list(we_dist.keys()), y=list(we_dist.values()),
                     labels={"x": "간호사", "y": "주말 횟수"},
                     color=list(we_dist.values()), color_continuous_scale="Oranges")
        fig.update_layout(showlegend=False, margin=dict(l=20,r=20,t=30,b=20), height=300)
        st.plotly_chart(fig, use_container_width=True)

    # Shift 분포 테이블
    st.subheader("📡 개인별 Shift 분포")
    rows = []
    for stat in er.nurse_stats:
        row = {"이름": stat.nurse_name, "근무일": stat.total_work_days}
        row.update({k: v for k, v in stat.shift_counts.items()})
        row.update({"주말": stat.weekend_shifts, "공휴일": stat.holiday_shifts})
        rows.append(row)
    shift_df = pd.DataFrame(rows).set_index("이름").fillna(0).astype(int, errors="ignore")
    st.dataframe(shift_df.style.background_gradient(cmap="YlOrRd", axis=None), use_container_width=True)

    # 피로도 Heatmap
    st.subheader("🔥 피로도 Heatmap")
    fatigue_matrix = evaluator.get_fatigue_matrix(sch)
    import calendar
    _, last_day = calendar.monthrange(st.session_state.year, st.session_state.month)
    dates = [datetime.date(st.session_state.year, st.session_state.month, d)
             for d in range(1, last_day + 1)]
    date_labels = [f"{d.month}/{d.day}" for d in dates]
    nurse_names = [n.name for n in st.session_state.nurses]

    z_data = [[fatigue_matrix.get(name, {}).get(d, 0) for d in dates] for name in nurse_names]
    fig_heat = go.Figure(data=go.Heatmap(
        z=z_data, x=date_labels, y=nurse_names,
        colorscale="YlOrRd", showscale=True,
    ))
    fig_heat.update_layout(height=max(300, len(nurse_names)*30),
                           margin=dict(l=20,r=20,t=30,b=20), xaxis_nticks=15)
    st.plotly_chart(fig_heat, use_container_width=True)

    # 공정성
    st.subheader("⚖️ 공정성 분석")
    c1, c2, c3 = st.columns(3)
    c1.metric("야간 편차 (std)",   f"{er.night_fairness_score:.2f}")
    c2.metric("주말 편차 (std)",   f"{er.weekend_fairness_score:.2f}")
    c3.metric("공휴일 편차 (std)", f"{er.holiday_fairness_score:.2f}")


# ──────────────────────────────────────────────
# 탭 3: 간호사 관리
# ──────────────────────────────────────────────

def render_nurses_tab() -> None:
    st.header("👩‍⚕️ 간호사 관리")
    nurses = st.session_state.nurses
    data = [{
        "ID": n.id, "이름": n.name, "경력": n.skill_level.value,
        "가능 병동": ", ".join(w.value for w in n.ward_qualifications),
        "가능 Shift": ", ".join(s.value for s in n.allowed_shifts),
    } for n in nurses]
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

    with st.expander("➕ 간호사 추가"):
        c1, c2, c3 = st.columns(3)
        new_id    = c1.text_input("ID", key="nn_id")
        new_name  = c2.text_input("이름", key="nn_name")
        new_skill = c3.selectbox("경력", [s.value for s in SkillLevel], key="nn_skill")
        new_shifts = st.multiselect(
            "가능 Shift (코드)",
            [f"{s.value} — {get_shift_label(s)}" for s in sorted(ASSIGNABLE_SHIFTS, key=lambda x: x.value)],
            default=["D — 낮근무", "E — 저녁근무", "N — 밤근무"],
            key="nn_shifts",
        )
        new_wards = st.multiselect("가능 병동", [w.value for w in WardType], default=["일반"], key="nn_wards")
        if st.button("추가", key="btn_add_nurse"):
            if new_id and new_name:
                try:
                    shift_codes = [ShiftType(s.split(" — ")[0]) for s in new_shifts]
                    nurse = Nurse(
                        id=new_id, name=new_name,
                        skill_level=SkillLevel(new_skill),
                        ward_qualifications=[WardType(w) for w in new_wards],
                        allowed_shifts=shift_codes,
                    )
                    st.session_state.nurses.append(nurse)
                    st.success(f"{new_name} 추가 완료")
                    st.rerun()
                except Exception as ex:
                    st.error(f"오류: {ex}")

    if st.button("🔄 샘플 초기화"):
        st.session_state.nurses   = create_sample_nurses()
        st.session_state.schedule = None
        st.session_state.eval_result = None
        st.rerun()


# ──────────────────────────────────────────────
# 탭 4: 고정 일정
# ──────────────────────────────────────────────

def render_fixed_tab() -> None:
    st.header("📌 고정 일정 관리")
    nurses = st.session_state.nurses
    fixed  = st.session_state.fixed_schedules

    if fixed:
        data = [{
            "간호사": next((n.name for n in nurses if n.id == f.nurse_id), f.nurse_id),
            "날짜":   f.date.isoformat(),
            "유형":   f.schedule_type.value,
            "코드":   f.shift_code.value,
            "비고":   f.note,
        } for f in fixed]
        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
    else:
        st.info("등록된 고정 일정이 없습니다.")

    st.subheader("➕ 추가")
    c1, c2, c3, c4 = st.columns(4)
    nurse_opts = {n.name: n.id for n in nurses}
    sel_name = c1.selectbox("간호사", list(nurse_opts.keys()), key="fs_nurse")
    sel_date = c2.date_input(
        "날짜",
        value=datetime.date(st.session_state.year, st.session_state.month, 1),
        key="fs_date",
    )
    sel_type = c3.selectbox(
        "유형",
        [t.value for t in FixedScheduleType],
        format_func=lambda v: f"{v}  → {FixedScheduleType(v).shift_code.value}",
        key="fs_type",
    )
    note = c4.text_input("비고", key="fs_note")

    if st.button("추가", key="btn_add_fs"):
        fs = FixedSchedule(
            nurse_id=nurse_opts[sel_name],
            date=sel_date,
            schedule_type=FixedScheduleType(sel_type),
            note=note,
        )
        st.session_state.fixed_schedules.append(fs)
        st.success(f"{sel_name} {sel_date} → {fs.shift_code.value}({sel_type}) 등록")
        st.rerun()

    if fixed and st.button("🗑️ 전체 초기화", key="btn_clear_fs"):
        st.session_state.fixed_schedules = []
        st.rerun()


# ──────────────────────────────────────────────
# 탭 5: 근무 코드 참조표
# ──────────────────────────────────────────────

def render_code_reference_tab() -> None:
    st.header("📖 근무 코드 참조표 (38종)")

    rows = []
    for s, meta in SHIFT_META.items():
        rows.append({
            "코드":     s.value,
            "명칭":     meta.label,
            "카테고리": meta.category,
            "근무여부": "○" if meta.is_work else "—",
            "야간여부": "●" if meta.is_night else "—",
            "시작":     f"{meta.start_h:02d}:00" if meta.is_work else "—",
            "종료":     f"{meta.end_h % 24:02d}:00{'(익일)' if meta.end_h >= 24 else ''}" if meta.is_work else "—",
        })

    df = pd.DataFrame(rows)

    def color_row(row):
        try:
            shift = ShiftType(row["코드"])
            color = f"#{SHIFT_META[shift].color_hex}"
        except Exception:
            color = "#ffffff"
        return [f"background-color:{color}"] * len(row)

    st.dataframe(
        df.style.apply(color_row, axis=1),
        use_container_width=True,
        hide_index=True,
        height=min(50 + len(rows) * 36, 800),
    )

    st.subheader("카테고리별 설명")
    cats = {
        "work":  "🟦 **work** — 실제 근무 (근무일수 산정, 피로도 계산 대상)",
        "off":   "⬜ **off**  — 비번 / 당직오프 (근무 없음)",
        "leave": "🟩 **leave** — 각종 휴가 (연차·공가·경조·분만·육아·무급)",
        "sick":  "🟥 **sick** — 병가",
        "edu":   "🟨 **edu**  — 교육 (전일/반일)",
        "limit": "⬛ **limit** — 사용금지·제한 코드",
    }
    for k, v in cats.items():
        st.markdown(v)


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main() -> None:
    st.title("🏥 병동 간호사 근무표 자동 생성 시스템")
    rules = render_sidebar()

    tab_sch, tab_dash, tab_nurse, tab_fixed, tab_code = st.tabs([
        "📋 근무표",
        "📊 대시보드",
        "👩‍⚕️ 간호사",
        "📌 고정 일정",
        "📖 근무 코드표",
    ])

    with tab_sch:   render_schedule_tab(rules)
    with tab_dash:  render_dashboard_tab()
    with tab_nurse: render_nurses_tab()
    with tab_fixed: render_fixed_tab()
    with tab_code:  render_code_reference_tab()


if __name__ == "__main__":
    main()
