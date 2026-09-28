/* Pure functions shared by the page and its tests: no DOM, no network.
   Loaded as a plain script in the browser (window.Core) and with require()
   under node, so the tests exercise exactly what the page runs. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Core = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* ---------- Search ---------- */

  // Spellings and shorthands that catalogues write one way and people type
  // another. Each entry lists alternatives any one of which satisfies the word.
  // Kept small and literal: every line here is a mismatch seen in an eval or a
  // catalogue, not a guess at what might help.
  const SYNONYMS = {
    labor: ["labor", "labour"],
    labour: ["labour", "labor"],
    harmonized: ["harmonized", "harmonised"],
    harmonised: ["harmonised", "harmonized"],
    cpi: ["cpi", "consumer price"],
    hicp: ["hicp", "harmonised index of consumer prices"],
    inflation: ["inflation", "consumer price", "hicp", "cpi"],
    gdp: ["gdp", "gross domestic product"],
    jobless: ["jobless", "unemploy"],
    fx: ["fx", "exchange rate"],
    forex: ["forex", "exchange rate"],
    rates: ["rates", "rate"],
    prices: ["prices", "price"],
    bop: ["bop", "balance of payments"],
    ppi: ["ppi", "producer price"],
  };

  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const alt = s => ({ s, re: new RegExp("(?<![0-9a-z])" + esc(s)) });

  // Each query word becomes a group of alternatives. With synonyms off every
  // group has one member and the ranking is exactly sdmx_api._rank.
  function compileQuery(q, { synonyms = true } = {}) {
    q = q.trim().toLowerCase();
    const groups = q.split(/\s+/).filter(Boolean)
      .map(w => (synonyms && SYNONYMS[w] ? SYNONYMS[w] : [w]).map(alt));
    return { q, groups };
  }

  /* How closely a compiled query matches, as a sort key, or null.

     A port of sdmx_api._rank: every word must appear in the id or the name,
     in any order. Ranked by an exact match first, then whether every word
     begins a word, then how far in the last word lands, then length, since a
     headline series is the one carrying no breakdowns. */
  function rank(cq, id, name) {
    let best = null;
    for (const f of [id.toLowerCase(), name.toLowerCase()]) {
      let inside = false, at = 0, ok = true;
      for (const group of cq.groups) {
        let found = null;
        for (const a of group) {
          const i = f.indexOf(a.s);
          if (i < 0) continue;
          const m = a.re.exec(f);
          const cand = { inside: !m, at: m ? m.index : i };
          if (!found || cand.inside < found.inside || (cand.inside === found.inside && cand.at < found.at)) found = cand;
        }
        if (!found) { ok = false; break; }
        inside = inside || found.inside;
        at = Math.max(at, found.at);
      }
      if (!ok) continue;
      const key = [f === cq.q ? 0 : 1, inside ? 1 : 0, at, f.length];
      if (!best || cmp(key, best) < 0) best = key;
    }
    return best;
  }

  function cmp(a, b) {
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
    return 0;
  }

  // IMF republishes each dataset as a monthly snapshot (ER_2026_MAY_VINTAGE),
  // which buries the live dataset under copies of itself in search results.
  const VINTAGE = /^(.+)_(\d{4})_([A-Z]{3})_VINTAGE$/;
  function vintageBase(id) {
    const m = VINTAGE.exec(id);
    return m ? m[1] : null;
  }

  /* ---------- CSV ---------- */

  function parseCSV(text) {
    const rows = [];
    let row = [], cell = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; }
        else cell += c;
      } else if (c === '"') q = true;
      else if (c === ",") { row.push(cell); cell = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(cell); cell = "";
        if (row.length > 1 || row[0] !== "") rows.push(row);
        row = [];
      } else cell += c;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows;
  }

  function toCSV(rows) {
    return rows.map(r => r.map(v => {
      const s = v == null ? "" : String(v);
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(",")).join("\r\n") + "\r\n";
  }

  // labels=both writes "US: United States" in cells and "REF_AREA: Reference area"
  // in headers; BIS leaves out the space.
  function splitLabel(s) {
    const i = s.indexOf(":");
    return i < 0 ? [s.trim(), ""] : [s.slice(0, i).trim(), s.slice(i + 1).trim()];
  }

  /* ---------- Units ---------- */

  // The same pattern sdmx_api._UNIT uses: UNIT_MEASURE, UNIT_MULT, UNIT,
  // BBK_UNIT, SCALE. What a number is measured in, as opposed to prose.
  const UNIT = /(^|_)(UNIT|SCALE)(_|$)/i;
  const isUnit = id => UNIT.test(id);

  // UNIT_MULT is a power of ten and the same in every provider's codelist.
  const MULT = { 0: "", 1: "tens", 2: "hundreds", 3: "thousands", 6: "millions", 9: "billions", 12: "trillions" };
  const isMult = id => /MULT/i.test(id);
  const multLabel = code => (code in MULT ? MULT[code] : `×10^${code}`);

  /* ---------- Periods ----------
     SDMX periods are strings in one of a handful of shapes. They are placed on
     a real time scale, so a gap in a series, or monthly beside quarterly, is
     drawn at the right distance rather than one step along. */

  // IMF writes months as 2024-M01; everyone else writes 2024-01.
  const normPeriod = p => String(p).trim().replace(/^(\d{4})-M(\d{2})$/, "$1-$2");

  const PERIODS = [
    // [frequency, pattern, periods per year, fraction of the year at the start]
    ["D", /^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/, 365, m => dayOfYear(+m[1], +m[2], +m[3]) / daysIn(+m[1])],
    ["M", /^(\d{4})-(\d{2})$/, 12, m => (+m[2] - 1) / 12],
    ["Q", /^(\d{4})-Q([1-4])$/, 4, m => (+m[2] - 1) / 4],
    ["S", /^(\d{4})-[SH]([12])$/, 2, m => (+m[2] - 1) / 2],
    ["W", /^(\d{4})-W(\d{2})$/, 52, m => (+m[2] - 1) / 52.1775],
    ["A", /^(\d{4})(?:-A1)?$/, 1, () => 0],
  ];

  function dayOfYear(y, mo, d) {
    return (Date.UTC(y, mo - 1, d) - Date.UTC(y, 0, 1)) / 86400000;
  }
  const daysIn = y => (y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 366 : 365);

  // {freq, t (fractional year), ppy} or null for a shape not recognised.
  function parsePeriod(p) {
    p = normPeriod(p);
    for (const [freq, re, ppy, frac] of PERIODS) {
      const m = re.exec(p);
      if (m) return { freq, t: +m[1] + frac(m), ppy, year: +m[1] };
    }
    return null;
  }

  // The same period one year earlier, as the provider would write it.
  function yearAgo(p) {
    p = normPeriod(p);
    const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(p);
    if (d) {
      const y = +d[1] - 1, mo = +d[2], day = Math.min(+d[3], mo === 2 && daysIn(y) === 365 ? 28 : 31);
      return `${y}-${d[2]}-${String(day).padStart(2, "0")}`;
    }
    return p.replace(/^(\d{4})/, y => String(+y - 1));
  }

  const PPY = { A: 1, S: 2, Q: 4, M: 12, W: 53, D: 366, B: 262, H: 2 };

  /* ---------- Views ---------- */

  // points: [[period, value], ...] sorted by period. Returns the same shape.
  function transform(points, mode) {
    if (mode === "index") {
      const base = points.find(([, v]) => Number.isFinite(v) && v !== 0);
      if (!base) return [];
      return points.map(([p, v]) => [p, (v / base[1]) * 100]);
    }
    if (mode === "yoy") {
      const look = new Map(points.map(([p, v]) => [normPeriod(p), v]));
      const out = [];
      for (const [p, v] of points) {
        const prev = look.get(yearAgo(p));
        if (prev != null && Number.isFinite(prev) && prev !== 0) out.push([p, (v / prev - 1) * 100]);
      }
      return out;
    }
    return points;
  }

  /* ---------- Numbers ---------- */

  function niceTicks(lo, hi, n = 5) {
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
    if (lo === hi) { const pad = Math.abs(lo) * 0.1 || 1; lo -= pad; hi += pad; }
    const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0);
    const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step;
    const ticks = [];
    for (let v = a; v <= b + step / 2; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }

  function fmtNum(v) {
    const a = Math.abs(v);
    if (a >= 1e12) return (v / 1e12).toFixed(2) + "tn";
    if (a >= 1e9) return (v / 1e9).toFixed(2) + "bn";
    if (a >= 1e6) return (v / 1e6).toFixed(2) + "m";
    if (a >= 1e4) return Math.round(v).toLocaleString("en");
    return (+v.toPrecision(5)).toLocaleString("en", { maximumFractionDigits: 4 });
  }

  return {
    SYNONYMS, compileQuery, rank, cmp, vintageBase,
    parseCSV, toCSV, splitLabel,
    isUnit, isMult, multLabel,
    normPeriod, parsePeriod, yearAgo, PPY, transform,
    niceTicks, fmtNum,
  };
});
