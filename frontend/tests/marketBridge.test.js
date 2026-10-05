import test from "node:test";
import assert from "node:assert/strict";
import { appendMarketWorkbook, applyMarketBinding, readMarketWorkbook, sameGrid } from "../src/marketBridge.js";

// In-memory Office adapter. Exercises sequencing/conflicts/readback; NOT an Excel host certification.
function office(initial = {}, { onSync = () => {}, failSheet = "" } = {}) {
  const sheets = new Map();
  const decode = a => {
    const [, col, row] = a.replaceAll("$", "").match(/^([A-Z]+)(\d+)$/);
    let n = 0; for (const c of col) n = n * 26 + c.charCodeAt(0) - 64;
    return [Number(row) - 1, n - 1];
  };
  const evaluate = v => {
    if (typeof v !== "string" || !v.startsWith("=")) return v;
    const match = v.match(/^='([^']+)'!(.+)$/);
    if (!match) return "#VALUE!";
    const [r, c] = decode(match[2]); return evaluate(sheets.get(match[1])?.rows[r]?.[c] ?? "");
  };
  class Range {
    constructor(sheet, r, c, height, width, isNullObject = false) {
      Object.assign(this, { sheet, rowIndex: r, columnIndex: c, rowCount: height, columnCount: width, isNullObject });
    }
    load() {}
    get formulas() { return Array.from({ length: this.rowCount }, (_, r) => Array.from({ length: this.columnCount }, (_, c) =>
      this.sheet.rows[r + this.rowIndex]?.[c + this.columnIndex] ?? "")); }
    get values() { return this.formulas.map((row, r) => row.map((v, c) => this.sheet.literals.has(`${r + this.rowIndex}:${c + this.columnIndex}`) ? v : evaluate(v))); }
    set values(rows) { this.write(rows, true); }
    set formulas(rows) { this.write(rows, false); }
    write(rows, literal) {
      if (this.sheet.name === failSheet) throw new Error("MOCK protected worksheet");
      rows.forEach((row, i) => row.forEach((v, j) => {
        while (this.sheet.rows.length <= i + this.rowIndex) this.sheet.rows.push([]);
        const key = `${i + this.rowIndex}:${j + this.columnIndex}`;
        if (literal) this.sheet.literals.add(key); else this.sheet.literals.delete(key);
        this.sheet.rows[i + this.rowIndex][j + this.columnIndex] = literal && typeof v === "string" && v.startsWith("'") ? v.slice(1) : v;
      }));
    }
  }
  class Sheet {
    constructor(name, rows = []) { this.name = name; this.rows = structuredClone(rows); this.literals = new Set(); this.isNullObject = false; }
    load() {}
    getRangeByIndexes(r, c, h, w) { return new Range(this, r, c, h, w); }
    getRange(a) { const [r, c] = decode(a); return new Range(this, r, c, 1, 1); }
    getUsedRangeOrNullObject() { return new Range(this, 0, 0, this.rows.length, Math.max(1, ...this.rows.map(r => r.length)), !this.rows.length); }
  }
  for (const [name, rows] of Object.entries(initial)) sheets.set(name, new Sheet(name, rows));
  const ctx = { workbook: { worksheets: {
    getItemOrNullObject: name => sheets.get(name) || { isNullObject: true, load() {} },
    getItem: name => { if (!sheets.has(name)) throw new Error("sheet missing"); return sheets.get(name); },
    add: name => { const sheet = new Sheet(name); sheets.set(name, sheet); return sheet; },
  }, application: { calculate() {} } }, sync: async () => onSync(sheets) };
  globalThis.Excel = { run: fn => fn(ctx) };
  return sheets;
}

const plan = (sheet, expected = [], rows = [["new", 1400]]) => ({ sheet, create: !expected.length,
  expected_grid: expected, header_rows: expected.length ? [] : [["schema", 1]], start_row: expected.length + 2, rows });

