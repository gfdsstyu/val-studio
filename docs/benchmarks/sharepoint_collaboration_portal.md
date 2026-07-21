# SharePoint 기반 연결결산/감사 협업 포털 UI 벤치마크

## 개요
이 문서는 업로드된 **'ABC홀딩스 연결플랫폼 (SharePoint 기반)'** 화면을 바탕으로 `valuation-platform (val-studio)`의 **클라이언트 협업 및 파일 관리(Document Management)** 화면 설계를 위한 가이드라인을 정의합니다. 회계법인회계법인 등 대형 회계법인가 실제 클라이언트와 엑셀 패키지를 주고받을 때 사용하는 전형적인 포털 화면입니다.

## 핵심 UI 원칙 (Minimalist Document Portal)

### 1. 극단적인 미니멀리즘 (Extreme Minimalism)
앞서 벤치마크한 '대시보드(Easy View)'가 정보의 밀도와 시각화에 집중했다면, '파일 공유 포털'은 **가독성과 여백**에 집중합니다.
*   **배경색:** 완전한 순백색 (`bg-white`).
*   **테두리 제거:** 표(Table) 형태임에도 불구하고 세로 구분선(Vertical Borders)이 전혀 없고, 가로 구분선(Horizontal Borders)만 매우 연하게(`border-gray-100`) 존재합니다.
*   **헤더 생략:** 테이블의 컬럼명(파일명, 수정일, 작성자)을 명시하는 헤더 텍스트조차 생략하여 시각적 노이즈를 극도로 줄였습니다.

### 2. 타이포그래피 및 레이아웃 (Typography & Layout)
*   **타이틀:** 중앙 정렬된 거대한 검은색 볼드 텍스트(`text-3xl font-bold text-center`).
*   **글로벌 네비게이션(GNB):** 제목 아래에 얇은 선으로 상하가 구분된 텍스트 메뉴. 
    *   항목: 홈, 부문마스터, 협업공간, 관련자료 등.
    *   글씨색은 연한 회색(`text-gray-500`), 호버 시 진한 회색이나 밑줄로 변화.
*   **리스트 정렬:** 
    1.  **아이콘:** 좌측에 엑셀(.xlsm) 전용 아이콘 배치.
    2.  **파일명:** 파일명은 가장 길기 때문에 좌측 정렬.
    3.  **시간:** 상대적 시간 표기 ("1분 전", "어제 5:16 PM").
    4.  **작성자/역할:** 담당자명 명시 ("ABC홀딩스 관리회계팀장", "회계법인회계법인 S 회계사").

### 3. 색상 (Color Palette)
*   **메인 텍스트:** 검은색 가까운 짙은 회색 (`text-gray-900`).
*   **보조 텍스트:** 연한 회색 (`text-gray-500`) - 날짜 등에 사용.
*   **포인트 컬러:** 오직 **'엑셀 아이콘의 초록색'**만이 화면 내의 유일한 유채색입니다. 철저한 무채색 통제입니다.
*   **상단 바 (SharePoint Global Header):** 검은색 배경에 흰색 텍스트 (`bg-black text-white`).

---

## 🛠️ Tailwind CSS 구현 지침 (클라이언트 협업 공간 예시)
이 벤치마크를 적용하여 파일 목록 화면을 구성할 때의 Tailwind 코드입니다.

```html
<!-- 상단 타이틀 및 네비게이션 -->
<div class="bg-white pt-10 pb-4">
  <h1 class="text-3xl font-bold text-center text-gray-900 mb-8">ABC홀딩스 연결플랫폼</h1>
  
  <div class="border-t border-b border-gray-200 px-8 py-3 flex justify-between items-center text-sm text-gray-500">
    <div class="flex space-x-6">
      <a href="#" class="text-gray-900 font-semibold">홈</a>
      <a href="#" class="hover:text-gray-900">부문마스터</a>
      <a href="#" class="hover:text-gray-900">협업공간</a>
      <a href="#" class="hover:text-gray-900">관련자료</a>
    </div>
    <button class="flex items-center text-gray-700 hover:text-black">
      <svg class="w-4 h-4 mr-1" ...><!-- Share Icon --></svg>
      공유
    </button>
  </div>
</div>

<!-- 극미니멀 파일 리스트 테이블 -->
<div class="max-w-6xl mx-auto mt-8 px-8">
  <div class="flex flex-col">
    <!-- Row 1 -->
    <div class="flex items-center py-4 border-b border-gray-100 hover:bg-gray-50">
      <div class="w-10 flex-shrink-0">
        <!-- 엑셀 아이콘 -->
        <img src="/icons/excel.svg" alt="Excel" class="w-6 h-6" />
      </div>
      <div class="flex-1 text-gray-900">ABC그룹패키지_202306_B부문.xlsm</div>
      <div class="w-48 text-gray-500 text-sm">어제 5:16 PM</div>
      <div class="w-64 text-gray-900 text-sm">ABC홀딩스 관리회계팀장</div>
    </div>
    
    <!-- Row 2 -->
    <div class="flex items-center py-4 border-b border-gray-100 hover:bg-gray-50">
      <div class="w-10 flex-shrink-0">
        <img src="/icons/excel.svg" alt="Excel" class="w-6 h-6" />
      </div>
      <div class="flex-1 text-gray-900">ABC그룹패키지_202306_F부문.xlsm</div>
      <div class="w-48 text-gray-500 text-sm">1시간 전</div>
      <div class="w-64 text-gray-900 text-sm">회계법인회계법인 S 회계사</div>
    </div>
  </div>
</div>
```
