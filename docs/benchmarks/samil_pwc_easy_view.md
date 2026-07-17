# 삼일PwC (PwC Easy View) UI/UX 벤치마크

## 개요
이 문서는 업로드된 **'PwC Easy View for Tax preview'** 화면을 바탕으로 `valuation-platform (val-studio)`의 정통 엔터프라이즈(빅4) UI/UX 구현을 위한 가이드라인을 정의합니다.

## 핵심 UI 원칙 (Enterprise Big 4 Aesthetic)

### 1. 색상 (Color Palette)
무채색(화이트/그레이) 캔버스에 **브랜드 컬러(오렌지)를 포인트로만 강렬하게 사용**합니다.
*   **Background (배경):** 옅은 회색 (`bg-gray-100`)을 사용하여 흰색 패널(Card)들이 돋보이도록 함.
*   **Surface (패널):** 순백색 (`bg-white`).
*   **Brand/Point Color:** PwC 고유의 오렌지색.
    *   상단 주요 KPI 위젯의 배경색 (백색 텍스트와 대비).
    *   사이드바/하단 탭의 '활성화(Active)' 상태 표시선 및 텍스트.
    *   테이블 헤더 텍스트 및 게이지 차트의 채움 색상.

### 2. 형태 및 모서리 (Shapes & Border Radius)
최근 AI 툴의 둥근 디자인을 철저히 배제하고 **직각(Square)**을 고수합니다.
*   **Card/Panel:** 모서리 둥글기 없음 (`rounded-none`).
*   **Input/Select:** 좌측 하단의 '법인코드', '연도' 선택 드롭다운 역시 둥글기 없는 직사각형 폼(`rounded-none`, `border-gray-300`).

### 3. 레이아웃 및 네비게이션 (Layout & Navigation)
엑셀(Excel)과 유사한 높은 정보 밀도와 다중 탭 구조를 가집니다.
*   **좌측 사이드바 (LNB):** 수직 형태의 텍스트 탭. 선택된 항목은 주황색 텍스트와 좌측 주황색 실선(`border-l-4 border-orange-500`)으로 강조.
*   **하단 시트 탭:** 엑셀의 워크시트 탭처럼 화면 하단에 가로로 탭이 나열됨.
*   **그리드 시스템:** 화면을 3단(3 Columns)으로 명확히 나누고, 상단에는 요약 KPI, 하단에는 상세 테이블 및 차트를 배치.

### 4. 데이터 테이블 (Data Tables)
*   **밀도 (Density):** 매우 좁은 패딩(`px-2 py-1` 수준)으로 한 화면에 많은 수치를 빽빽하게 보여줌.
*   **구분선:** 각 행(Row)마다 얇은 실선 테두리가 존재하며, 중요 항목(과세표준, 납부세액 등)은 연한 배경색(`bg-orange-50` 등)으로 하이라이트.
*   **상호작용:** 확장이 가능한 행에는 우측에 명확한 `+` 아이콘을 배치하여 뎁스(Depth)를 표현.

### 5. 데이터 시각화 (Data Visualization)
*   **게이지 차트 (Half-Donut):** 세전손익 대비 과세표준, 유효세율 등을 직관적인 반원 게이지 차트로 표현. 두꺼운 선과 명확한 큰 텍스트 사용.

---

## 🛠️ Tailwind CSS 구현 지침 (적용 예시)
이 벤치마크를 `valuation-platform`에 적용할 때 사용하는 기본 Tailwind 클래스 규칙입니다.

```html
<!-- 상단 KPI 카드 예시 -->
<div class="bg-[#d04a02] text-white p-4 rounded-none shadow-sm flex items-center">
  <div class="text-3xl font-bold">78.67백만</div>
  <div class="text-sm">법인세차감전순이익</div>
</div>

<!-- 데이터 테이블 패널 예시 -->
<div class="bg-white p-0 rounded-none shadow border border-gray-200">
  <div class="border-b border-gray-300 p-3 text-lg font-semibold text-gray-800">
    회계상 세전손익
  </div>
  <table class="w-full text-sm">
    <thead class="bg-gray-50 text-[#d04a02]">
      <tr>
        <th class="text-left font-normal p-2">계정과목</th>
        <th class="text-right font-normal p-2">금액</th>
      </tr>
    </thead>
    <tbody class="divide-y divide-gray-200 text-gray-700">
      <tr>
        <td class="p-2">매출액</td>
        <td class="p-2 text-right">925,508,415</td>
      </tr>
      <!-- ... -->
    </tbody>
  </table>
</div>
```
