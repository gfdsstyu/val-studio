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

export function conversionBox(address) {
  const match = typeof address === "string" && address.match(/^\$?([A-Za-z]{1,3})\$?([1-9]\d{0,6})(?::\$?([A-Za-z]{1,3})\$?([1-9]\d{0,6}))?$/);
  if (!match) throw new Error("A1 또는 A1:B10 형태의 연속 범위를 지정하세요.");
  const col = text => [...text.toUpperCase()].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0) - 1;
  const row = Number(match[2]) - 1, column = col(match[1]);
  const lastRow = Number(match[4] || match[2]) - 1, lastColumn = col(match[3] || match[1]);
  const height = lastRow - row + 1, width = lastColumn - column + 1;
  if (lastRow >= 1048576 || lastColumn >= 16384 || height < 1 || width < 1 || width > 100 || height * width > 2000) {
    throw new Error("환산 범위는 최대 2,000셀·100열이며 Excel 주소 안에 있어야 합니다.");
  }
  return { row, column, height, width };
}

async function unmerged(ctx, range) {
  if (typeof range.getMergedAreasOrNullObject !== "function") {
    throw new Error("환산에는 병합 셀 검사를 지원하는 Excel(ExcelApi 1.13 이상)이 필요합니다.");
  }
  const merged = range.getMergedAreasOrNullObject();
  merged.load("isNullObject"); await ctx.sync();
  if (!merged.isNullObject) throw new Error("병합 셀이 있는 범위는 환산할 수 없습니다.");
}

async function readRange(ctx, range) {
  range.load("values,formulas"); await ctx.sync();
  return { values: range.values.map(row => [...row]), formulas: range.formulas.map(row => [...row]) };
}

export async function selectedConversionRange() {
  return run(async ctx => {
    const range = ctx.workbook.getSelectedRange();
    range.load("address"); range.worksheet.load("name"); await ctx.sync();
    const address = range.address.slice(range.address.lastIndexOf("!") + 1);
    conversionBox(address); await unmerged(ctx, range);
    return { sheet: range.worksheet.name, address };
  });
}

export async function readConversionRanges(sourceSheet, sourceAddress, outputSheet, outputStart) {
  return run(async ctx => {
    const source = conversionBox(sourceAddress), output = conversionBox(outputStart);
    if (output.height !== 1 || output.width !== 1 || output.row + source.height > 1048576 || output.column + source.width > 16384) {
      throw new Error("출력 시작은 Excel 주소 안의 단일 셀이어야 합니다.");
    }
    const from = ctx.workbook.worksheets.getItem(sourceSheet).getRangeByIndexes(source.row, source.column, source.height, source.width);
    const to = ctx.workbook.worksheets.getItem(outputSheet).getRangeByIndexes(output.row, output.column, source.height, source.width);
    await unmerged(ctx, from); await unmerged(ctx, to);
    return { expected_source: await readRange(ctx, from), expected_output: await readRange(ctx, to) };
  });
}

export async function applyMarketConversion(plan, onStage = () => {}) {
  return run(async ctx => {
    const getRange = spec => ctx.workbook.worksheets.getItem(spec.sheet)
      .getRangeByIndexes(spec.row, spec.column, spec.height, spec.width);
    const source = getRange(plan.source), output = getRange(plan.output);
    const check = async (range, expected) => {
      await unmerged(ctx, range);
      const actual = await readRange(ctx, range);
      if (!sameGrid(actual.values, expected.values) || !sameGrid(actual.formulas, expected.formulas)) throw conflict();
    };
    await expectGrid(ctx, "rMarket", plan.expected_market_grid, true);
    await expectGrid(ctx, "MarketInputs", plan.inputs.expected_grid);
    await expectGrid(ctx, "_VS_FACTS", plan.facts.expected_grid, true);
    await check(source, plan.source.expected); await check(output, plan.output.expected);
    const inputs = await applyAppend(ctx, plan.inputs, plan.inputs.formula_column); onStage("inputs_written");
    await expectGrid(ctx, "rMarket", plan.expected_market_grid, true);
    await check(source, plan.source.expected); await check(output, plan.output.expected);
    output.numberFormat = plan.output.formulas.map(row => row.map(() => "General"));
    output.formulas = plan.output.formulas; await ctx.sync(); onStage("conversion_written");
    ctx.workbook.application.calculate("Full"); await ctx.sync();
    await check(source, plan.source.expected);
    await expectGrid(ctx, "rMarket", plan.expected_market_grid, true);
    const actual = await readRange(ctx, output);
    const adopted = inputs.getRangeByIndexes(plan.inputs.start_row - 1, plan.inputs.formula_column, 1, 1);
    const rate = await readRange(ctx, adopted);
    const close = (value, expected) => typeof value === "number" && Number.isFinite(value) &&
      Math.abs(value - Number(expected)) <= Math.abs(Number(expected)) * 1e-12;
    if (!sameGrid(actual.formulas, plan.output.formulas) || actual.values.some((row, r) => row.some((v, c) =>
      plan.output.expected_values[r][c] === "" ? v !== "" : !close(v, plan.output.expected_values[r][c]))) ||
      rate.formulas[0][0] !== plan.inputs.rows[0][plan.inputs.formula_column] || !close(rate.values[0][0], plan.expected_rate)) {
      throw new Error("환산 수식·계산값 대사가 실패했습니다. 출력 범위를 확인하세요.");
    }
    onStage("conversion_verified");
    await applyAppend(ctx, plan.facts); onStage("conversion_recorded");
    return { conversion_id: plan.conversion_id, snapshot_id: plan.snapshot_id, observation_id: plan.observation_id,
      source: { sheet: plan.source.sheet, address: plan.source.address },
      output: { sheet: plan.output.sheet, address: plan.output.address }, currency: plan.currency,
      source_scale: plan.source_scale, output_unit: plan.output_unit, state: "conversion_recorded" };
  });
}
