# Val-Studio 디자인 시스템 (Design System)

## 1. 브랜드 아이덴티티 (Brand Identity)
*   **Primary Brand Color:** `Burgundy Wine` (버건디 와인)
    *   **Hex:** `#9f1239`
    *   **Tailwind Token:** `bg-rose-800`, `text-rose-800`, `border-rose-800`
    *   **상징성:** 럭셔리, 흔들리지 않는 권위, 묵직한 신뢰감. 글로벌 투자은행 및 프리미엄 금융 소프트웨어의 감성을 차용하여, 타 대형 회계법인(오렌지, 파랑, 초록, 노랑)와 완벽히 차별화하면서도 금융권 특유의 보수적인 안정감을 줍니다.

## 2. 핵심 UI/UX 원칙 (Enterprise Professional Aesthetic)
트렌디한 AI 스타트업 디자인(둥근 모서리, 넓은 여백, 그림자)을 철저히 배제하고, **실제 회계법인 실무진들이 엑셀처럼 편하게 쓸 수 있는 정통 엔터프라이즈 구조**를 따릅니다.

1.  **완벽한 직각 (Zero Border Radius)**
    *   모든 버튼, 인풋, 패널, 모달은 `rounded-none`을 기본으로 합니다. 
2.  **높은 데이터 밀도 (High Density Layout)**
    *   여백을 최소화하여 한 화면에 많은 데이터(테이블 행 등)를 빽빽하게 보여줍니다 (`px-2 py-1`, 텍스트 `text-sm` 위주).
3.  **미니멀한 1px 구분선 (1px Solid Borders)**
    *   요소 간의 구분은 그림자(`shadow`)나 그라데이션이 아닌, 명확한 1px 실선 테두리(`border border-gray-300`)를 사용합니다.
4.  **컬러 통제 (Strict Color Constraint)**
    *   화면의 95%는 무채색(White, Gray, Black)으로 구성합니다.
    *   버건디 와인 컬러는 **우측 상단의 메인 액션 버튼 1개, 활성화된 탭의 밑줄, 중요한 KPI의 수치** 등 가장 시선이 가야 할 곳에만 극도로 제한적으로 사용합니다.

## 3. 시맨틱 컬러 (Semantic Colors)
브랜드 컬러(버건디) 외에 시스템 상태를 나타낼 때만 쓰는 컬러입니다.
*   🟢 **Pass / Success:** `emerald-500` (#10b981) - 통과, 확인 완료
*   🟡 **Review / Warning:** `amber-500` (#f59e0b) - 검토 필요, 부분 일치
*   🔴 **Fail / Error:** `red-600` (#dc2626) - 치명적 오류, 필수 항목 누락
*   *(주의: 실패/에러 색상인 `red-600`이 브랜드 컬러인 `rose-800`과 충돌하지 않도록, 에러는 가급적 작은 아이콘이나 텍스트 컬러로만 사용합니다.)*

---

## 4. 검증 확정 (2026-07-17, 벤치마크 이미지 3장 + brand_color_palette.md 대조)

1. **상태색 충돌 해소 — muted 세트 채택**: §3 의 Tailwind 원색(emerald-500·amber-500·
   red-600)은 색상표의 "채도 높은 원색 남용 금지" 원칙과 모순 → **brand_color_palette.md
   의 muted 세트가 정본**: Success=Sage `#5b7c65` / Warning=Antique Gold `#c49b47` /
   Error=Burnt Rust `#cf3a36`(브랜드 자줏빛과 구분되는 주황빛 — 면적 금지, 텍스트·
   보더·아이콘만).
2. **KPI 색 사용 절제**: Easy View 처럼 KPI 전부 브랜드 배경 채움은 §2-4 "극도로
   제한적 사용"과 충돌 → **핵심 결론 1개(예: 주당가치)만 버건디 배경+백색 텍스트**,
   나머지 KPI 는 무채색 카드 + 버건디 수치 텍스트.
3. **레이아웃 정본 보완**(벤치마크 이미지에서 채택): ①좌측 다크 수직 LNB —
   활성 항목은 버건디 텍스트 + 좌측 4px 버건디 실선 ②상단 얇은 헤더(로고+화면명)
   ③본문 = 상단 KPI 행 + 고밀도 패널 ④**하단 시트탭**(엑셀 워크시트 탭 스타일 —
   워크플로우 단계 이동). 파일/협업 화면은 SharePoint 벤치마크(극미니멀, 세로선 無,
   헤더 생략, 아이콘+상대시간+담당자)를 따른다.
4. 다크모드 토큰(brand-900·neutral-900)은 정의만 유지 — 구현 후순위.

*작성일: 2026-07-17 · 검증: 벤치마크 3종(Easy View·Consolidation BI·SharePoint 포털) 대조*
*목적: Val-Studio 프론트엔드 컴포넌트 개발 시 최우선 적용 CSS/디자인 가이드라인*
