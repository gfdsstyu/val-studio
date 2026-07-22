"""profiles — 자료유형별 시맨틱 프로파일(파서 매트릭스의 '유형' 층).

추출 백엔드(pdf/xbrl/xlsx)가 준 표·텍스트에 *의미*를 입힌다: "이 유형에서 이게 WACC,
이게 영구성장률". 고정양식([[외부평가의견서_고정양식_구조]])의 앵커를 이용해, 한글 라벨이
깨진 상황에서도 필드를 특정한다.
"""
from .business_report import BusinessFinancials, extract_business_report
from .opinion_template import OpinionExtract, extract_opinion

__all__ = [
    "OpinionExtract", "extract_opinion",
    "BusinessFinancials", "extract_business_report",
]