test("append preserves existing rows, records facts and verifies readback", async () => {
  const before = [["schema", 1], ["existing", 1350]];
  const sheets = office({ rMarket: before });
  const stages = [];
  await appendMarketWorkbook({ market: plan("rMarket", before), facts: plan("_VS_FACTS") }, s => stages.push(s));
  assert.deepEqual(sheets.get("rMarket").rows.slice(0, 2), before);
  assert.deepEqual(stages, ["raw_written", "facts_written"]);
  assert.equal((await readMarketWorkbook()).market_grid[3][1], 1400);
});

test("precondition mismatch writes nothing", async () => {
  const sheets = office({ rMarket: [["someone else's work"]] });
  await assert.rejects(() => appendMarketWorkbook({ market: plan("rMarket"), facts: plan("_VS_FACTS") }), /변경/);
  assert.deepEqual(sheets.get("rMarket").rows, [["someone else's work"]]);
  assert.equal(sheets.has("_VS_FACTS"), false);
});

test("facts failure leaves raw checkpoint and no false completion", async () => {
  office({}, { failSheet: "_VS_FACTS" });
  const stages = [];
  await assert.rejects(() => appendMarketWorkbook({ market: plan("rMarket"), facts: plan("_VS_FACTS") }, s => stages.push(s)), /protected/);
  assert.deepEqual(stages, ["raw_written"]);
});

function adoption() {
  return { binding_id: "b", snapshot_id: "s", observation_id: "o", expected_market_grid: [[1400]],
    inputs: { ...plan("MarketInputs", [], [["b", "fx", "USD", "='rMarket'!$A$1"]]), formula_column: 3 },
    target: { sheet: "Model", address: "A1", expected: { value: 1350, formula: 1350 }, formula: "='MarketInputs'!$D$2" },
    expected_value: "1400", facts: plan("_VS_FACTS") };
}

test("binding validates both formulas and recalculated values before approval record", async () => {
  const sheets = office({ rMarket: [[1400]], Model: [[1350]] });
  const stages = [];
  const result = await applyMarketBinding(adoption(), s => stages.push(s));
  assert.equal(result.state, "adoption_recorded");
  assert.deepEqual(stages, ["inputs_written", "target_written", "bindings_verified", "adoption_recorded"]);
  assert.equal(sheets.get("Model").rows[0][0], "='MarketInputs'!$D$2");
});

test("a target changed after preview is never overwritten", async () => {
  const sheets = office({ rMarket: [[1400]], Model: [[1600]] });
  await assert.rejects(() => applyMarketBinding(adoption()), /변경/);
  assert.equal(sheets.get("Model").rows[0][0], 1600);
  assert.equal(sheets.has("MarketInputs"), false);
});

test("wrong recalculated value cannot produce adopted facts", async () => {
  const sheets = office({ rMarket: [[1400]], Model: [[1350]] });
  const stages = [];
  const p = adoption(); p.expected_value = "1500";
  await assert.rejects(() => applyMarketBinding(p, s => stages.push(s)), /대사/);
  assert.deepEqual(stages, ["inputs_written", "target_written"]);
  assert.equal(sheets.has("_VS_FACTS"), false);
});

test("blank padding and number serialization do not create false conflicts", () => {
  assert(sameGrid([["schema", 1, ""], ["", ""]], [["schema", 1.0]]));
  assert(!sameGrid([["schema", 0]], [["schema", ""]]));
});

test("upstream formula-looking text remains a literal through append/readback", async () => {
  office();
  await appendMarketWorkbook({ market: plan("rMarket", [], [["=HYPERLINK(unsafe)", "-0.25", "@USD"]]), facts: plan("_VS_FACTS") });
  const grid = (await readMarketWorkbook()).market_grid;
  assert.deepEqual(grid[1], ["=HYPERLINK(unsafe)", "-0.25", "@USD"]);
});
