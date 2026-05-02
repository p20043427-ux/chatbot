"""
병동 간호사 근무표 자동 생성 시스템 — Streamlit UI.

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
    WORK_SHIFTS,
    FixedScheduleType,
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
# 디자인 시스템 CSS
# ─────────────────────────────────────────────

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap');

/* ── Tokens ─────────────────────────────── */
:root {
  --navy:        #1B2238;
  --navy-hover:  #26314F;
  --navy-deep:   #131929;
  --teal:        #2A82C8;
  --bg:          #EEF1F8;
  --card:        #FFFFFF;
  --border:      #E0E6F0;
  --border-side: #2D3A56;
  --text:        #1A202C;
  --text-sub:    #4A5568;
  --text-muted:  #718096;
  --side-text:   #A8B9D0;
  --side-label:  #5C7299;

  --success: #1E8449;
  --warning: #B7770D;
  --danger:  #B03A2E;

  --r-sm: 6px;
  --r-md: 10px;
  --r-lg: 14px;
  --shadow: 0 2px 8px rgba(0,0,0,0.07);
}

/* ── Global ──────────────────────────────── */
html, body, [class*="css"] {
  font-family: 'Noto Sans KR', -apple-system, sans-serif !important;
  font-size: 13px;
  color: var(--text);
}
.stApp { background: var(--bg) !important; }
.main .block-container {
  padding: 20px 32px 48px !important;
  max-width: 1400px;
}

/* ── Dark Sidebar ────────────────────────── */
section[data-testid="stSidebar"] {
  background: var(--navy) !important;
  border-right: none !important;
}
section[data-testid="stSidebar"] > div:first-child {
  background: var(--navy) !important;
}
section[data-testid="stSidebar"] > div {
  background: var(--navy) !important;
}

/* Sidebar text overrides */
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span:not([data-testid]),
section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p {
  color: var(--side-text) !important;
}
section[data-testid="stSidebar"] label {
  color: var(--side-text) !important;
  font-size: 12px !important;
  font-weight: 500 !important;
}
section[data-testid="stSidebar"] hr {
  border-color: var(--border-side) !important;
  margin: 6px 0 !important;
}

/* Sidebar number inputs */
section[data-testid="stSidebar"] input {
  background: #2D3A56 !important;
  border-color: #3D4E6E !important;
  color: #E8EDF5 !important;
  border-radius: var(--r-sm) !important;
}

/* Sidebar checkbox */
section[data-testid="stSidebar"] [data-testid="stCheckbox"] span {
  color: var(--side-text) !important;
}

/* Slider min/max labels */
section[data-testid="stSidebar"] [data-testid="stTickBarMin"],
section[data-testid="stSidebar"] [data-testid="stTickBarMax"] {
  color: var(--side-label) !important;
}

/* ── Sidebar Brand ───────────────────────── */
.sb-brand {
  padding: 6px 0 14px;
  border-bottom: 1px solid var(--border-side);
  margin-bottom: 6px;
}
.sb-brand-title {
  color: #FFFFFF !important;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.3;
}
.sb-brand-sub {
  color: var(--side-label) !important;
  font-size: 10px;
  letter-spacing: 0.6px;
  margin-top: 2px;
}
.sb-section-label {
  color: var(--side-label) !important;
  font-size: 10px !important;
  font-weight: 700 !important;
  text-transform: uppercase;
  letter-spacing: 0.9px;
  padding: 14px 0 5px;
  display: block;
}

/* ── Page Title ──────────────────────────── */
.ds-page-header {
  margin-bottom: 20px;
}
.ds-breadcrumb {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.ds-page-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--navy);
  letter-spacing: -0.5px;
}

/* ── Card Sections ───────────────────────── */
.ds-card-hdr {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 15px 11px;
  background: #F6F8FC;
  border-bottom: 1px solid var(--border);
  margin: -1px -1px 12px -1px;
  border-radius: var(--r-md) var(--r-md) 0 0;
}
.ds-icon {
  width: 30px; height: 30px;
  border-radius: var(--r-sm);
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; flex-shrink: 0;
}
.icon-blue   { background: #DBEAFE; }
.icon-green  { background: #D1FAE5; }
.icon-red    { background: #FEE2E2; }
.icon-amber  { background: #FEF3C7; }
.icon-purple { background: #EDE9FE; }
.icon-gray   { background: #E5E7EB; }

.ds-card-title { font-size: 14px; font-weight: 600; color: var(--navy); }
.ds-card-sub   { font-size: 11px; color: var(--text-muted); margin-top: 1px; }

/* ── Metric Cards ────────────────────────── */
.ds-metric-row {
  display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px;
}
.ds-metric {
  flex: 1; min-width: 110px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow);
  padding: 13px 16px;
  text-align: center;
}
.ds-metric-label {
  font-size: 10px; font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.5px;
  margin-bottom: 7px;
}
.ds-metric-value {
  font-size: 24px; font-weight: 700;
  color: var(--navy); line-height: 1.1;
}
.ds-metric-sub { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.ds-metric.v-danger  .ds-metric-value { color: var(--danger); }
.ds-metric.v-success .ds-metric-value { color: var(--success); }
.ds-metric.v-warning .ds-metric-value { color: var(--warning); }
.ds-metric.v-accent  .ds-metric-value { color: var(--teal); }

/* ── Violation Tags ──────────────────────── */
.viol-hard {
  display: inline-block;
  background: #FEF2F2; color: var(--danger);
  border: 1px solid #FECACA;
  border-radius: var(--r-sm);
  padding: 3px 10px 3px 8px;
  font-size: 12px; font-weight: 500;
  margin: 2px 0; line-height: 1.6;
}

/* ── Buttons ─────────────────────────────── */
.stButton > button {
  height: 40px;
  font-size: 13px;
  font-weight: 600;
  border-radius: var(--r-sm);
  border: 1px solid #C0CAD8;
  transition: background 0.12s ease, border-color 0.12s ease;
  letter-spacing: 0.1px;
}
.stButton > button[kind="primary"] {
  background: var(--navy) !important;
  color: #FFFFFF !important;
  border-color: var(--navy) !important;
}
.stButton > button[kind="primary"]:hover {
  background: var(--navy-hover) !important;
  border-color: var(--navy-hover) !important;
}

/* ── Tabs ────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
  background: transparent;
  border-bottom: 2px solid var(--border);
  gap: 0;
}
.stTabs [data-baseweb="tab"] {
  font-size: 13px; font-weight: 600;
  color: var(--text-muted);
  padding: 9px 20px;
  border-radius: var(--r-sm) var(--r-sm) 0 0;
  background: transparent;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
}
.stTabs [aria-selected="true"] {
  color: var(--navy) !important;
  border-bottom: 2px solid var(--navy) !important;
  background: var(--card) !important;
}

/* ── DataFrames ──────────────────────────── */
[data-testid="stDataFrame"] {
  border: 1px solid var(--border) !important;
  border-radius: var(--r-md) !important;
  overflow: hidden !important;
}

/* ── Alerts ──────────────────────────────── */
.stAlert { border-radius: var(--r-md) !important; font-size: 13px; }

/* ── Expanders ───────────────────────────── */
.streamlit-expanderHeader {
  font-size: 13px !important;
  font-weight: 600 !important;
  color: var(--text-sub) !important;
  background: var(--card) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--r-sm) !important;
}

/* ── Inputs ──────────────────────────────── */
.stSelectbox label, .stNumberInput label, .stTextInput label,
.stDateInput label, .stMultiSelect label, .stSlider label,
.stCheckbox label {
  font-size: 12px !important;
  font-weight: 600 !important;
  color: var(--text-sub) !important;
}

/* ── File uploader ───────────────────────── */
[data-testid="stFileUploadDropzone"] {
  background: #EBF4FA;
  border: 1.5px dashed var(--teal) !important;
  border-radius: var(--r-md) !important;
  font-size: 13px;
}

/* ── Legend badges ───────────────────────── */
.legend-row { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
.legend-badge {
  padding: 4px 14px;
  border-radius: 20px;
  font-size: 11px; font-weight: 600;
}

/* Container border override for card look */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--border) !important;
  border-radius: var(--r-lg) !important;
  box-shadow: var(--shadow) !important;
  background: var(--card) !important;
}
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 디자인 헬퍼
# ─────────────────────────────────────────────

def _card_header(icon: str, title: str, subtitle: str = "", icon_cls: str = "icon-blue") -> None:
    sub_html = f'<div class="ds-card-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="ds-card-hdr">'
        f'  <div class="ds-icon {icon_cls}">{icon}</div>'
        f'  <div>'
        f'    <div class="ds-card-title">{title}</div>'
        f'    {sub_html}'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _metric(label: str, value: str, sub: str = "", variant: str = "") -> str:
    cls = f"ds-metric {variant}".strip()
    sub_html = f'<div class="ds-metric-sub">{sub}</div>' if sub else ""
    return (
        f'<div class="{cls}">'
        f'  <div class="ds-metric-label">{label}</div>'
        f'  <div class="ds-metric-value">{value}</div>'
        f'  {sub_html}'
        f'</div>'
    )


def _metric_row(*cards: str) -> None:
    st.markdown(f'<div class="ds-metric-row">{"".join(cards)}</div>', unsafe_allow_html=True)


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
    # 브랜드
    st.sidebar.markdown(
        '<div class="sb-brand">'
        '  <div class="sb-brand-title">병동 근무표 시스템</div>'
        '  <div class="sb-brand-sub">NURSE SCHEDULE v2.0</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # 대상 기간
    st.sidebar.markdown('<span class="sb-section-label">대상 기간</span>', unsafe_allow_html=True)
    c1, c2 = st.sidebar.columns(2)
    st.session_state.year  = c1.number_input("연도", value=st.session_state.year,  min_value=2020, max_value=2030, label_visibility="visible")
    st.session_state.month = c2.number_input("월",   value=st.session_state.month, min_value=1,    max_value=12,   label_visibility="visible")

    st.sidebar.divider()
    st.sidebar.markdown('<span class="sb-section-label">Hard Constraint</span>', unsafe_allow_html=True)
    max_consec = st.sidebar.slider("최대 연속 근무일",         3, 10, 5)
    night_rest = st.sidebar.checkbox("야간 후 다음날 OFF 강제", value=True)
    max_nights = st.sidebar.slider("최대 연속 야간",           1,  7, 3)
    min_rest_h = st.sidebar.slider("교대 간 최소 휴식 (시간)", 8, 16, 11)

    st.sidebar.divider()
    st.sidebar.markdown('<span class="sb-section-label">Shift 최소 인원</span>', unsafe_allow_html=True)
    c1, c2 = st.sidebar.columns(2)
    d_min = c1.number_input("Day 최소",   value=4, min_value=1, key="d_min")
    d_snr = c2.number_input("Day 숙련",   value=1, min_value=0, key="d_snr")
    e_min = c1.number_input("Eve 최소",   value=3, min_value=1, key="e_min")
    e_snr = c2.number_input("Eve 숙련",   value=1, min_value=0, key="e_snr")
    n_min = c1.number_input("Night 최소", value=2, min_value=1, key="n_min")
    n_snr = c2.number_input("Night 숙련", value=1, min_value=0, key="n_snr")

    st.sidebar.divider()
    st.sidebar.markdown('<span class="sb-section-label">공정성 가중치</span>', unsafe_allow_html=True)
    w_night   = st.sidebar.slider("야간",   0.0, 5.0, 1.5, 0.1)
    w_weekend = st.sidebar.slider("주말",   0.0, 5.0, 1.0, 0.1)
    w_holiday = st.sidebar.slider("공휴일", 0.0, 5.0, 2.0, 0.1)
    pref_rate = st.sidebar.slider("선호 반영 목표 (%)", 0, 100, 70, 5) / 100

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
    # 액션 버튼 카드
    with st.container(border=True):
        _card_header("▶", "근무표 생성", "자동 배정 또는 최적화 포함 생성", icon_cls="icon-blue")
        col_gen, col_opt, col_exp = st.columns(3)
        with col_gen:
            if st.button("자동 생성", type="primary", use_container_width=True):
                _run_generation(rules, optimize=False)
        with col_opt:
            if st.button("생성 + 최적화", use_container_width=True):
                _run_generation(rules, optimize=True)
        with col_exp:
            if st.session_state.schedule:
                exporter = ScheduleExporter(st.session_state.nurses)
                excel_bytes = exporter.to_excel(st.session_state.schedule)
                st.download_button(
                    "Excel 다운로드",
                    data=excel_bytes,
                    file_name=f"schedule_{st.session_state.year}_{st.session_state.month:02d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    # 파일 업로드 카드
    with st.container(border=True):
        _card_header("↑", "Excel / CSV 업로드", "기존 근무표 불러오기", icon_cls="icon-green")
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
        st.session_state.eval_result = ScheduleEvaluator(config).evaluate(schedule)
        st.session_state.schedule    = schedule

    shortage = schedule.generation_params.get("shortage_log", [])
    if shortage:
        with st.expander(f"인력 부족 경고 ({len(shortage)}건)", expanded=True):
            for msg in shortage:
                st.warning(msg)
    else:
        st.success("근무표 생성 완료")


def _render_schedule_grid(schedule: Schedule, rules: ScheduleRules) -> None:
    # 그리드
    with st.container(border=True):
        _card_header("☰", "근무표 Grid", f"{st.session_state.year}년 {st.session_state.month}월", icon_cls="icon-blue")
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
            return f"background-color:{color}; font-weight:{bold}; text-align:center; font-size:12px;"

        st.dataframe(
            df.style.map(color_shift),
            use_container_width=True,
            height=min(55 + len(st.session_state.nurses) * 36, 650),
        )

    # 수동 셀 편집
    with st.container(border=True):
        _card_header("✏", "수동 셀 수정", "고정 후 재생성 시에도 유지됩니다", icon_cls="icon-amber")
        c1, c2, c3, c4 = st.columns(4)
        nurse_options = {n.name: n.id for n in st.session_state.nurses}
        sel_name = c1.selectbox("간호사", list(nurse_options.keys()), key="mc_nurse")
        sel_nid  = nurse_options[sel_name]

        import calendar
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
            st.success(f"{sel_name} {sel_date}: {sel_shift_val} ({get_shift_label(ShiftType(sel_shift_val))}) 고정")
            st.rerun()

    # Hard 위반
    if st.session_state.eval_result:
        er = st.session_state.eval_result
        hard_viols = [v for v in er.constraint_result.violations if v.is_hard]
        with st.container(border=True):
            icon_cls = "icon-red" if hard_viols else "icon-green"
            sub = f"{len(hard_viols)}건 위반 발생" if hard_viols else "모든 조건을 만족합니다"
            _card_header("!", "Hard Constraint 검증", sub, icon_cls=icon_cls)
            if hard_viols:
                for v in hard_viols:
                    st.markdown(
                        f'<div class="viol-hard">[{v.constraint}] {v.reason}</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.success("Hard Constraint 위반 없음")

    # 요약 통계
    with st.container(border=True):
        _card_header("≡", "개인별 근무 요약", icon_cls="icon-gray")
        exporter2 = ScheduleExporter(st.session_state.nurses)
        st.dataframe(exporter2.to_summary_dataframe(schedule), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────
# 탭 2: 대시보드
# ─────────────────────────────────────────────

def render_dashboard_tab() -> None:
    if not st.session_state.schedule or not st.session_state.eval_result:
        st.info("먼저 '근무표' 탭에서 근무표를 생성해주세요.")
        return

    er  = st.session_state.eval_result
    sch = st.session_state.schedule

    # 종합 지표
    with st.container(border=True):
        _card_header("◈", "종합 평가 지표", icon_cls="icon-blue")
        hard_cnt = sum(1 for v in er.constraint_result.violations if v.is_hard)
        _metric_row(
            _metric("종합 점수",   f"{er.overall_score:.1f}", sub="/ 100"),
            _metric("Hard 위반",   str(hard_cnt),
                    variant="v-danger" if hard_cnt > 0 else "v-success"),
            _metric("인력 충족률", f"{er.staffing_coverage_rate*100:.0f}%",
                    variant="v-success" if er.staffing_coverage_rate >= 0.9 else "v-warning"),
            _metric("선호 반영률", f"{er.preference_satisfaction_rate*100:.0f}%"),
            _metric("평균 피로도", f"{er.average_fatigue_score:.2f}", variant="v-accent"),
        )

    # 분포 차트
    evaluator = ScheduleEvaluator(ScheduleConfig(
        ward=st.session_state.ward, nurses=st.session_state.nurses,
        rules=ScheduleRules(), year=st.session_state.year, month=st.session_state.month,
    ))

    col1, col2 = st.columns(2)
    _CHART_LAYOUT = dict(
        showlegend=False, height=270,
        margin=dict(l=12, r=12, t=20, b=12),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="Noto Sans KR, sans-serif", size=11),
    )
    with col1:
        with st.container(border=True):
            _card_header("◑", "야간 근무 분포", icon_cls="icon-purple")
            night_dist = evaluator.get_night_distribution(sch)
            fig = px.bar(
                x=list(night_dist.keys()), y=list(night_dist.values()),
                labels={"x": "", "y": "횟수"},
                color=list(night_dist.values()), color_continuous_scale="Blues",
            )
            fig.update_layout(**_CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        with st.container(border=True):
            _card_header("◔", "주말 근무 분포", icon_cls="icon-amber")
            we_dist = evaluator.get_weekend_distribution(sch)
            fig = px.bar(
                x=list(we_dist.keys()), y=list(we_dist.values()),
                labels={"x": "", "y": "횟수"},
                color=list(we_dist.values()), color_continuous_scale="Oranges",
            )
            fig.update_layout(**_CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)

    # Shift 분포
    with st.container(border=True):
        _card_header("▦", "개인별 Shift 분포", icon_cls="icon-green")
        rows = []
        for stat in er.nurse_stats:
            row = {"이름": stat.nurse_name, "근무일": stat.total_work_days}
            row.update({k: v for k, v in stat.shift_counts.items()})
            row.update({"주말": stat.weekend_shifts, "공휴일": stat.holiday_shifts})
            rows.append(row)
        shift_df = pd.DataFrame(rows).set_index("이름").fillna(0).astype(int, errors="ignore")
        st.dataframe(_heatmap_style(shift_df), use_container_width=True)

    # 피로도 Heatmap
    with st.container(border=True):
        _card_header("▣", "피로도 Heatmap", icon_cls="icon-red")
        fatigue_matrix = evaluator.get_fatigue_matrix(sch)
        import calendar
        _, last_day = calendar.monthrange(st.session_state.year, st.session_state.month)
        dates = [datetime.date(st.session_state.year, st.session_state.month, d) for d in range(1, last_day + 1)]
        date_labels  = [f"{d.month}/{d.day}" for d in dates]
        nurse_names  = [n.name for n in st.session_state.nurses]
        z_data = [[fatigue_matrix.get(name, {}).get(d, 0) for d in dates] for name in nurse_names]
        fig_heat = go.Figure(data=go.Heatmap(
            z=z_data, x=date_labels, y=nurse_names,
            colorscale="YlOrRd", showscale=True,
        ))
        fig_heat.update_layout(
            height=max(260, len(nurse_names) * 28),
            margin=dict(l=12, r=12, t=20, b=12),
            xaxis_nticks=15,
            plot_bgcolor="white", paper_bgcolor="white",
            font=dict(family="Noto Sans KR, sans-serif", size=11),
        )
        st.plotly_chart(fig_heat, use_container_width=True)

    # 공정성
    with st.container(border=True):
        _card_header("⊜", "공정성 분석", "값이 낮을수록 균등한 배분", icon_cls="icon-gray")
        _metric_row(
            _metric("야간 편차 (std)",   f"{er.night_fairness_score:.2f}"),
            _metric("주말 편차 (std)",   f"{er.weekend_fairness_score:.2f}"),
            _metric("공휴일 편차 (std)", f"{er.holiday_fairness_score:.2f}"),
        )


# ─────────────────────────────────────────────
# 탭 3: 간호사 관리
# ─────────────────────────────────────────────

def render_nurses_tab() -> None:
    with st.container(border=True):
        _card_header("♟", "간호사 목록", f"총 {len(st.session_state.nurses)}명", icon_cls="icon-blue")
        nurses = st.session_state.nurses
        data = [{
            "ID":         n.id,
            "이름":       n.name,
            "경력":       n.skill_level.value,
            "가능 병동":  ", ".join(w.value for w in n.ward_qualifications),
            "가능 Shift": ", ".join(s.value for s in n.allowed_shifts),
        } for n in nurses]
        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

    with st.container(border=True):
        _card_header("+", "간호사 추가", icon_cls="icon-green")
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
        new_wards = st.multiselect("가능 병동", [w.value for w in WardType], default=["일반"], key="nn_wards")

        col_add, col_reset, _ = st.columns([1, 1, 3])
        with col_add:
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
        with col_reset:
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

    with st.container(border=True):
        _card_header("◈", "등록된 고정 일정", f"{len(fixed)}건", icon_cls="icon-purple")
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

    with st.container(border=True):
        _card_header("+", "고정 일정 추가", "연차·병가·교육 등 고정 일정을 등록합니다", icon_cls="icon-amber")
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

        col_add, col_clear, _ = st.columns([1, 1, 4])
        with col_add:
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
        with col_clear:
            if fixed and st.button("전체 초기화", key="btn_clear_fs", use_container_width=True):
                st.session_state.fixed_schedules = []
                st.rerun()


# ─────────────────────────────────────────────
# 탭 5: 근무 코드표
# ─────────────────────────────────────────────

def render_code_reference_tab() -> None:
    with st.container(border=True):
        _card_header("☰", "근무 코드 참조표", "38종 전체 코드 목록", icon_cls="icon-blue")
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
            return [f"background-color:{color}; font-size:12px;"] * len(row)

        st.dataframe(
            df.style.apply(color_row, axis=1),
            use_container_width=True,
            hide_index=True,
            height=min(50 + len(rows) * 36, 820),
        )

    with st.container(border=True):
        _card_header("◉", "카테고리 범례", icon_cls="icon-gray")
        cats = [
            ("#BDD7EE", "#1F618D", "work",  "실제 근무 (근무일수·피로도 산정)"),
            ("#EDEDED", "#4A4A4A", "off",   "비번 / 당직오프"),
            ("#C6EFCE", "#276221", "leave", "각종 휴가 (연차·공가·경조·분만·육아·무급)"),
            ("#FFC7CE", "#9C0006", "sick",  "병가"),
            ("#FFEB9C", "#9C5700", "edu",   "교육 (전일·반일)"),
            ("#D9D9D9", "#3A3A3A", "limit", "사용금지·제한 코드"),
        ]
        html_badges = "".join(
            f'<span class="legend-badge" style="background:{bg};color:{fg};border:1px solid {fg}33;">'
            f'<b>{code}</b> — {desc}</span>'
            for bg, fg, code, desc in cats
        )
        st.markdown(f'<div class="legend-row">{html_badges}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────

def _heatmap_style(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    def _cell_bg(val):
        try:
            v = float(val)
        except (TypeError, ValueError):
            return ""
        ratio = min(v / 15.0, 1.0)
        r = 255
        g = int(255 * (1 - ratio * 0.85))
        b = int(255 * (1 - ratio))
        return f"background-color:rgb({r},{g},{b}); font-size:12px;"
    return df.style.map(_cell_bg)


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────

def main() -> None:
    st.markdown(
        '<div class="ds-page-header">'
        '  <div class="ds-breadcrumb">병동 관리 / 근무표</div>'
        '  <div class="ds-page-title">병동 간호사 근무표 자동 생성 시스템</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    rules = render_sidebar()

    tab_sch, tab_dash, tab_nurse, tab_fixed, tab_code = st.tabs([
        "근무표",
        "대시보드",
        "간호사",
        "고정 일정",
        "근무 코드표",
    ])

    with tab_sch:   render_schedule_tab(rules)
    with tab_dash:  render_dashboard_tab()
    with tab_nurse: render_nurses_tab()
    with tab_fixed: render_fixed_tab()
    with tab_code:  render_code_reference_tab()


if __name__ == "__main__":
    main()
