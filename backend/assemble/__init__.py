"""assemble — 커넥터/복붙 원천값을 calc_core 엔진 입력으로 조립하는 오케스트레이션 계층.

calc_core(순수 엔진, stdlib)와 ingest(데이터 커넥터, 네트워크) 사이의 다리. 커넥터가
방출한 ProvenancedValue/ValidationReport 를 모아 엔진 입력(WaccInputs 등)을 만들고,
모든 게이트 리포트를 하나로 접어 FAIL 시 조립을 차단한다.
"""
