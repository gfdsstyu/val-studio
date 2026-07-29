"""tests/skill 을 패키지로 만든다 — 모듈명 충돌 방지용.

pytest 기본 import 모드(prepend)는 테스트 파일의 **basename** 을 모듈명으로 쓴다.
`tests/skill/test_footnote_costs.py` 와 `tests/test_footnote_costs.py` 는 이름이
같아 같은 모듈명(`test_footnote_costs`)으로 충돌했고, 전체 수집이 중단됐다
("imported module has this __file__ attribute which is not the same as the test
file we want to collect").

이 파일이 있으면 pytest 가 basedir 를 `tests/` 로 잡아 모듈명이
`skill.test_footnote_costs` 가 되므로 충돌이 사라진다. 파일명을 바꾸는 것보다
덜 침습적이고, 두 테스트가 같은 대상(backend vs vendor 사본)을 각자의 관점에서
검증한다는 의도도 그대로 유지된다.
"""
