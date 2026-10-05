/** Market-specific append and binding writes. Never calls delete/replace-sheet helpers.
 * A single writer is required; precondition checks cannot make coauthoring atomic.
 */
export const marketExcelAvailable = () => typeof globalThis.Excel?.run === "function";

export function normalizedGrid(rows = []) {
  const result = rows.map(row => {
    const cells = row.map(v => v == null ? "" : String(v));
    while (cells.at(-1) === "") cells.pop();
    return cells;
  });
  while (result.length && result.at(-1).length === 0) result.pop();
  return result;
}
export const sameGrid = (a, b) => JSON.stringify(normalizedGrid(a)) === JSON.stringify(normalizedGrid(b));
const conflict = () => new Error("시트가 조회 후 변경되었습니다. 다시 읽고 재시도하세요.");
const pad = rows => {
  const width = Math.max(1, ...rows.map(r => r.length));
  return rows.map(r => Array.from({ length: width }, (_, i) => r[i] ?? ""));
};

async function sheetGrid(ctx, name) {
  const sheet = ctx.workbook.worksheets.getItemOrNullObject(name);
  sheet.load("isNullObject"); await ctx.sync();
  if (sheet.isNullObject) return { sheet, rows: [], formulas: [] };
  const used = sheet.getUsedRangeOrNullObject(true);
  used.load("isNullObject,values,formulas,rowIndex,columnIndex"); await ctx.sync();
  if (used.isNullObject) return { sheet, rows: [], formulas: [] };
  // Preserve A1 coordinates even if a user moved/deleted the ownership header.
  const expand = values => [...Array.from({ length: used.rowIndex }, () => []),
    ...values.map(row => [...Array(used.columnIndex).fill(""), ...row])];
  return { sheet, rows: expand(used.values), formulas: expand(used.formulas) };
}

async function expectGrid(ctx, name, expected, noFormulas = false) {
  const current = await sheetGrid(ctx, name);
  if (!sameGrid(current.rows, expected)) throw conflict();
  if (noFormulas && current.formulas.some((row, r) => row.some((value, c) =>
    typeof value === "string" && value.startsWith("=") && value !== current.rows[r]?.[c]))) {
    throw new Error("원자료·사실 원장에 수식이 있습니다. 원본 값을 확인하세요.");
  }
  return current;
}

async function writeRows(ctx, sheet, start, rows, formulaColumn = null) {
  if (!rows.length) return;
  const values = pad(rows);
  const range = sheet.getRangeByIndexes(start - 1, 0, values.length, values[0].length);
  // Literal text, including upstream labels beginning with =, +, - or @.
  range.numberFormat = values.map(row => row.map(v => typeof v === "number" ? "General" : "@"));
  range.values = values.map(row => row.map(v => typeof v === "string" && v ? "'" + v : v));
  if (formulaColumn !== null) {
    const formulaRange = sheet.getRangeByIndexes(start - 1, formulaColumn, values.length, 1);
    formulaRange.numberFormat = values.map(() => ["General"]);
    formulaRange.formulas = values.map(row => [row[formulaColumn]]);
  }
  await ctx.sync();
  range.load("values,formulas"); await ctx.sync();
  const actual = range.values.map(row => [...row]);
  if (formulaColumn !== null) actual.forEach((row, i) => { row[formulaColumn] = range.formulas[i][formulaColumn]; });
  if (!sameGrid(actual, values)) throw new Error("기록 후 재읽기 값이 다릅니다. 기록 상태를 확인하세요.");
}

async function applyAppend(ctx, plan, formulaColumn = null) {
  const current = await expectGrid(ctx, plan.sheet, plan.expected_grid, formulaColumn === null);
  const sheet = current.sheet.isNullObject ? ctx.workbook.worksheets.add(plan.sheet) : current.sheet;
  if (plan.header_rows.length) await writeRows(ctx, sheet, 1, plan.header_rows);
  await writeRows(ctx, sheet, plan.start_row, plan.rows, formulaColumn);
  return sheet;
}

