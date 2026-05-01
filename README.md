# 🏥 병동 간호사 근무표 자동 생성 시스템

제약 조건 기반 최적화(Constraint Optimization)를 활용한 실운영 수준의 간호사 스케줄링 시스템입니다.

---

## 🚀 빠른 시작

```bash
pip install -r requirements.txt
streamlit run ui/app.py
```

---

## 📁 프로젝트 구조

```
chatbot/
├── scheduler/
│   ├── models.py          # 데이터 모델 (Nurse, Ward, Schedule, Rules)
│   ├── constraints.py     # Hard/Soft Constraint 검증기
│   ├── algorithm.py       # Greedy 스케줄 생성기
│   ├── optimizer.py       # Simulated Annealing Local Search 최적화기
│   ├── evaluator.py       # 근무표 품질 평가기
│   └── exporter.py        # CSV/Excel/JSON Import·Export
├── ui/
│   └── app.py             # Streamlit 웹 UI
├── tests/
│   ├── sample_data.py     # 샘플 간호사·병동·규칙 데이터
│   └── test_scenarios.py  # 7가지 테스트 시나리오
├── data/
│   └── sample_config.json # JSON 설정 예시
└── requirements.txt
```

---

## 🧠 알고리즘 설계

### 선택: Greedy + Simulated Annealing Local Search

| 방식 | 선택 이유 | 시간 복잡도 | 장점 | 단점 |
|------|-----------|------------|------|------|
| **Greedy + SA** (채택) | 명확한 규칙 → 빠른 초기해, SA로 품질 개선 | O(D×S×N) + O(iter×N²) | 빠름(<5초), 설명 쉬움 | 전역 최적 보장 불가 |
| OR-Tools CP-SAT | 전역 최적 보장 | NP-hard (실용적 범위) | 수학적 최적 | 의존성 무거움, 규모 커지면 느려짐 |
| Genetic Algorithm | 탐색 범위 넓음 | O(G×P×fitness) | 다목적 최적화 | 수렴 느림, 파라미터 민감 |

### 2단계 생성 흐름

```
1단계: GreedyScheduler
  ↓ Night → Evening → Day 순서로 날짜 순회
  ↓ 공정성 점수(야간/주말 누적) 낮은 간호사 우선
  ↓ ConstraintChecker.can_assign() → Hard Constraint 검증
  → 초기 근무표 (60~80% 품질)

2단계: LocalSearchOptimizer (Simulated Annealing)
  ↓ 2-opt Swap: 두 간호사의 같은 날짜 shift 교환
  ↓ 수용 조건: delta<0 무조건 | delta>=0 → exp(-delta/T) 확률
  ↓ 스왑 전 Hard Constraint + Forward(다음날) 검증
  → 최적화 근무표 (80~95% 품질)
```

---

## 제약 조건

### Hard Constraints (반드시 준수)
| 제약 | 설명 |
|------|------|
| 최소 인원 충족 | Shift별 최소 간호사 수 (관리자 설정) |
| Night → Day/Evening 전환 금지 | Night 직후 반드시 OFF |
| 최대 연속 근무일 | 기본 5일 (1~14일 설정 가능) |
| 최대 연속 Night | 기본 3회 (1~7회 설정 가능) |
| 숙련자 최소 포함 | Shift별 숙련 간호사 수 보장 |
| 고정 일정 준수 | 연차/병가/교육 날짜 자동 OFF |

### Soft Constraints (최적화 목표)
| 제약 | 페널티 방식 |
|------|------------|
| 야간 근무 균등 분배 | 표준편차 × 공정성 가중치 |
| 주말 근무 균등 분배 | 표준편차 × 주말 가중치 |
| 개인 선호 반영 | 미반영 건당 페널티 |
| 피로도 최소화 | 연속 근무·야간 집중도 가중 합산 |

---

## 평가 지표 (0~100점)

| 항목 | 비중 |
|------|------|
| Hard Constraint 위반 없음 | 40점 |
| 인력 충족률 | 20점 |
| 공정성 편차 최소 | 20점 |
| 개인 선호 반영률 | 10점 |
| 피로도 최소 | 10점 |

---

## 테스트 시나리오

```bash
PYTHONPATH=. python tests/test_scenarios.py
```

| # | 시나리오 | 검증 포인트 |
|---|----------|------------|
| 1 | 정상 케이스 (12명) | 기본 생성 + 최적화 품질 |
| 2 | 인력 부족 (6명) | 부족 경고 발생 여부 |
| 3 | 연차 집중 (4명 동시) | 숙련자 부족 Hard 위반 감지 |
| 4 | Night 기피 (3명만 허용) | 야간 편중 현상 |
| 5 | 이전 달 연속 근무 연계 | 월 경계 연속 근무 방지 |
| 6 | 수동 고정 셀 유지 | 재생성 시 고정 셀 유지 |
| 7 | Hard Constraint 위반 감지 | Night→Day 직접 삽입 감지 |

---

## UI 화면 구성

| 탭 | 기능 |
|----|------|
| 근무표 | 자동 생성, Excel Grid, 수동 셀 편집, CSV/Excel 다운로드 |
| 대시보드 | 야간/주말 분포 차트, 피로도 Heatmap, 공정성 분석 |
| 간호사 | 간호사 추가/편집, 선호도 설정 |
| 고정 일정 | 연차/병가/교육 등록 |
| 시스템 정보 | 알고리즘 설명, 제약 조건 목록 |

사이드바에서 모든 근무 규칙(연속 근무 제한, 최소 인원, 공정성 가중치)을 실시간 조정할 수 있습니다.

---

## OCS/ERP 연동

`ScheduleExporter.export_for_erp()` / `import_from_erp()` 를 통해
`{nurse_id, date, shift_code, shift_name, is_holiday, is_weekend}` 표준 레코드로 연동합니다.

---

## 향후 확장 방안

1. **OR-Tools CP-SAT 통합**: 50명 이상 대규모 병동 최적 해 보장
2. **멀티 병동 통합**: 병동 간 인력 공유 및 통합 스케줄링
3. **실시간 알림**: 인력 부족 예측 알림 연동
4. **ML 선호도 학습**: 과거 수정 패턴으로 선호도 자동 업데이트
5. **모바일 간호사 앱**: 근무 확인/교환 요청 앱 연동
