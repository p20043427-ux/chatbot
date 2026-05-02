"""
병동 간호사 근무표 자동 생성 시스템 — Streamlit UI.

실행: streamlit run ui/app.py
"""

from __future__ import annotations

import calendar
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
    FixedSchedule,
    GreedyScheduler,
    LocalSearchOptimizer,
    Nurse,
    Schedule,
    ScheduleConfig,
    ScheduleEvaluator,
    ScheduleExporter,
    ScheduleRules,
    ShiftType,
    SkillLevel,
    WardType,
)
from scheduler.models import (
    ASSIGNABLE_SHIFTS,
    SHIFT_META,
    WORK_SHIFTS,
    FixedScheduleType,
    ScheduleEntry,
    ShiftRequirement,
    get_shift_label,
)
from tests.sample_data import create_sample_nurses, create_sample_ward

# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="간호사 근무표 시스템",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# 디자인 시스템 — 최소화된 안정적 CSS
# ─────────────────────────────────────────────

_CSS = """
<style>
/* ── Tokens ───────────────────────────────────── */
:root {
  --navy:      #1B2238;
  --navy-2:    #26314F;
  --teal:      #2A82C8;
  --bg:        #F1F4FA;
  --card:      #FFFFFF;
  --border:    #DCE3EE;
  --text:      #1A202C;
  --text-sub:  #4A5568;
  --text-mute: #718096;
  --success:   #1E8449;
  --warning:   #B7770D;
  --danger:    #B03A2E;
}

/* ── Base ─────────────────────────────────────── */
.stApp { background: var(--bg); }

/* Limit content width for readability */
.main .block-container {
  padding-top: 1.2rem;
  padding-bottom: 3rem;
  max-width: 1400px;
}

/* ── Page header ──────────────────────────────── */
.app-header {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 22px;
  margin-bottom: 18px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.app-header .crumb {
  font-size: 11px;
  color: var(--text-mute);
  letter-spacing: 0.4px;
  margin-bottom: 4px;
}
.app-header .title {
  font-size: 22px;
  font-weight: 700;
  color: var(--navy);
  letter-spacing: -0.4px;
}

/* ── Section header (HTML-only, robust) ───────── */
.sec-head {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--card);
  border: 1px solid var(--border);
  border-left: 4px solid var(--navy);
  border-radius: 8px;
  padding: 11px 16px;
  margin: 18px 0 10px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.sec-head .num {
  width: 24px; height: 24px;
  background: var(--navy);
  color: #fff;
  border-radius: 5px;
  display: inline-flex;
  align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700;
  flex-shrink: 0;
}
.sec-head .ttl {
  font-size: 14px;
  font-weight: 600;
  color: var(--navy);
}
.sec-head .desc {
  font-size: 12px;
  color: var(--text-mute);
  margin-left: 6px;
}

/* Variants */
.sec-head.green  { border-left-color: var(--success); }
.sec-head.green  .num { background: var(--success); }
.sec-head.amber  { border-left-color: var(--warning); }
.sec-head.amber  .num { background: var(--warning); }
.sec-head.red    { border-left-color: var(--danger); }
.sec-head.red    .num { background: var(--danger); }
.sec-head.teal   { border-left-color: var(--teal); }
.sec-head.teal   .num { background: var(--teal); }

/* ── Metric cards ─────────────────────────────── */
.mtx-row {
  display: flex; gap: 10px; flex-wrap: wrap; margin: 0 0 10px;
}
.mtx {
  flex: 1; min-width: 130px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.mtx .lbl {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-mute);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  margin-bottom: 6px;
}
.mtx .val {
  font-size: 26px;
  font-weight: 700;
  color: var(--navy);
  line-height: 1.1;
}
.mtx .sub {
  font-size: 11px;
  color: var(--text-mute);
  margin-top: 3px;
}
.mtx.danger  .val { color: var(--danger); }
.mtx.success .val { color: var(--success); }
.mtx.warning .val { color: var(--warning); }
.mtx.teal    .val { color: var(--teal); }

/* ── Violation tag ─────────────────────────────── */
.viol {
  display: inline-block;
  background: #FEF2F2; color: var(--danger);
  border: 1px solid #FECACA;
  border-radius: 5px;
  padding: 3px 9px;
  font-size: 12px; font-weight: 500;
  margin: 2px 4px 2px 0;
}

/* ── Legend badges (code reference) ───────────── */
.lgd {
  display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px;
}
.lgd span {
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 11px; font-weight: 600;
}

/* ── Code dot (for shift codes display) ────── */
.codedot {
  display: inline-block;
  min-width: 22px;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px; font-weight: 700;
  text-align: center;
  border: 1px solid rgba(0,0,0,0.08);
}
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 디자인 헬퍼
# ─────────────────────────────────────────────

def section(num: int, title: str, desc: str = "", variant: str = "") -> None:
    """섹션 헤더 — variant: "" | "green" | "amber" | "red" | "teal" """
    cls = f"sec-head {variant}".strip()
    desc_html = f'<span class="desc">{desc}</span>' if desc else ""
    st.markdown(
        f'<div class="{cls}">'
        f'  <span class="num">{num}</span>'
        f'  <span class="ttl">{title}</span>'
        f'  {desc_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def metric_html(label: str, value: str, sub: str = "", variant: str = "") -> str:
    cls = f"mtx {variant}".strip()
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (
        f'<div class="{cls}">'
        f'<div class="lbl">{label}</div>'
        f'<div class="val">{value}</div>'
        f'{sub_html}'
        f'</div>'
    )


def metric_row(*cards: str) -> None:
    st.markdown(f'<div class="mtx-row">{"".join(cards)}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Session State
# ─────────────────────────────────────────────

def _init_state() -> None:
    defaults = {
        "nurses":          create_sample_nurses(),
        "ward":            create_sample_ward(),
        "schedule":        None,
        "eval_result":     None,
        "fixed_schedules": [],
        "locked_entries":  [],
        "year":            datetime.date.today().year,
        "month":           datetime.date.today().month,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ─────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────

def render_sidebar() -> ScheduleRules:
    sb = st.sidebar
    sb.title("근무 규칙 설정")
    sb.caption("Nurse Schedule v2.0")
    sb.divider()

    sb.markdown("**대상 기간**")
    c1, c2 = sb.columns(2)
    st.session_state.year  = c1.number_input("연도", value=st.session_state.year,
                                             min_value=2020, max_value=2030)
    st.session_state.month = c2.number_input("월", value=st.session_state.month,
                                             min_value=1, max_value=12)
    sb.divider()

    sb.markdown("**Hard Constraint**")
    max_consec = sb.slider("최대 연속 근무일", 3, 10, 5)
    night_rest = sb.checkbox("야간 후 다음날 OFF 강제", value=True)
    max_nights = sb.slider("최대 연속 야간", 1, 7, 3)
    min_rest_h = sb.slider("교대 간 최소 휴식 (시간)", 8, 16, 11)
    sb.divider()

    sb.markdown("**Shift 최소 인원**")
    c1, c2 = sb.columns(2)
    d_min = c1.number_input("D 최소",   value=4, min_value=1, key="d_min")
    d_snr = c2.number_input("D 숙련",   value=1, min_value=0, key="d_snr")
    e_min = c1.number_input("E 최소",   value=3, min_value=1, key="e_min")
    e_snr = c2.number_input("E 숙련",   value=1, min_value=0, key="e_snr")
    n_min = c1.number_input("N 최소",   value=2, min_value=1, key="n_min")
    n_snr = c2.number_input("N 숙련",   value=1, min_value=0, key="n_snr")
    sb.divider()

    sb.markdown("**공정성 가중치**")
    w_night   = sb.slider("야간",   0.0, 5.0, 1.5, 0.1)
    w_weekend = sb.slider("주말",   0.0, 5.0, 1.0, 0.1)
    w_holiday = sb.slider("공휴일", 0.0, 5.0, 2.0, 0.1)
    pref_rate = sb.slider("선호 반영 목표 (%)", 0, 100, 70, 5) / 100

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


# ─────────────────────────────────────────────
# 탭 1: 근무표
# ─────────────────────────────────────────────

def render_schedule_tab(rules: ScheduleRules) -> None:
    section(1, "근무표 생성", "버튼을 눌러 자동 배정 또는 최적화를 실행합니다")
    c_gen, c_opt, c_exp = st.columns(3)
    with c_gen:
        if st.button("자동 생성", type="primary", use_container_width=True):
            _run_generation(rules, optimize=False)
    with c_opt:
        if st.button("생성 + 최적화", use_container_width=True):
            _run_generation(rules, optimize=True)
    with c_exp:
        if st.session_state.schedule:
            exporter = ScheduleExporter(st.session_state.nurses)
            xl = exporter.to_excel(st.session_state.schedule)
            st.download_button(
                "Excel 다운로드", data=xl,
                file_name=f"schedule_{st.session_state.year}_{st.session_state.month:02d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    section(2, "Excel / CSV 업로드", "기존 근무표 불러오기", variant="teal")
    uploaded = st.file_uploader("파일 선택", type=["xlsx", "csv"], label_visibility="collapsed")
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
        _render_grid(st.session_state.schedule, rules)
    else:
        st.info("‘자동 생성’ 버튼을 눌러 근무표를 생성하세요.")


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
        sched = GreedyScheduler(config).generate()
        if optimize:
            with st.spinner("최적화 진행 중..."):
                sched = LocalSearchOptimizer(config, max_iterations=1500).optimize(sched)
        st.session_state.eval_result = ScheduleEvaluator(config).evaluate(sched)
        st.session_state.schedule = sched

    shortage = sched.generation_params.get("shortage_log", [])
    if shortage:
        with st.expander(f"인력 부족 경고 ({len(shortage)}건)", expanded=True):
            for msg in shortage:
                st.warning(msg)
    else:
        st.success("근무표 생성 완료")


def _render_grid(schedule: Schedule, rules: ScheduleRules) -> None:
    section(3, "근무표 Grid",
            f"{st.session_state.year}년 {st.session_state.month}월 · "
            f"{len(st.session_state.nurses)}명")

    exporter = ScheduleExporter(st.session_state.nurses)
    df = exporter.to_dataframe(schedule)

    def color_shift(val: str):
        raw = str(val).strip()
        try:
            shift = ShiftType(raw)
            color = f"#{SHIFT_META[shift].color_hex}" if shift in SHIFT_META else "#ffffff"
            bold  = "600" if shift in WORK_SHIFTS else "400"
        except (ValueError, KeyError):
            color, bold = "#ffffff", "400"
        return f"background-color:{color};font-weight:{bold};text-align:center;font-size:12px;"

    st.dataframe(
        df.style.map(color_shift),
        use_container_width=True,
        height=min(55 + len(st.session_state.nurses) * 36, 650),
    )

    section(4, "수동 셀 수정", "고정한 셀은 재생성 시에도 유지됩니다", variant="amber")
    c1, c2, c3, c4 = st.columns([2, 1, 2, 1])
    nurse_options = {n.name: n.id for n in st.session_state.nurses}
    sel_name = c1.selectbox("간호사", list(nurse_options.keys()), key="mc_nurse")
    sel_nid  = nurse_options[sel_name]

    _, last_day = calendar.monthrange(st.session_state.year, st.session_state.month)
    sel_day  = c2.number_input("날짜", 1, last_day, 1, key="mc_day")
    sel_date = datetime.date(st.session_state.year, st.session_state.month, sel_day)

    selectable = sorted(
        list(ASSIGNABLE_SHIFTS) + [ShiftType.O, ShiftType.Y, ShiftType.I, ShiftType.T],
        key=lambda s: s.value,
    )
    sel_shift_val = c3.selectbox(
        "근무 코드",
        [s.value for s in selectable],
        format_func=lambda v: f"{v} — {get_shift_label(ShiftType(v))}",
        key="mc_shift",
    )
    if c4.button("적용", key="mc_apply", type="primary", use_container_width=True):
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
        st.success(f"{sel_name} {sel_date}: {sel_shift_val} 고정")
        st.rerun()

    if st.session_state.eval_result:
        er = st.session_state.eval_result
        hard_viols = [v for v in er.constraint_result.violations if v.is_hard]
        if hard_viols:
            section(5, "Hard Constraint 위반", f"총 {len(hard_viols)}건", variant="red")
            for v in hard_viols:
                st.markdown(
                    f'<span class="viol">[{v.constraint}] {v.reason}</span>',
                    unsafe_allow_html=True,
                )
        else:
            section(5, "Hard Constraint 검증", "위반 없음", variant="green")
            st.success("모든 Hard Constraint를 만족합니다")

    section(6, "개인별 근무 요약")
    st.dataframe(exporter.to_summary_dataframe(schedule),
                 use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────
# 탭 2: 대시보드
# ─────────────────────────────────────────────

def render_dashboard_tab() -> None:
    if not st.session_state.schedule or not st.session_state.eval_result:
        st.info("먼저 ‘근무표’ 탭에서 근무표를 생성해주세요.")
        return

    er  = st.session_state.eval_result
    sch = st.session_state.schedule

    section(1, "종합 평가 지표")
    hard_cnt = sum(1 for v in er.constraint_result.violations if v.is_hard)
    metric_row(
        metric_html("종합 점수", f"{er.overall_score:.1f}", sub="/ 100"),
        metric_html("Hard 위반", str(hard_cnt),
                    variant="danger" if hard_cnt else "success"),
        metric_html("인력 충족률", f"{er.staffing_coverage_rate*100:.0f}%",
                    variant="success" if er.staffing_coverage_rate >= 0.9 else "warning"),
        metric_html("선호 반영률", f"{er.preference_satisfaction_rate*100:.0f}%"),
        metric_html("평균 피로도", f"{er.average_fatigue_score:.2f}", variant="teal"),
    )

    evaluator = ScheduleEvaluator(ScheduleConfig(
        ward=st.session_state.ward, nurses=st.session_state.nurses,
        rules=ScheduleRules(), year=st.session_state.year, month=st.session_state.month,
    ))

    _LAYOUT = dict(
        showlegend=False, height=280,
        margin=dict(l=12, r=12, t=20, b=12),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(size=11),
    )

    section(2, "근무 분포 분석", variant="teal")
    col1, col2 = st.columns(2)
    with col1:
        st.caption("야간 근무 분포")
        nd = evaluator.get_night_distribution(sch)
        fig = px.bar(x=list(nd.keys()), y=list(nd.values()),
                     labels={"x": "", "y": "횟수"},
                     color=list(nd.values()), color_continuous_scale="Blues")
        fig.update_layout(**_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        st.caption("주말 근무 분포")
        wd = evaluator.get_weekend_distribution(sch)
        fig = px.bar(x=list(wd.keys()), y=list(wd.values()),
                     labels={"x": "", "y": "횟수"},
                     color=list(wd.values()), color_continuous_scale="Oranges")
        fig.update_layout(**_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

    section(3, "개인별 Shift 분포", variant="green")
    rows = []
    for stat in er.nurse_stats:
        row = {"이름": stat.nurse_name, "근무일": stat.total_work_days}
        row.update({k: v for k, v in stat.shift_counts.items()})
        row.update({"주말": stat.weekend_shifts, "공휴일": stat.holiday_shifts})
        rows.append(row)
    shift_df = pd.DataFrame(rows).set_index("이름").fillna(0).astype(int, errors="ignore")
    st.dataframe(_heatmap_style(shift_df), use_container_width=True)

    section(4, "피로도 Heatmap", "값이 클수록 누적 피로", variant="red")
    fmat = evaluator.get_fatigue_matrix(sch)
    _, last_day = calendar.monthrange(st.session_state.year, st.session_state.month)
    dates = [datetime.date(st.session_state.year, st.session_state.month, d)
             for d in range(1, last_day + 1)]
    date_labels = [f"{d.month}/{d.day}" for d in dates]
    nurse_names = [n.name for n in st.session_state.nurses]
    z_data = [[fmat.get(name, {}).get(d, 0) for d in dates] for name in nurse_names]
    fig_h = go.Figure(data=go.Heatmap(z=z_data, x=date_labels, y=nurse_names,
                                      colorscale="YlOrRd", showscale=True))
    fig_h.update_layout(
        height=max(280, len(nurse_names) * 28),
        margin=dict(l=12, r=12, t=20, b=12),
        xaxis_nticks=15,
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(size=11),
    )
    st.plotly_chart(fig_h, use_container_width=True)

    section(5, "공정성 분석", "값이 낮을수록 균등", variant="amber")
    metric_row(
        metric_html("야간 편차 (std)",   f"{er.night_fairness_score:.2f}"),
        metric_html("주말 편차 (std)",   f"{er.weekend_fairness_score:.2f}"),
        metric_html("공휴일 편차 (std)", f"{er.holiday_fairness_score:.2f}"),
    )


# ─────────────────────────────────────────────
# 탭 3: 간호사 관리
# ─────────────────────────────────────────────

def render_nurses_tab() -> None:
    nurses = st.session_state.nurses
    section(1, "간호사 목록", f"총 {len(nurses)}명")
    data = [{
        "ID":         n.id,
        "이름":       n.name,
        "경력":       n.skill_level.value,
        "가능 병동":  ", ".join(w.value for w in n.ward_qualifications),
        "가능 Shift": ", ".join(s.value for s in n.allowed_shifts),
    } for n in nurses]
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

    section(2, "간호사 추가", variant="green")
    c1, c2, c3 = st.columns(3)
    new_id    = c1.text_input("ID",   key="nn_id")
    new_name  = c2.text_input("이름", key="nn_name")
    new_skill = c3.selectbox("경력",  [s.value for s in SkillLevel], key="nn_skill")
    new_shifts = st.multiselect(
        "가능 Shift",
        [f"{s.value} — {get_shift_label(s)}" for s in sorted(ASSIGNABLE_SHIFTS, key=lambda x: x.value)],
        default=["D — 낮근무", "E — 저녁근무", "N — 밤근무"],
        key="nn_shifts",
    )
    new_wards = st.multiselect("가능 병동", [w.value for w in WardType],
                               default=["일반"], key="nn_wards")

    c_add, c_reset, _ = st.columns([1, 1, 3])
    with c_add:
        if st.button("추가", key="btn_add_nurse", type="primary", use_container_width=True):
            if new_id and new_name:
                try:
                    nurse = Nurse(
                        id=new_id, name=new_name,
                        skill_level=SkillLevel(new_skill),
                        ward_qualifications=[WardType(w) for w in new_wards],
                        allowed_shifts=[ShiftType(s.split(" — ")[0]) for s in new_shifts],
                    )
                    st.session_state.nurses.append(nurse)
                    st.success(f"{new_name} 추가 완료")
                    st.rerun()
                except Exception as ex:
                    st.error(f"오류: {ex}")
    with c_reset:
        if st.button("샘플 초기화", key="btn_reset_nurses", use_container_width=True):
            st.session_state.nurses      = create_sample_nurses()
            st.session_state.schedule    = None
            st.session_state.eval_result = None
            st.rerun()


# ─────────────────────────────────────────────
# 탭 4: 고정 일정
# ─────────────────────────────────────────────

def render_fixed_tab() -> None:
    nurses = st.session_state.nurses
    fixed  = st.session_state.fixed_schedules

    section(1, "등록된 고정 일정", f"{len(fixed)}건")
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

    section(2, "고정 일정 추가", "연차 · 병가 · 교육 등", variant="amber")
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

    c_add, c_clear, _ = st.columns([1, 1, 4])
    with c_add:
        if st.button("추가", key="btn_add_fs", type="primary", use_container_width=True):
            fs = FixedSchedule(
                nurse_id=nurse_opts[sel_name],
                date=sel_date,
                schedule_type=FixedScheduleType(sel_type),
                note=note,
            )
            st.session_state.fixed_schedules.append(fs)
            st.success(f"{sel_name} {sel_date} → {fs.shift_code.value} ({sel_type}) 등록")
            st.rerun()
    with c_clear:
        if fixed and st.button("전체 초기화", key="btn_clear_fs", use_container_width=True):
            st.session_state.fixed_schedules = []
            st.rerun()


# ─────────────────────────────────────────────
# 탭 5: 근무 코드표
# ─────────────────────────────────────────────

def render_code_reference_tab() -> None:
    section(1, "근무 코드 참조표", "38종 전체 코드")
    rows = []
    for s, meta in SHIFT_META.items():
        rows.append({
            "코드":     s.value,
            "명칭":     meta.label,
            "카테고리": meta.category,
            "근무":     "○" if meta.is_work  else "—",
            "야간":     "●" if meta.is_night else "—",
            "시작":     f"{meta.start_h:02d}:00" if meta.is_work else "—",
            "종료":     (
                f"{meta.end_h % 24:02d}:00{'(익일)' if meta.end_h >= 24 else ''}"
                if meta.is_work else "—"
            ),
        })
    df = pd.DataFrame(rows)

    def color_row(row):
        try:
            color = f"#{SHIFT_META[ShiftType(row['코드'])].color_hex}"
        except Exception:
            color = "#ffffff"
        return [f"background-color:{color};font-size:12px;"] * len(row)

    st.dataframe(
        df.style.apply(color_row, axis=1),
        use_container_width=True,
        hide_index=True,
        height=min(50 + len(rows) * 36, 820),
    )

    section(2, "카테고리 범례", variant="teal")
    cats = [
        ("#BDD7EE", "#1F618D", "work",  "실제 근무 (근무일수·피로도 산정)"),
        ("#EDEDED", "#4A4A4A", "off",   "비번 / 당직오프"),
        ("#C6EFCE", "#276221", "leave", "각종 휴가"),
        ("#FFC7CE", "#9C0006", "sick",  "병가"),
        ("#FFEB9C", "#9C5700", "edu",   "교육"),
        ("#D9D9D9", "#3A3A3A", "limit", "사용금지·제한"),
    ]
    badges = "".join(
        f'<span style="background:{bg};color:{fg};border:1px solid {fg}33;">'
        f'<b>{code}</b> &nbsp; {desc}</span>'
        for bg, fg, code, desc in cats
    )
    st.markdown(f'<div class="lgd">{badges}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────

def _heatmap_style(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    def _bg(val):
        try:
            v = float(val)
        except (TypeError, ValueError):
            return ""
        ratio = min(v / 15.0, 1.0)
        r, g, b = 255, int(255 * (1 - ratio * 0.85)), int(255 * (1 - ratio))
        return f"background-color:rgb({r},{g},{b});font-size:12px;"
    return df.style.map(_bg)


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────

def main() -> None:
    st.markdown(
        '<div class="app-header">'
        '<div class="crumb">병동 관리 / 근무표</div>'
        '<div class="title">병동 간호사 근무표 자동 생성 시스템</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    rules = render_sidebar()

    tabs = st.tabs(["근무표", "대시보드", "간호사", "고정 일정", "근무 코드표"])
    with tabs[0]: render_schedule_tab(rules)
    with tabs[1]: render_dashboard_tab()
    with tabs[2]: render_nurses_tab()
    with tabs[3]: render_fixed_tab()
    with tabs[4]: render_code_reference_tab()


if __name__ == "__main__":
    main()
