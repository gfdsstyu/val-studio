import test from "node:test";
import assert from "node:assert/strict";
import { appendMarketWorkbook, applyMarketBinding, applyMarketConversion, conversionBox,
  readConversionRanges, readMarketWorkbook, selectedConversionRange, sameGrid } from "../src/marketBridge.js";

// In-memory Office adapter. Exercises sequencing/conflicts/readback; NOT an Excel host certification.
function office(initial = {}, { onSync = () => {}, failSheet = "", mergedSheet = "", mergeSupported = true, selection = ["Source", "A1:B2"] } = {}) {
  const sheets = new Map();
  const decode = a => {
    const [, col, row] = a.replaceAll("$", "").match(/^([A-Z]+)(\d+)$/);
    let n = 0; for (const c of col) n = n * 26 + c.charCodeAt(0) - 64;
    return [Number(row) - 1, n - 1];
  };
  const evaluate = v => {
    if (typeof v !== "string" || !v.startsWith("=")) return v;
    const ref = "'((?:''|[^'])+)'!(\\$?[A-Z]+\\$?\\d+)";
    const match = v.match(new RegExp("^=" + ref + "$"));
    const readRef = (name, address) => {
      const [r, c] = decode(address);
      return evaluate(sheets.get(name.replaceAll("''", "'"))?.rows[r]?.[c] ?? "");
    };
    if (match) return readRef(match[1], match[2]);
    const formula = v.match(new RegExp('^=IF\\((' + ref + ')="","",(' + ref + ')\\*(\\d+)\\*(' + ref + ')/(\\d+)\\)$'));
    if (!formula) return "#VALUE!";
    const value = readRef(formula[2], formula[3]);
    return value === "" ? "" : value * Number(formula[7]) * readRef(formula[9], formula[10]) / Number(formula[11]);
  };
  class Range {
    constructor(sheet, r, c, height, width, isNullObject = false) {
      Object.assign(this, { sheet, rowIndex: r, columnIndex: c, rowCount: height, columnCount: width, isNullObject });
      if (!mergeSupported) this.getMergedAreasOrNullObject = undefined;
    }
    load() {}
    get address() { return `${this.sheet.name}!${this.sheet.addressOf(this.rowIndex, this.columnIndex)}:${this.sheet.addressOf(this.rowIndex + this.rowCount - 1, this.columnIndex + this.columnCount - 1)}`; }
    get worksheet() { return this.sheet; }
    getMergedAreasOrNullObject() { return { isNullObject: this.sheet.name !== mergedSheet, load() {} }; }
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
    addressOf(r, c) {
      let col = "", n = c + 1;
      while (n) { const rem = (n - 1) % 26; col = String.fromCharCode(65 + rem) + col; n = Math.floor((n - 1) / 26); }
      return col + (r + 1);
    }
    getRange(a) { const [first, last = first] = a.split(":"); const [r, c] = decode(first), [endR, endC] = decode(last);
      return new Range(this, r, c, endR - r + 1, endC - c + 1); }
    getUsedRangeOrNullObject() { return new Range(this, 0, 0, this.rows.length, Math.max(1, ...this.rows.map(r => r.length)), !this.rows.length); }
  }
  for (const [name, rows] of Object.entries(initial)) sheets.set(name, new Sheet(name, rows));
  const ctx = { workbook: { getSelectedRange: () => sheets.get(selection[0]).getRange(selection[1]), worksheets: {
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

function conversion() {
  const values = [[2, 0], [-1, ""]];
  const formulas = values.map((row, r) => row.map((_, c) => {
    const ref = `'Source'!$${c ? "B" : "A"}$${r + 1}`;
    return `=IF(${ref}="","",${ref}*1000*'MarketInputs'!$D$2/1000000)`;
  }));
  return { conversion_id: "c", snapshot_id: "s", observation_id: "o", expected_market_grid: [[1400]],
    inputs: { ...plan("MarketInputs", [], [["c", "fx_range_conversion", "USD", "='rMarket'!$A$1"]]), formula_column: 3 },
    source: { sheet: "Source", address: "A1:B2", row: 0, column: 0, height: 2, width: 2,
      expected: { values, formulas: structuredClone(values) } },
    output: { sheet: "Output", address: "D3:E4", row: 2, column: 3, height: 2, width: 2,
      expected: { values: [["", ""], ["", ""]], formulas: [["", ""], ["", ""]] },
      formulas, expected_values: [[2.8, 0], [-1.4, ""]] },
    expected_rate: "1400", currency: "USD", source_scale: "thousand", output_unit: "KRW_million",
    facts: plan("_VS_FACTS", [], [["c", "conversion audit"]]) };
}
const conversionBook = () => ({ rMarket: [[1400]], Source: [[2, 0], [-1, ""]], Output: [] });

test("conversion preserves source and verifies units, zeros, negatives and blank formulas before audit", async () => {
  const book = conversionBook(), sheets = office(book), stages = [];
  const result = await applyMarketConversion(conversion(), s => stages.push(s));
  assert.deepEqual(sheets.get("Source").rows, book.Source);
  assert.deepEqual(sheets.get("Output").getRange("D3:E4").values, [[2.8, 0], [-1.4, ""]]);
  assert.deepEqual(stages, ["inputs_written", "conversion_written", "conversion_verified", "conversion_recorded"]);
  assert.equal(result.state, "conversion_recorded");
  assert.deepEqual(result.output, { sheet: "Output", address: "D3:E4" });
});

test("selected source and explicit output range keep worksheet coordinates", async () => {
  office(conversionBook());
  assert.deepEqual(await selectedConversionRange(), { sheet: "Source", address: "A1:B2" });
  const ranges = await readConversionRanges("Source", "A1:B2", "Output", "D3");
  assert.deepEqual(ranges.expected_source.values, [[2, 0], [-1, ""]]);
  assert.deepEqual(ranges.expected_output.values, [["", ""], ["", ""]]);
});

test("source change after preview prevents both input and output writes", async () => {
  const book = conversionBook(); book.Source[0][0] = 3;
  const sheets = office(book);
  await assert.rejects(() => applyMarketConversion(conversion()), /변경/);
  assert.equal(sheets.has("MarketInputs"), false);
  assert.deepEqual(sheets.get("Output").rows, []);
});

test("occupied output after preview is preserved", async () => {
  const sheets = office(conversionBook()); sheets.get("Output").getRange("D3").values = [[99]];
  await assert.rejects(() => applyMarketConversion(conversion()), /변경/);
  assert.equal(sheets.get("Output").getRange("D3").values[0][0], 99);
  assert.equal(sheets.has("MarketInputs"), false);
});

test("wrong conversion result cannot create an adopted fact", async () => {
  const sheets = office(conversionBook()), p = conversion(), stages = [];
  p.output.expected_values[0][0] = 28;
  await assert.rejects(() => applyMarketConversion(p, s => stages.push(s)), /대사/);
  assert.deepEqual(stages, ["inputs_written", "conversion_written"]);
  assert.equal(sheets.has("_VS_FACTS"), false);
});

test("a tiny nonzero expected amount is never accepted as zero", async () => {
  const sheets = office(conversionBook()), p = conversion();
  p.output.expected_values[0][1] = 1e-11;
  await assert.rejects(() => applyMarketConversion(p), /대사/);
  assert.equal(sheets.has("_VS_FACTS"), false);
});

test("source mutation during writes cannot produce a completed audit", async () => {
  const sheets = office(conversionBook(), { onSync: s => {
    if (s.get("Output").rows[2]?.[3]?.startsWith?.("=IF")) s.get("Source").rows[0][0] = 3;
  } });
  await assert.rejects(() => applyMarketConversion(conversion()), /변경/);
  assert.equal(sheets.has("_VS_FACTS"), false);
});

test("protected output keeps source intact and reports input checkpoint", async () => {
  const sheets = office(conversionBook(), { failSheet: "Output" }), stages = [];
  await assert.rejects(() => applyMarketConversion(conversion(), s => stages.push(s)), /protected/);
  assert.deepEqual(stages, ["inputs_written"]);
  assert.deepEqual(sheets.get("Source").rows, conversionBook().Source);
  assert.equal(sheets.has("_VS_FACTS"), false);
});

test("audit failure reports verified formulas without claiming completion", async () => {
  office(conversionBook(), { failSheet: "_VS_FACTS" }); const stages = [];
  await assert.rejects(() => applyMarketConversion(conversion(), s => stages.push(s)), /protected/);
  assert.deepEqual(stages, ["inputs_written", "conversion_written", "conversion_verified"]);
});

test("merged cells and unsupported merge inspection stop before writes", async () => {
  for (const options of [{ mergedSheet: "Source" }, { mergedSheet: "Output" }, { mergeSupported: false }]) {
    const sheets = office(conversionBook(), options);
    await assert.rejects(() => applyMarketConversion(conversion()), /병합/);
    assert.equal(sheets.has("MarketInputs"), false);
    assert.deepEqual(sheets.get("Output").rows, []);
  }
});

test("conversion range size, boundaries and contiguous shape are checked before reading", () => {
  assert.deepEqual(conversionBox("$B$3:$C$4"), { row: 2, column: 1, height: 2, width: 2 });
  for (const address of ["A:A", "A1,B2", "B2:A1", "A1:CV21", "XFE1", "A1048577"]) {
    assert.throws(() => conversionBox(address));
  }
});
