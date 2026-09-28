// node --test web/
const test = require("node:test");
const assert = require("node:assert/strict");
const C = require("./core.js");

const top = (q, rows, opts) => {
  const cq = C.compileQuery(q, opts);
  return rows.map(([id, name]) => [C.rank(cq, id, name), id]).filter(([r]) => r)
    .sort((a, b) => C.cmp(a[0], b[0])).map(([, id]) => id);
};

test("the headline series outranks its own breakdowns", () => {
  const rows = [
    ["DF_SDG", "SDG indicator 8.5.2: Unemployment rate by sex and age"],
    ["DF_UNE_MS", "Unemployment rate by sex, age and marital status"],
    ["DF_UNE", "Unemployment rate by sex and age"],
    ["DF_UNDER", "Time-related underemployment"],
  ];
  assert.deepEqual(top("unemployment rate", rows), ["DF_UNE", "DF_UNE_MS", "DF_SDG"]);
});

test("words match in any order", () => {
  assert.deepEqual(top("national accounts", [["ANEA", "National Economic Accounts (NEA), Annual Data"]]), ["ANEA"]);
});

test("synonyms bridge spelling and shorthand, and can be turned off", () => {
  const rows = [["LF", "Labour force survey"], ["CPI", "Consumer price index"], ["X", "Other"]];
  assert.deepEqual(top("labor force", rows), ["LF"]);
  assert.deepEqual(top("labor force", rows, { synonyms: false }), []);
  assert.deepEqual(top("inflation", rows), ["CPI"]);
});

test("IMF monthly snapshots map to the dataset they copy", () => {
  assert.equal(C.vintageBase("ER_2026_MAY_VINTAGE"), "ER");
  assert.equal(C.vintageBase("MFS_CBS_2026_JAN_VINTAGE"), "MFS_CBS");
  assert.equal(C.vintageBase("ER"), null);
});

test("CSV with quoted commas, doubled quotes and CRLF", () => {
  const rows = C.parseCSV('a,b,c\r\n1,"x, y","say ""hi"""\r\n2,,\r\n');
  assert.deepEqual(rows, [["a", "b", "c"], ["1", "x, y", 'say "hi"'], ["2", "", ""]]);
  assert.equal(C.toCSV([["a", "x, y"]]), 'a,"x, y"\r\n');
});

test("labels=both cells split on the first colon", () => {
  assert.deepEqual(C.splitLabel("US: United States"), ["US", "United States"]);
  assert.deepEqual(C.splitLabel("FREQ:Frequency"), ["FREQ", "Frequency"]);
  assert.deepEqual(C.splitLabel("USD"), ["USD", ""]);
});

test("periods of every shape land on one time scale", () => {
  assert.equal(C.parsePeriod("2024").t, 2024);
  assert.equal(C.parsePeriod("2024-Q3").t, 2024.5);
  assert.equal(C.parsePeriod("2024-07").t, 2024.5);
  assert.equal(C.parsePeriod("2024-M07").t, 2024.5);   // IMF
  assert.equal(C.parsePeriod("2024-S2").t, 2024.5);
  assert.ok(Math.abs(C.parsePeriod("2024-07-01").t - 2024.497) < 0.001);
  assert.equal(C.parsePeriod("2024-W01").freq, "W");
  assert.equal(C.parsePeriod("nonsense"), null);
});

test("a year ago is written the way the provider writes it", () => {
  assert.equal(C.yearAgo("2024-Q3"), "2023-Q3");
  assert.equal(C.yearAgo("2024-M07"), "2023-07");
  assert.equal(C.yearAgo("2024-02-29"), "2023-02-28");
  assert.equal(C.yearAgo("2024"), "2023");
});

test("index and year-on-year views", () => {
  const pts = [["2023-Q1", 50], ["2023-Q2", 55], ["2023-Q3", 60], ["2023-Q4", 65], ["2024-Q1", 55], ["2024-Q2", 66]];
  assert.deepEqual(C.transform(pts, "index").map(p => +p[1].toFixed(9)), [100, 110, 120, 130, 110, 132]);
  const yoy = C.transform(pts, "yoy");
  assert.deepEqual(yoy.map(p => p[0]), ["2024-Q1", "2024-Q2"]);
  assert.ok(Math.abs(yoy[0][1] - 10) < 1e-9);
  assert.ok(Math.abs(yoy[1][1] - 20) < 1e-9);
  assert.equal(C.transform(pts, "level"), pts);
});

test("unit attributes are recognised by pattern, multipliers by power of ten", () => {
  for (const id of ["UNIT_MEASURE", "UNIT_MULT", "UNIT", "BBK_UNIT", "SCALE"]) assert.ok(C.isUnit(id), id);
  for (const id of ["COMMUNITY", "TITLE", "REF_AREA"]) assert.ok(!C.isUnit(id), id);
  assert.equal(C.multLabel("6"), "millions");
  assert.equal(C.multLabel("0"), "");
});

test("ticks bracket the data", () => {
  const t = C.niceTicks(-0.1, 5.5);
  assert.ok(t[0] <= -0.1 && t[t.length - 1] >= 5.5);
  assert.deepEqual(C.niceTicks(3, 3).length > 1, true);
});