function run(fn) {
  if (!marketExcelAvailable()) throw new Error("Excel 추가 기능에서 워크북을 열어주세요.");
  return globalThis.Excel.run(fn);
}

export async function readMarketWorkbook() {
  return run(async ctx => {
    const market = await sheetGrid(ctx, "rMarket");
    const facts = await sheetGrid(ctx, "_VS_FACTS");
    const inputs = await sheetGrid(ctx, "MarketInputs");
    return { market_grid: market.rows, facts_grid: facts.rows, inputs_grid: inputs.rows };
  });
}

export async function readMarketTarget(sheetName, address) {
  return run(async ctx => {
    const range = ctx.workbook.worksheets.getItem(sheetName).getRange(address);
    range.load("values,formulas,rowCount,columnCount"); await ctx.sync();
    if (range.rowCount !== 1 || range.columnCount !== 1) throw new Error("대상은 단일 셀이어야 합니다.");
    return { value: range.values[0][0], formula: range.formulas[0][0] };
  });
}

export async function appendMarketWorkbook(plan, onStage = () => {}) {
  return run(async ctx => {
    // Fail known conflicts before any writes, then check again at each write boundary.
    await expectGrid(ctx, "rMarket", plan.market.expected_grid, true);
    await expectGrid(ctx, "_VS_FACTS", plan.facts.expected_grid, true);
    await applyAppend(ctx, plan.market); onStage("raw_written");
    await applyAppend(ctx, plan.facts); onStage("facts_written");
    return "facts_written";
  });
}

export async function applyMarketBinding(plan, onStage = () => {}) {
  return run(async ctx => {
    await expectGrid(ctx, "rMarket", plan.expected_market_grid, true);
    await expectGrid(ctx, "MarketInputs", plan.inputs.expected_grid);
    await expectGrid(ctx, "_VS_FACTS", plan.facts.expected_grid, true);
    const range = ctx.workbook.worksheets.getItem(plan.target.sheet).getRange(plan.target.address);
    const checkTarget = async () => {
      range.load("values,formulas"); await ctx.sync();
      if (!sameGrid(range.values, [[plan.target.expected.value]]) ||
          !sameGrid(range.formulas, [[plan.target.expected.formula]])) throw conflict();
    };
    await checkTarget();
    const inputs = await applyAppend(ctx, plan.inputs, plan.inputs.formula_column);
    onStage("inputs_written");
    await checkTarget();
    range.formulas = [[plan.target.formula]]; await ctx.sync(); onStage("target_written");
    ctx.workbook.application.calculate("Full"); await ctx.sync();
    const adopted = inputs.getRangeByIndexes(plan.inputs.start_row - 1, plan.inputs.formula_column, 1, 1);
    range.load("values,formulas"); adopted.load("values,formulas"); await ctx.sync();
    await expectGrid(ctx, "rMarket", plan.expected_market_grid, true);
    const expected = Number(plan.expected_value);
    const close = value => typeof value === "number" && Number.isFinite(value) &&
      Math.abs(value - expected) <= Math.max(1e-10, Math.abs(expected) * 1e-12);
    if (range.formulas[0][0] !== plan.target.formula || !close(range.values[0][0]) ||
        adopted.formulas[0][0] !== plan.inputs.rows[0][plan.inputs.formula_column] || !close(adopted.values[0][0])) {
      throw new Error("모델 수식·계산값 대사가 실패했습니다. 재조회 전에 현재 셀을 확인하세요.");
    }
    onStage("bindings_verified");
    await applyAppend(ctx, plan.facts); onStage("adoption_recorded");
    return { binding_id: plan.binding_id, observation_id: plan.observation_id,
      snapshot_id: plan.snapshot_id, target: plan.target, state: "adoption_recorded" };
  });
}
