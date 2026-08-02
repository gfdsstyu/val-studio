/* 골든 케이스(픽스처) ↔ DCF 시트 폼 형태 변환.
 *
 * 서버의 /api/demo/cases 는 픽스처 **원본** 을 가공 없이 준다(그래야 '재현'이라는
 * 주장이 성립한다). 반면 DCF 시트의 폼은 모든 값을 문자열로 들고 있고 시리즈는
 * 콤마 문자열이다. 그 간극을 여기서만 메운다.
 */

/** DCF 폼 기본값 — 시트와 Home 이 공유하는 단일 출처.
 *
 *  ⚠️ 부분 폼을 만들지 말 것. runDcf 가 form.claimed_per_share.trim() 처럼
 *  옵셔널 체이닝 없이 접근하는 필드가 있어, 키가 빠진 객체를 넣으면 클릭 순간
 *  TypeError 로 화면이 죽는다. 그래서 toDcfForm 은 항상 이 기본값 위에 덮는다. */
export const DCF_FORM_DEFAULTS = {
  wacc: "0.10", terminal_growth: "0.01",
  revenue: "100000, 115000, 132000, 149000, 165000",
  cogs: "40000, 46000, 52800, 59600, 66000",
  sga: "20000, 23000, 26400, 29800, 33000",
  dep_amort: "5000, 5000, 5000, 5000, 5000",
  capex: "5000, 5000, 5000, 5000, 5000",
  delta_nwc_cash_adj: "0, 0, 0, 0, 0",
  non_operating_assets: "20000", net_debt: "10000", non_controlling_interest: "0",
  shares_outstanding: "10000000", claimed_per_share: "", terminal_wc_ratio: "",
  mid_year_periods: "", tax_override: "", terminal_fcff_override: "",
  fade_years: "", fade_growth: "", terminal_from_last_fcff: false,
  pgr_source: "", pgr_basis: "",
  terminal_discount_period: "",
};

/** 배열로 들어오는 입력(연도별 시계열·할인기간·세금). */
const SERIES = [
  "revenue", "cogs", "sga", "dep_amort", "capex", "delta_nwc_cash_adj",
  "mid_year_periods", "tax_override",
];

/** 스칼라 입력. */
const SCALAR = [
  "wacc", "terminal_growth", "non_operating_assets", "net_debt",
  "non_controlling_interest", "shares_outstanding", "terminal_discount_period",
  "terminal_fcff_override", "terminal_wc_ratio", "fade_years", "fade_growth",
];

/**
 * 골든 케이스 inputs → DCF 폼 객체(문자열). 기본값 위에 덮어 항상 완전한 폼을 만든다.
 * 폼이 표현할 수 없는 키(explicit_years 등 라벨성 필드)는 버린다.
 */
export function toDcfForm(inputs) {
  const f = { ...DCF_FORM_DEFAULTS };
  for (const k of SERIES) {
    if (Array.isArray(inputs[k])) f[k] = inputs[k].join(", ");
  }
  for (const k of SCALAR) {
    if (inputs[k] != null) f[k] = String(inputs[k]);
  }
  return f;
}
