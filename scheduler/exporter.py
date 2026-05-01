"""
Import / Export 모듈.

지원 형식:
  - CSV  : pandas DataFrame ↔ Schedule
  - Excel (.xlsx) : openpyxl 기반 색상 포함 Excel
  - JSON : Schedule 직렬화 / 역직렬화

OCS/ERP 연동 구조:
  - export_for_erp() : {nurse_id, date, shift} 레코드 목록 반환
  - import_from_erp() : 동일 구조에서 Schedule 복원
"""

from __future__ import annotations

import csv
import datetime
import io
import json
from typing import Dict, List, Optional

import pandas as pd

from .models import (
    Nurse,
    Schedule,
    ScheduleConfig,
    ScheduleEntry,
    ShiftType,
)

# Excel 셀 색상 (Shift별)
SHIFT_COLORS = {
    ShiftType.DAY:     "B8E4F9",   # 하늘
    ShiftType.EVENING: "FFD966",   # 노랑
    ShiftType.NIGHT:   "9FC5E8",   # 파랑
    ShiftType.OFF:     "EFEFEF",   # 회색
}

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


class ScheduleExporter:
    """
    근무표 Import / Export.

    사용법:
        exporter = ScheduleExporter(nurses)
        df = exporter.to_dataframe(schedule)
        excel_bytes = exporter.to_excel(schedule)
        schedule = exporter.from_dataframe(df, nurses)
    """

    def __init__(self, nurses: List[Nurse]) -> None:
        self.nurses = nurses
        self.nurse_map = {n.id: n for n in nurses}

    # ──────────────────────────────────────────
    # DataFrame 변환 (UI Grid 기반)
    # ──────────────────────────────────────────

    def to_dataframe(self, schedule: Schedule) -> pd.DataFrame:
        """
        Schedule → DataFrame.

        행: 간호사 이름 (skill_level 포함)
        열: 날짜 (MM/DD 요일)
        값: Shift 코드 (D/E/N/OFF)
        """
        matrix = schedule.as_matrix(self.nurses)
        dates = sorted(
            {e.date for e in schedule.entries}
        )

        rows = []
        for nurse in self.nurses:
            row = {
                "간호사": f"{nurse.name} ({nurse.skill_level.value})",
                "ID": nurse.id,
            }
            for d in dates:
                col = f"{d.month}/{d.day}\n{WEEKDAY_KR[d.weekday()]}"
                shift = matrix[nurse.id].get(d, ShiftType.OFF)
                row[col] = shift.value
            rows.append(row)

        df = pd.DataFrame(rows)
        df.set_index("간호사", inplace=True)
        df.drop(columns=["ID"], inplace=True)
        return df

    def to_summary_dataframe(self, schedule: Schedule) -> pd.DataFrame:
        """간호사별 근무 통계 요약 DataFrame."""
        matrix = schedule.as_matrix(self.nurses)
        rows = []
        for nurse in self.nurses:
            hist = matrix[nurse.id]
            work_days = sum(1 for s in hist.values() if s != ShiftType.OFF)
            nights = sum(1 for s in hist.values() if s == ShiftType.NIGHT)
            weekends = sum(
                1 for d, s in hist.items()
                if d.weekday() >= 5 and s != ShiftType.OFF
            )
            rows.append({
                "이름": nurse.name,
                "경력": nurse.skill_level.value,
                "근무일": work_days,
                "D": sum(1 for s in hist.values() if s == ShiftType.DAY),
                "E": sum(1 for s in hist.values() if s == ShiftType.EVENING),
                "N": nights,
                "OFF": sum(1 for s in hist.values() if s == ShiftType.OFF),
                "주말": weekends,
            })
        return pd.DataFrame(rows)

    # ──────────────────────────────────────────
    # CSV
    # ──────────────────────────────────────────

    def to_csv(self, schedule: Schedule) -> str:
        """Schedule → CSV 문자열."""
        df = self.to_dataframe(schedule)
        return df.to_csv(encoding="utf-8-sig")

    def from_csv(
        self,
        csv_content: str,
        ward_id: str,
        year: int,
        month: int,
    ) -> Schedule:
        """CSV 문자열 → Schedule."""
        df = pd.read_csv(io.StringIO(csv_content), index_col=0)
        return self._dataframe_to_schedule(df, ward_id, year, month)

    # ──────────────────────────────────────────
    # Excel
    # ──────────────────────────────────────────

    def to_excel(self, schedule: Schedule) -> bytes:
        """Schedule → Excel bytes (색상 포함)."""
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
            from openpyxl.utils import get_column_letter
        except ImportError:
            raise ImportError("openpyxl 이 설치되지 않았습니다: pip install openpyxl")

        wb = Workbook()
        ws = wb.active
        ws.title = f"{schedule.year}-{schedule.month:02d} 근무표"

        df = self.to_dataframe(schedule)
        dates = sorted({e.date for e in schedule.entries})

        # 헤더 행 작성
        ws.cell(row=1, column=1, value="간호사").font = Font(bold=True)
        for col_idx, d in enumerate(dates, start=2):
            cell = ws.cell(
                row=1,
                column=col_idx,
                value=f"{d.month}/{d.day}({WEEKDAY_KR[d.weekday()]})",
            )
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")
            # 주말 헤더 색상
            if d.weekday() >= 5:
                cell.fill = PatternFill("solid", fgColor="FFD7D7")

        # 데이터 행
        matrix = schedule.as_matrix(self.nurses)
        for row_idx, nurse in enumerate(self.nurses, start=2):
            ws.cell(
                row=row_idx,
                column=1,
                value=f"{nurse.name} ({nurse.skill_level.value})",
            ).font = Font(bold=nurse.skill_level.value == "숙련")

            for col_idx, d in enumerate(dates, start=2):
                shift = matrix[nurse.id].get(d, ShiftType.OFF)
                cell = ws.cell(row=row_idx, column=col_idx, value=shift.value)
                cell.alignment = Alignment(horizontal="center")
                color = SHIFT_COLORS.get(shift, "FFFFFF")
                cell.fill = PatternFill("solid", fgColor=color)

        # 열 너비 자동 조정
        ws.column_dimensions["A"].width = 18
        for col_idx in range(2, len(dates) + 2):
            ws.column_dimensions[get_column_letter(col_idx)].width = 6

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def from_excel(
        self,
        excel_bytes: bytes,
        ward_id: str,
        year: int,
        month: int,
    ) -> Schedule:
        """Excel bytes → Schedule."""
        df = pd.read_excel(io.BytesIO(excel_bytes), index_col=0)
        return self._dataframe_to_schedule(df, ward_id, year, month)

    # ──────────────────────────────────────────
    # JSON (직렬화 / 역직렬화)
    # ──────────────────────────────────────────

    def to_json(self, schedule: Schedule) -> str:
        """Schedule → JSON 문자열."""
        return schedule.model_dump_json(indent=2)

    def from_json(self, json_str: str) -> Schedule:
        """JSON 문자열 → Schedule."""
        return Schedule.model_validate_json(json_str)

    # ──────────────────────────────────────────
    # ERP / OCS 연동 구조
    # ──────────────────────────────────────────

    def export_for_erp(self, schedule: Schedule) -> List[Dict]:
        """
        ERP/OCS 시스템으로 전달할 표준 레코드 목록.

        각 레코드:
          {nurse_id, nurse_name, date, shift_code, shift_name, is_holiday, is_weekend}
        """
        records = []
        nurse_map = {n.id: n for n in self.nurses}
        shift_names = {
            ShiftType.DAY: "주간",
            ShiftType.EVENING: "저녁",
            ShiftType.NIGHT: "야간",
            ShiftType.OFF: "휴무",
        }
        for entry in schedule.entries:
            nurse = nurse_map.get(entry.nurse_id)
            records.append({
                "nurse_id": entry.nurse_id,
                "nurse_name": nurse.name if nurse else "",
                "date": entry.date.isoformat(),
                "shift_code": entry.shift.value,
                "shift_name": shift_names[entry.shift],
                "is_holiday": entry.is_holiday,
                "is_weekend": entry.is_weekend,
                "is_fixed": entry.is_fixed,
            })
        return records

    def import_from_erp(
        self,
        records: List[Dict],
        ward_id: str,
        year: int,
        month: int,
    ) -> Schedule:
        """ERP 레코드 목록 → Schedule."""
        entries = []
        for rec in records:
            entries.append(
                ScheduleEntry(
                    nurse_id=rec["nurse_id"],
                    date=datetime.date.fromisoformat(rec["date"]),
                    shift=ShiftType(rec["shift_code"]),
                    is_fixed=rec.get("is_fixed", False),
                    is_holiday=rec.get("is_holiday", False),
                    is_weekend=rec.get("is_weekend", False),
                )
            )
        return Schedule(
            ward_id=ward_id,
            year=year,
            month=month,
            entries=entries,
            generated_at=datetime.datetime.now(),
        )

    # ──────────────────────────────────────────
    # 내부 헬퍼
    # ──────────────────────────────────────────

    def _dataframe_to_schedule(
        self,
        df: pd.DataFrame,
        ward_id: str,
        year: int,
        month: int,
    ) -> Schedule:
        """DataFrame → Schedule (CSV/Excel 공용)."""
        entries = []
        name_to_id = {f"{n.name} ({n.skill_level.value})": n.id for n in self.nurses}

        for nurse_label in df.index:
            nurse_id = name_to_id.get(str(nurse_label))
            if nurse_id is None:
                continue
            for col in df.columns:
                # 열 이름에서 날짜 파싱 (형식: "M/D\n요일" 또는 "M/D(요일)")
                try:
                    date_part = str(col).split("\n")[0].split("(")[0].strip()
                    m, d = map(int, date_part.split("/"))
                    date = datetime.date(year, m, d)
                except (ValueError, IndexError):
                    continue

                raw = str(df.loc[nurse_label, col]).strip().upper()
                try:
                    shift = ShiftType(raw)
                except ValueError:
                    shift = ShiftType.OFF

                entries.append(
                    ScheduleEntry(
                        nurse_id=nurse_id,
                        date=date,
                        shift=shift,
                        is_fixed=True,  # 외부 입력은 고정으로 처리
                        is_weekend=date.weekday() >= 5,
                    )
                )
        return Schedule(
            ward_id=ward_id,
            year=year,
            month=month,
            entries=entries,
            generated_at=datetime.datetime.now(),
        )
