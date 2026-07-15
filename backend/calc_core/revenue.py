"""매출추정 — top_down(산업 CAGR) | bottom_up(계층 트리 P×Q).

두 전략 모두 연도별 매출 벡터(list[float])를 반환하며 하류 EBIT→FCFF 는 불변.

- top_down (구현 쉬움·기본): 산업 TAM × 점유율, CAGR 로 성장. 입력 3파라미터.
- bottom_up: 디렉토리형 상-하위 트리(지역>제품군>제품>상품 등, 축 순서 자유).
  각 리프는 판매량(Q)×판매단가(P) 또는 성장률. 상위 노드 = 하위 합계(합계검증).
  LLM 이 사업보고서에서 트리를 제안하고 유저가 +/− 편집·승인(상위 레이어 UI).
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ── top-down ─────────────────────────────────────────────────────────────
def top_down(
    market_size: float, share: float, cagr: float, years: int,
    share_path: list[float] | None = None,
) -> list[float]:
    """산업 CAGR 방식: 매출[t] = TAM·(1+cagr)^(t+1) · 점유율.

    share_path 를 주면 연도별 점유율 변화 반영(길이 years), 없으면 share 고정.
    """
    out = []
    for t in range(years):
        tam_t = market_size * (1.0 + cagr) ** (t + 1)
        s = share_path[t] if share_path else share
        out.append(tam_t * s)
    return out


# ── bottom-up 트리 ────────────────────────────────────────────────────────
@dataclass
class RevenueNode:
    """매출 트리 노드. 리프는 (price×qty) 또는 base×(1+growth); 내부노드는 자식 합계.

    provenance: 근거 출처(사업보고서 문단 등) — 감사추적용.
    """

    name: str
    children: list["RevenueNode"] = field(default_factory=list)
    # 리프 전용: 판매단가·판매량 경로(길이=years) 또는 base+growth 경로
    price: list[float] | None = None
    qty: list[float] | None = None
    base: float | None = None
    growth: list[float] | None = None
    provenance: str | None = None

    def is_leaf(self) -> bool:
        return not self.children

    def revenue(self, years: int) -> list[float]:
        """이 노드의 연도별 매출."""
        if not self.is_leaf():
            child_vecs = [c.revenue(years) for c in self.children]
            return [sum(v[t] for v in child_vecs) for t in range(years)]
        if self.price is not None and self.qty is not None:
            return [self.price[t] * self.qty[t] for t in range(years)]
        if self.base is not None and self.growth is not None:
            out, prev = [], self.base
            for t in range(years):
                prev = prev * (1.0 + self.growth[t])
                out.append(prev)
            return out
        raise ValueError(f"리프 '{self.name}' 에 price×qty 또는 base+growth 필요")


def bottom_up(root: RevenueNode, years: int) -> list[float]:
    """트리 루트의 총매출 벡터."""
    return root.revenue(years)


def validate_tree_sums(root: RevenueNode, years: int, rel_tol: float = 1e-9) -> list[str]:
    """합계검증: 각 내부노드 매출 == 자식 합계 (부동소수 허용오차 내). 위반 리스트 반환."""
    import math

    errors: list[str] = []

    def walk(node: RevenueNode):
        if node.is_leaf():
            return
        node_rev = node.revenue(years)
        child_sum = [sum(c.revenue(years)[t] for c in node.children) for t in range(years)]
        for t in range(years):
            if not math.isclose(node_rev[t], child_sum[t], rel_tol=rel_tol, abs_tol=1e-9):
                errors.append(f"{node.name} 연도{t}: {node_rev[t]} != Σ자식 {child_sum[t]}")
        for c in node.children:
            walk(c)

    walk(root)
    return errors
