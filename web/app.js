"use strict";
const C = window.Core;

/* ---------- Providers ----------
   Where each provider lives and how it wants to be asked. `ref` is the flow
   reference its data path accepts; `avail` is the one its availability path
   accepts, and a provider without one cannot say which codes remain once
   others are chosen. Each form was tested against the live service. */
const PROVIDERS = {
  ESTAT: {
    name: "Eurostat", short: "Eurostat", base: "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1",
    agency: "ESTAT", ref: f => f.id,
  },
  OECD: {
    name: "OECD", short: "OECD", base: "https://sdmx.oecd.org/public/rest",
    ref: f => `${f.agency},${f.id},`, avail: f => `${f.agency},${f.id},`,
  },
  ECB: {
    name: "European Central Bank", short: "ECB", base: "https://data-api.ecb.europa.eu/service",
    agency: "ECB", ref: f => f.id, accept: "text/csv",
  },
  BIS: {
    name: "Bank for International Settlements", short: "BIS", base: "https://stats.bis.org/api/v1",
    agency: "BIS", ref: f => f.id, avail: f => f.id,
  },
  IMF_DATA: {
    name: "International Monetary Fund", short: "IMF", base: "https://api.imf.org/external/sdmx/2.1",
    agency: "all", ref: f => `${f.agency},${f.id}`, avail: f => f.id,
    // Ignores the CSV Accept header and answers in structure-specific XML.
    accept: "application/vnd.sdmx.structurespecificdata+xml;version=2.1",
  },
  ABS: {
    name: "Australian Bureau of Statistics", short: "ABS", base: "https://data.api.abs.gov.au/rest",
    agency: "ABS", ref: f => `${f.agency},${f.id}`, avail: f => `${f.agency},${f.id}`,
  },
  // Added after scripts.web_probe found them answering browsers.
  ILO: {
    name: "International Labour Organization", short: "ILO", base: "https://sdmx.ilo.org/rest",
    // No availability endpoint ("not implemented"), so its pickers list the
    // whole codelist and cannot grey out combinations.
    agency: "ILO", ref: f => `${f.agency},${f.id}`,
  },
  NB: {
    name: "Norges Bank", short: "Norges Bank", base: "https://data.norges-bank.no/api",
    agency: "NB", ref: f => `${f.agency},${f.id}`, avail: f => `${f.agency},${f.id}`,
  },
  SPC: {
    name: "Pacific Community", short: "SPC", base: "https://stats-nsi-stable.pacificdata.org/rest",
    agency: "SPC", ref: f => `${f.agency},${f.id}`, avail: f => `${f.agency},${f.id}`,
  },
};
const CSV_ACCEPT = "application/vnd.sdmx.data+csv;version=1.0.0;labels=both";
const STRUCT = "application/vnd.sdmx.structure+xml;version=2.1";
const MAX_SERIES = 8;
const REPO = "https://github.com/rabidlego25/macro-mcp";

/* ---------- DOM helpers ---------- */
const $ = s => document.querySelector(s);
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) n.append(k.nodeType ? k : String(k));
  return n;
}
const byLocal = (root, name) => [...root.getElementsByTagNameNS("*", name)];
const kidsNamed = (node, name) => [...node.children].filter(c => c.localName === name);
const xml = text => new DOMParser().parseFromString(text, "application/xml");
const spinner = () => el("span", { class: "spin", "aria-hidden": "true" });

/* ---------- Browser cache ----------
   Structures and codelists change rarely and several take seconds to fetch,
   so they are kept for a week. Storage can be full, blocked or absent; every
   path works without it. */
const TTL = 7 * 24 * 3600 * 1000;
function cacheGet(key) {
  try {
    const raw = localStorage.getItem("ome1:" + key);
    if (!raw) return null;
    const { t, v } = JSON.parse(raw);
    return Date.now() - t < TTL ? v : null;
  } catch { return null; }
}
function cachePut(key, v) {
  try { localStorage.setItem("ome1:" + key, JSON.stringify({ t: Date.now(), v })); }
  catch {
    // Full: drop this app's entries and try once more.
    try {
      Object.keys(localStorage).filter(k => k.startsWith("ome1:")).forEach(k => localStorage.removeItem(k));
      localStorage.setItem("ome1:" + key, JSON.stringify({ t: Date.now(), v }));
    } catch { /* storage unavailable */ }
  }
}
const inflight = new Map();
async function cached(key, fn) {
  const hit = cacheGet(key);
  if (hit) return hit;
  if (inflight.has(key)) return inflight.get(key);
  const p = fn().then(v => { cachePut(key, v); inflight.delete(key); return v; },
    e => { inflight.delete(key); throw e; });
  inflight.set(key, p);
  return p;
}

/* ---------- Network ---------- */
async function get(url, accept, provider) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 45000);
  let res;
  try {
    res = await fetch(url, { headers: accept ? { Accept: accept } : {}, signal: ctrl.signal });
  } catch (e) {
    const who = provider ? PROVIDERS[provider].short : "The provider";
    throw new Error(e.name === "AbortError"
      ? `${who} took more than 45 seconds to answer. Narrow the selection and try again.`
      : `The request did not reach ${who}. It may be down, or it may be blocking requests from browsers right now.`);
  } finally { clearTimeout(timer); }
  const text = await res.text();
  if (!res.ok) {
    const err = new Error(explain(res.status, text, provider));
    err.status = res.status;
    throw err;
  }
  return { text, type: res.headers.get("content-type") || "" };
}

function explain(status, text, provider) {
  const who = provider ? PROVIDERS[provider].short : "The provider";
  // OECD sits behind Cloudflare, which sometimes answers with a bot check that
  // a page cannot pass. It clears up on its own.
  if (/Just a moment|challenges\.cloudflare/i.test(text))
    return `${who} is asking browsers to pass a bot check, which this page cannot do. It usually clears within the hour; open the request link directly to see it.`;
  if (status === 404) return "No data matches this selection. One of the chosen codes may not occur with the others; leave a dimension on All to see what the dataset carries.";
  if (status === 413 || /too large|exceeds/i.test(text)) return `${who} says the selection is too large. Choose fewer codes.`;
  const brief = text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 200);
  return `${who} answered ${status}${brief ? `: ${brief}` : ""}.`;
}

/* ---------- Structure ----------
   The structure definition gives the dimensions in key order and the codelist
   each one draws on. Asking for it with every codelist attached takes 30 to 90
   seconds at OECD, Eurostat and IMF, so the codelists are fetched one by one,
   in parallel, and kept. */
function parseFlowId(p, id) {
  const m = id.match(/^(?:([^:]+):)?([^()]+)(?:\((.+)\))?$/);
  return { provider: p, agency: m[1] || PROVIDERS[p].agency, id: m[2], version: m[3] || "latest", raw: id };
}

const refOf = node => {
  const r = node && byLocal(node, "Ref")[0];
  return r ? { agency: r.getAttribute("agencyID"), id: r.getAttribute("id"), version: r.getAttribute("version") || "latest",
    parent: r.getAttribute("maintainableParentID"), parentVersion: r.getAttribute("maintainableParentVersion") } : null;
};

function component(node, i) {
  const local = kidsNamed(node, "LocalRepresentation")[0];
  const enumeration = local && kidsNamed(local, "Enumeration")[0];
  return {
    id: node.getAttribute("id"),
    pos: +(node.getAttribute("position") || i + 1),
    cl: enumeration ? refOf(enumeration) : null,
    concept: refOf(kidsNamed(node, "ConceptIdentity")[0]),
  };
}

async function loadStructure(f) {
  const P = PROVIDERS[f.provider];
  return cached(`struct:${f.provider}:${f.raw}`, async () => {
    const url = f.provider === "ESTAT"
      ? `${P.base}/datastructure/ESTAT/${encodeURIComponent(f.id)}`
      : `${P.base}/dataflow/${f.agency}/${encodeURIComponent(f.id)}/${f.version}?references=datastructure`;
    let res;
    try { res = await get(url, STRUCT, f.provider); }
    catch (e) {
      if (e.status === 404) throw new Error(`${P.short} no longer lists this dataset. The search index is a snapshot and may be out of date.`);
      throw e;
    }
    const doc = xml(res.text);
    const flowEl = byLocal(doc, "Dataflow")[0];
    const agency = f.agency === "all" && flowEl ? flowEl.getAttribute("agencyID") : f.agency;
    const dims = byLocal(doc, "Dimension").filter(d => d.getAttribute("id")).map(component).sort((a, b) => a.pos - b.pos);
    const attrs = byLocal(doc, "Attribute").map(component).filter(a => a.id && C.isUnit(a.id));
    if (!dims.length) throw new Error(`${P.short} returned no dimensions for this dataset.`);
    // IMF declares no codelist on its dimensions; they inherit one from the
    // concept each identifies, which lives in a concept scheme.
    const missing = [...dims, ...attrs].filter(c => !c.cl && c.concept && c.concept.parent);
    const schemes = [...new Set(missing.map(c => `${c.concept.agency}/${c.concept.parent}/${c.concept.parentVersion || "latest"}`))];
    for (const s of schemes) {
      try {
        const cs = await cached(`cs:${f.provider}:${s}`, async () => {
          const d = xml((await get(`${P.base}/conceptscheme/${s}`, STRUCT, f.provider)).text);
          const out = {};
          for (const c of byLocal(d, "Concept")) {
            const core = kidsNamed(c, "CoreRepresentation")[0];
            const en = core && kidsNamed(core, "Enumeration")[0];
            if (en) out[c.getAttribute("id")] = refOf(en);
          }
          return out;
        });
        for (const c of missing) if (`${c.concept.agency}/${c.concept.parent}/${c.concept.parentVersion || "latest"}` === s) c.cl = cs[c.concept.id] || null;
      } catch { /* labels are a nicety; carry on without them */ }
    }
    return { agency, dims, attrs };
  });
}

// Codes that occur in the dataset at all, from its availability constraint.
async function loadCodes(f) {
  const P = PROVIDERS[f.provider];
  return cached(`codes:${f.provider}:${f.raw}`, async () => {
    const url = f.provider === "ESTAT"
      ? `${P.base}/contentconstraint/ESTAT/${encodeURIComponent(f.id)}`
      : P.avail
        ? `${P.base}/availableconstraint/${P.avail(f)}/all/all/all`
        // ECB, and anyone else without an availability endpoint, attaches
        // its constraint to the dataflow.
        : `${P.base}/dataflow/${f.agency}/${encodeURIComponent(f.id)}/latest?references=contentconstraint`;
    return parseConstraint((await get(url, STRUCT, f.provider)).text).codes;
  });
}

function parseConstraint(text) {
  const doc = xml(text);
  const codes = {};
  const region = byLocal(doc, "CubeRegion").find(r => r.getAttribute("include") !== "false");
  if (region) for (const kv of byLocal(region, "KeyValue")) {
    codes[kv.getAttribute("id")] = byLocal(kv, "Value").map(v => v.textContent.trim()).filter(Boolean);
  }
  let series = null;
  for (const a of byLocal(doc, "Annotation")) {
    if (a.getAttribute("id") === "series_count") {
      const t = byLocal(a, "AnnotationTitle")[0];
      if (t) series = +t.textContent.trim();
    }
  }
  return { codes, series };
}

// Code to English label for one codelist.
async function loadCodelist(provider, ref) {
  const P = PROVIDERS[provider];
  return cached(`cl:${provider}:${ref.agency}:${ref.id}:${ref.version}`, async () => {
    const doc = xml((await get(`${P.base}/codelist/${ref.agency}/${ref.id}/${ref.version}`, STRUCT, provider)).text);
    const out = {};
    for (const c of byLocal(doc, "Code")) {
      const names = kidsNamed(c, "Name");
      const en = names.find(n => (n.getAttribute("xml:lang") || n.getAttributeNS("http://www.w3.org/XML/1998/namespace", "lang")) === "en") || names[0];
      if (en) out[c.getAttribute("id")] = en.textContent.trim();
    }
    return out;
  });
}

/* ---------- Data ---------- */
function fromCSV(text, dimIds) {
  const [head, ...body] = C.parseCSV(text);
  if (!head) return [];
  const ids = head.map(h => C.splitLabel(h)[0]);
  const ix = id => ids.findIndex(h => h.toLowerCase() === id.toLowerCase());
  const tp = ix("TIME_PERIOD"), ov = ix("OBS_VALUE");
  const dcols = dimIds.map(d => [d, ix(d)]).filter(([, i]) => i >= 0);
  // Eurostat's `unit` is a dimension, not an attribute; it is named by the key.
  const dimSet = new Set(dimIds.map(d => d.toLowerCase()));
  const ucols = ids.map((id, i) => [id, i]).filter(([id]) => C.isUnit(id) && !dimSet.has(id.toLowerCase()));
  return body.map(r => {
    const key = {}, labels = {}, units = {};
    for (const [d, i] of dcols) { const [c, l] = C.splitLabel(r[i] || ""); key[d] = c; if (l) labels[d] = l; }
    for (const [u, i] of ucols) { const [c, l] = C.splitLabel(r[i] || ""); if (c) units[u] = { code: c, label: l }; }
    return { key, labels, units, period: C.normPeriod(r[tp]), value: r[ov] === "" ? NaN : +r[ov] };
  });
}

function fromXML(text, dimIds) {
  const doc = xml(text);
  const out = [];
  for (const s of byLocal(doc, "Series")) {
    const key = {}, units = {};
    const sk = byLocal(s, "SeriesKey")[0];
    if (sk) for (const v of byLocal(sk, "Value")) key[v.getAttribute("id") || v.getAttribute("concept")] = v.getAttribute("value");
    else for (const d of dimIds) if (s.hasAttribute(d)) key[d] = s.getAttribute(d);
    for (const a of s.getAttributeNames()) if (C.isUnit(a) && !dimIds.includes(a)) units[a] = { code: s.getAttribute(a), label: "" };
    for (const v of byLocal(s, "Attributes").flatMap(a => byLocal(a, "Value"))) {
      const id = v.getAttribute("id");
      if (id && C.isUnit(id)) units[id] = { code: v.getAttribute("value"), label: "" };
    }
    for (const o of byLocal(s, "Obs")) {
      const dim = byLocal(o, "ObsDimension")[0], val = byLocal(o, "ObsValue")[0];
      const p = o.getAttribute("TIME_PERIOD") || (dim && dim.getAttribute("value"));
      const v = o.getAttribute("OBS_VALUE") ?? (val && val.getAttribute("value"));
      out.push({ key, labels: {}, units, period: C.normPeriod(p), value: v == null || v === "" ? NaN : +v });
    }
  }
  return out;
}

const keyString = (dims, pick) => dims.map(d => (pick[d.id] || []).join("+")).join(".");
const hasKey = key => key.replace(/\./g, "") !== "";

function freqOf(cur) {
  const d = cur.dims.find(d => /^FREQ(UENCY)?$/i.test(d.id));
  const picked = d && cur.pick[d.id];
  return picked && picked.length === 1 ? picked[0] : null;
}

// How many observations to ask for. The year-on-year view needs a year more
// than it shows, or its first year is blank.
function wanted(cur) {
  if (cur.view !== "yoy") return cur.n;
  return cur.n + (C.PPY[freqOf(cur)] || 12);
}

function dataUrl(cur, n = wanted(cur)) {
  const P = PROVIDERS[cur.provider];
  const key = keyString(cur.dims, cur.pick);
  const params = new URLSearchParams({ lastNObservations: n });
  if (cur.provider === "ESTAT") params.set("format", "SDMX-CSV");
  return `${P.base}/data/${P.ref(cur.f)}/${hasKey(key) ? key : "all"}?${params}`;
}

function label(cur, dim, code) {
  const d = cur.dims.find(x => x.id === dim);
  return (d && d.labels && d.labels[code]) || null;
}

function toSeries(obs, cur) {
  const map = new Map();
  for (const o of obs) {
    if (!Number.isFinite(o.value) || !o.period) continue;
    const id = cur.dims.map(d => o.key[d.id] ?? "").join(".");
    if (!map.has(id)) map.set(id, { id, key: o.key, labels: o.labels, units: o.units, points: [] });
    map.get(id).points.push([o.period, o.value]);
  }
  const series = [...map.values()];
  for (const s of series) {
    s.points.sort((a, b) => ((C.parsePeriod(a[0]) || {}).t ?? 0) - ((C.parsePeriod(b[0]) || {}).t ?? 0));
  }
  return series;
}

/* ---------- App state ---------- */
let CATALOGUE = null, STATUS = null, CHANGES = null;
const VINTAGES = {};           // "P/baseId" -> count of monthly snapshots
const state = { provider: null, current: null };

/* ---------- Search ---------- */
function search() {
  const cq = C.compileQuery($("#q").value);
  const hits = [], counts = {};
  for (const [p, flows] of Object.entries(CATALOGUE.providers)) {
    counts[p] = 0;
    for (const [id, name] of flows) {
      if (flows.hidden && flows.hidden.has(id)) continue;
      const r = cq.groups.length ? C.rank(cq, id, name) : null;
      if (!r) continue;
      counts[p]++;
      if (!state.provider || state.provider === p) hits.push([r, p, id, name]);
    }
  }
  hits.sort((a, b) => C.cmp(a[0], b[0]));
  renderChips(counts);
  const shown = hits.slice(0, 60);
  const total = hits.length;
  $("#count").textContent = !cq.groups.length
    ? `${indexSize().toLocaleString("en")} datasets. Type a subject to search, e.g. inflation, policy rate, GDP.`
    : total ? `${total.toLocaleString("en")} match${total === 1 ? "" : "es"}${total > shown.length ? `, closest ${shown.length} shown` : ""}`
    : "No matches. Try fewer or different words.";
  $("#results").replaceChildren(...shown.map(([, p, id, name]) => {
    const snaps = VINTAGES[`${p}/${id}`];
    const isNew = CHANGES && CHANGES[`${p}/${id}`];
    return el("li", {}, el("button", {
      type: "button",
      "aria-current": state.current && state.current.provider === p && state.current.id === id ? "true" : false,
      onclick: () => openFlow(p, id, name),
    },
      el("span", { class: "name" }, name, isNew ? el("span", { class: "tag new", title: `Added ${isNew}` }, "New") : null),
      el("span", { class: "meta" },
        el("span", { class: "prov" }, PROVIDERS[p].short),
        el("span", { class: "mono" }, id),
        snaps ? el("span", {}, `+${snaps} monthly snapshots`) : null)));
  }));
}

const indexSize = () => Object.values(CATALOGUE.providers).reduce((a, f) => a + f.length - (f.hidden ? f.hidden.size : 0), 0);

function health(p) {
  const s = STATUS && STATUS.providers && STATUS.providers[p];
  if (!s) return null;
  return s;
}

function renderChips(counts) {
  const all = Object.values(counts).reduce((a, b) => a + b, 0);
  const chip = (p, text, n) => {
    const h = p && health(p);
    const cls = h && h.state !== "ok" ? h.state : null;
    return el("button", {
      type: "button", class: "chip", "aria-pressed": String(state.provider === p),
      title: h ? `${PROVIDERS[p].name}: ${h.note}` : p ? PROVIDERS[p].name : "Every provider",
      onclick: () => { state.provider = p; search(); },
    }, cls ? el("i", { class: `dot ${cls}`, "aria-label": h.state === "down" ? "not answering" : "slow" }) : null,
      text, el("span", { class: "n" }, n.toLocaleString("en")));
  };
  $("#provs").replaceChildren(chip(null, "All", all),
    ...Object.keys(PROVIDERS).map(p => chip(p, PROVIDERS[p].short, counts[p] || 0)));
}

/* ---------- Dataset panel ---------- */
async function openFlow(p, rawId, name, preset, view = "level") {
  const f = parseFlowId(p, rawId);
  const cur = state.current = {
    provider: p, id: rawId, name, f, dims: null, attrs: [], pick: {}, n: 60,
    possible: null, series: null, result: null, dimCtl: {}, view,
  };
  search();
  const h = health(p);
  $("#panel").replaceChildren(
    head(cur),
    h && h.state === "down" ? el("p", { class: "status warn" }, `${PROVIDERS[p].short} failed today's health check: ${h.note}`) : null,
    el("p", { class: "status" }, spinner(), `Reading the structure from ${PROVIDERS[p].short}…`));
  let structure, codes = {};
  try {
    [structure, codes] = await Promise.all([loadStructure(f), loadCodes(f).catch(() => ({}))]);
  } catch (e) {
    if (state.current !== cur) return;
    $("#panel").replaceChildren(head(cur), el("p", { class: "status bad" }, el("strong", {}, "Could not read this dataset. "), e.message));
    return;
  }
  if (state.current !== cur) return;
  f.agency = structure.agency;
  cur.dims = structure.dims.map(d => ({ ...d, codes: codes[d.id] || null, labels: null }));
  cur.attrs = structure.attrs;

  if (typeof preset === "string") preset.split(".").forEach((part, i) => {
    if (cur.dims[i] && part) cur.pick[cur.dims[i].id] = part.split("+");
  });
  else if (preset) cur.pick = { ...preset };
  // A dimension with one code is not a choice; fill it in.
  for (const d of cur.dims) if (d.codes && d.codes.length === 1) cur.pick[d.id] = [d.codes[0]];

  renderPanel();
  loadLabels(cur);
  refreshAvailability(cur);
  // Only fetch straight away when something has been chosen. An open key on a
  // large dataset such as ECB exchange rates is thousands of series.
  if (preset) fetchData();
  else $("#out").replaceChildren(el("p", { class: "status" },
    "Choose codes above, then Get data. Leaving everything on All can return thousands of series."));
}

function loadLabels(cur) {
  for (const d of cur.dims) {
    if (!d.cl) continue;
    loadCodelist(cur.provider, d.cl).then(labels => {
      if (state.current !== cur) return;
      d.labels = labels;
      // With no constraint to say which codes occur, offer the whole codelist.
      if (!d.codes) d.codes = Object.keys(labels);
      cur.dimCtl[d.id] && cur.dimCtl[d.id].refresh();
      if (cur.result) renderResult();
    }).catch(() => {});
  }
}

// Ask which codes remain possible given everything else chosen, and how many
// series the current selection matches. Only providers with an availability
// endpoint can answer; the rest show every code the dataset carries.
let availTimer = null;
function refreshAvailability(cur) {
  const P = PROVIDERS[cur.provider];
  if (!P.avail) { renderMatch(cur); return; }
  clearTimeout(availTimer);
  availTimer = setTimeout(async () => {
    const key = keyString(cur.dims, cur.pick);
    const path = `${P.base}/availableconstraint/${P.avail(cur.f)}/${hasKey(key) ? key : "all"}/all/all`;
    cur.availKey = key;
    cur.matching = "…";
    renderMatch(cur);
    const [avail, exact] = await Promise.allSettled([
      get(`${path}?mode=available`, STRUCT, cur.provider),
      get(path, STRUCT, cur.provider)]);
    if (state.current !== cur || cur.availKey !== key) return;
    cur.possible = avail.status === "fulfilled" ? parseConstraint(avail.value.text).codes : null;
    if (exact.status === "fulfilled") cur.matching = parseConstraint(exact.value.text).series;
    else cur.matching = exact.reason && exact.reason.status === 404 ? 0 : null;
    for (const d of cur.dims) cur.dimCtl[d.id] && cur.dimCtl[d.id].refresh();
    renderMatch(cur);
  }, 300);
}

function renderMatch(cur) {
  const box = $("#match");
  if (!box) return;
  const m = cur.matching;
  box.className = "match" + (m === 0 ? " none" : "");
  box.textContent = m === "…" ? "Counting matching series…"
    : m === 0 ? "No series match this selection. Remove a code marked “no data”."
    : typeof m === "number" ? `${m.toLocaleString("en")} series match${m > MAX_SERIES ? `; the first ${MAX_SERIES} will be charted` : ""}`
    : "";
}

function head(cur) {
  const snaps = VINTAGES[`${cur.provider}/${cur.id}`];
  return el("div", { class: "flow-head" },
    el("p", { class: "eyebrow" }, PROVIDERS[cur.provider].name),
    el("h2", {}, cur.name),
    el("div", { class: "sub" }, el("span", { class: "mono" }, cur.id),
      snaps ? el("span", {}, `IMF also publishes ${snaps} monthly snapshots of this dataset`) : null));
}

function renderPanel() {
  const cur = state.current;
  const dimsBox = el("div", { class: "dims" });
  cur.dimCtl = {};
  for (const d of cur.dims) {
    const ctl = dimControl(cur, d);
    cur.dimCtl[d.id] = ctl;
    dimsBox.append(ctl.node);
  }
  const nInput = el("input", { id: "nobs", type: "number", min: 1, max: 500, value: cur.n, inputmode: "numeric",
    oninput: e => { cur.n = Math.max(1, Math.min(500, +e.target.value || 60)); updateRequest(); } });
  const views = el("div", { class: "seg", role: "radiogroup", "aria-label": "View as" },
    [["level", "Level"], ["index", "Index, start = 100"], ["yoy", "% change on a year ago"]].map(([v, t]) =>
      el("button", { type: "button", role: "radio", "aria-checked": String(cur.view === v), "data-view": v,
        onclick: () => setView(v) }, t)));
  $("#panel").replaceChildren(
    head(cur),
    el("div", {}, el("p", { class: "eyebrow" }, "Choose codes for each dimension. Leave one on All to get every code."), dimsBox),
    el("div", { class: "controls" },
      el("div", { class: "field nfield" }, el("label", { class: "lbl", for: "nobs" }, "Latest observations"), nInput),
      el("div", { class: "field" }, el("span", { class: "lbl", id: "view-lbl" }, "View as"), views),
      el("button", { class: "primary", id: "go", type: "button", onclick: fetchData }, "Get data")),
    el("p", { id: "match", class: "match", "aria-live": "polite" }),
    el("div", { id: "out" }),
    requestPanel());
  updateRequest();
  renderMatch(cur);
}

function setView(v) {
  const cur = state.current;
  const before = wanted(cur);
  cur.view = v;
  document.querySelectorAll(".seg button").forEach(b => b.setAttribute("aria-checked", String(b.dataset.view === v)));
  updateRequest();
  // The year-on-year view needs a year more history than was fetched.
  if (cur.result && wanted(cur) > before && cur.fetched < wanted(cur)) fetchData();
  else if (cur.result) renderResult();
}

/* A picker per dimension: the chosen codes as removable chips, and a
   searchable list that matches code or label. Codes that cannot occur with
   the other choices stay listed but are marked, so nothing silently vanishes. */
function dimControl(cur, d) {
  const listId = `list-${d.id}`;
  const chips = el("div", { class: "picked" });
  const input = el("input", {
    id: `dim-${d.id}`, type: "text", autocomplete: "off", spellcheck: "false",
    role: "combobox", "aria-expanded": "false", "aria-controls": listId, "aria-autocomplete": "list",
    placeholder: d.codes ? "Search codes…" : "Type a code, then Enter",
    "aria-label": `Add a ${d.id} code`,
  });
  const list = el("ul", { id: listId, class: "listbox", role: "listbox", hidden: true });
  const countEl = el("span", {});
  let active = -1, options = [];

  const lab = c => (d.labels && d.labels[c]) || "";
  const possible = c => !cur.possible || !cur.possible[d.id] || cur.possible[d.id].includes(c);

  function add(code) {
    const picked = cur.pick[d.id] || [];
    if (!picked.includes(code)) cur.pick[d.id] = [...picked, code];
    input.value = "";
    close();
    changed();
  }
  function remove(code) {
    cur.pick[d.id] = (cur.pick[d.id] || []).filter(x => x !== code);
    changed();
    input.focus();
  }
  function changed() {
    renderChips();
    updateRequest();
    refreshAvailability(cur);
  }

  function renderChips() {
    const picked = cur.pick[d.id] || [];
    chips.replaceChildren(...(picked.length ? picked.map(c => {
      const ok = possible(c);
      return el("span", { class: "code" + (ok ? "" : " dead"), title: ok ? c : `${c}: no data with the other choices` },
        el("span", { class: "cid" }, c),
        lab(c) ? el("span", { class: "clab" }, lab(c)) : null,
        ok ? null : el("span", { class: "clab" }, "no data"),
        el("button", { type: "button", "aria-label": `Remove ${lab(c) || c}`, onclick: () => remove(c) }, "×"));
    }) : [el("span", { class: "all" }, "All")]));
    const n = d.codes ? d.codes.length : 0;
    const live = cur.possible && cur.possible[d.id] && d.codes ? d.codes.filter(possible).length : n;
    countEl.textContent = !d.codes ? "codes unknown" : live !== n ? `${live} of ${n} possible` : `${n} code${n === 1 ? "" : "s"}`;
  }

  function renderList() {
    if (!d.codes) { close(); return; }
    const q = input.value.trim().toLowerCase();
    const picked = new Set(cur.pick[d.id] || []);
    const match = d.codes.filter(c => !picked.has(c) && (!q || c.toLowerCase().includes(q) || lab(c).toLowerCase().includes(q)));
    match.sort((a, b) => (possible(b) - possible(a)) || (q ? (a.toLowerCase() === q ? -1 : b.toLowerCase() === q ? 1 : 0) : 0));
    options = match.slice(0, 80);
    active = options.length ? 0 : -1;
    list.replaceChildren(...[...options.map((c, i) => el("li", {
      id: `${listId}-${i}`, role: "option", class: possible(c) ? "" : "dead", "aria-selected": String(i === active),
      onmousedown: e => { e.preventDefault(); add(c); },
    }, el("span", { class: "cid" }, c), el("span", { class: "clab" }, lab(c) || ""), possible(c) ? null : el("span", { class: "hint" }, "no data"))),
    match.length > options.length ? el("li", { class: "more", "aria-disabled": "true" }, `${match.length - options.length} more; keep typing to narrow`) : null,
    !match.length ? el("li", { class: "more", "aria-disabled": "true" }, "No codes match") : null].filter(Boolean));
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-activedescendant", active >= 0 ? `${listId}-${active}` : "");
  }
  function move(delta) {
    if (!options.length) return;
    active = (active + delta + options.length) % options.length;
    [...list.querySelectorAll('[role="option"]')].forEach((o, i) => o.setAttribute("aria-selected", String(i === active)));
    const node = document.getElementById(`${listId}-${active}`);
    node && node.scrollIntoView({ block: "nearest" });
    input.setAttribute("aria-activedescendant", `${listId}-${active}`);
  }
  function close() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  input.addEventListener("focus", renderList);
  input.addEventListener("input", renderList);
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") { e.preventDefault(); list.hidden ? renderList() : move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Escape") close();
    else if (e.key === "Enter") {
      e.preventDefault();
      if (!d.codes && input.value.trim()) add(input.value.trim());
      else if (active >= 0 && options[active]) add(options[active]);
    } else if (e.key === "Backspace" && !input.value && (cur.pick[d.id] || []).length) {
      remove(cur.pick[d.id][cur.pick[d.id].length - 1]);
    }
  });

  renderChips();
  return {
    node: el("div", { class: "dim" },
      el("div", { class: "dname" }, el("label", { for: `dim-${d.id}` }, d.id), countEl),
      chips, el("div", { class: "combo" }, input, list)),
    refresh() { renderChips(); if (!list.hidden) renderList(); },
  };
}

/* ---------- Request panel: the URL, the MCP call, and exports ---------- */
function requestPanel() {
  return el("details", { class: "request" },
    el("summary", {}, "Request, and the same query in Claude"),
    el("div", { class: "reqbody" },
      el("div", {}, el("p", { class: "eyebrow" }, "Series key"), el("code", { id: "keyline", class: "key" })),
      el("div", {}, el("p", { class: "eyebrow" }, "Request sent to the provider"), el("a", { id: "requrl", target: "_blank", rel: "noopener" })),
      el("div", {},
        el("p", { class: "eyebrow" }, "The same query through the macro-mcp server"),
        el("pre", { id: "mcpcall", class: "snippet" }),
        el("div", { class: "row" }, copyButton("Copy call", () => $("#mcpcall").textContent))),
      el("div", {},
        el("p", { class: "eyebrow" }, "Add the server to Claude Desktop or Claude Code"),
        el("pre", { class: "snippet" }, mcpConfig()),
        el("div", { class: "row" }, copyButton("Copy config", mcpConfig),
          el("a", { href: REPO, target: "_blank", rel: "noopener" }, "macro-mcp on GitHub")))));
}

const mcpConfig = () => JSON.stringify({ mcpServers: { macro: { command: "uvx",
  args: ["--from", `git+${REPO}`, "macro-mcp"] } } }, null, 2);

function mcpCall(cur) {
  const key = {};
  for (const d of cur.dims) if ((cur.pick[d.id] || []).length) key[d.id] = cur.pick[d.id].join("+");
  return `fetch_data(\n  provider="${cur.provider}",\n  flow="${cur.id}",\n  key=${JSON.stringify(key)},\n  limit=${cur.n}\n)`;
}

function copyButton(text, get) {
  const b = el("button", { type: "button", class: "ghost" }, text);
  b.addEventListener("click", async () => {
    const value = get();
    try { await navigator.clipboard.writeText(value); b.textContent = "Copied"; }
    catch {
      // Clipboard refused: select the text so the viewer can copy it themselves.
      const pre = b.closest("div").previousElementSibling;
      if (pre) { const r = document.createRange(); r.selectNodeContents(pre); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
      b.textContent = "Selected; press Ctrl+C";
    }
    setTimeout(() => { b.textContent = text; }, 1800);
  });
  return b;
}

function updateRequest() {
  const cur = state.current;
  if (!cur || !cur.dims) return;
  const key = keyString(cur.dims, cur.pick);
  const url = dataUrl(cur);
  const k = $("#keyline"); if (k) k.textContent = hasKey(key) ? key : "(everything)";
  const a = $("#requrl"); if (a) { a.textContent = url; a.href = url; }
  const m = $("#mcpcall"); if (m) m.textContent = mcpCall(cur);
  const view = cur.view === "level" ? "" : `/${cur.view}`;
  try { history.replaceState(null, "", `#${[cur.provider, cur.id].map(encodeURIComponent).join("/")}/${key}${view}`); } catch { /* sandboxed */ }
}

/* ---------- Fetch and render ---------- */
async function fetchData() {
  const cur = state.current;
  updateRequest();
  const out = $("#out"), go = $("#go");
  const n = wanted(cur);
  const url = dataUrl(cur, n);
  const token = (cur.token = {});
  go.disabled = true;
  out.replaceChildren(el("p", { class: "status" }, spinner(), `Asking ${PROVIDERS[cur.provider].short} for data…`));
  const P = PROVIDERS[cur.provider];
  let res;
  try { res = await get(url, P.accept || CSV_ACCEPT, cur.provider); }
  catch (e) {
    if (cur.token !== token) return;
    go.disabled = false;
    out.replaceChildren(el("p", { class: "status bad" }, el("strong", {}, "No data. "), e.message));
    return;
  }
  if (cur.token !== token) return;
  go.disabled = false;
  const ids = cur.dims.map(d => d.id);
  const obs = /csv|text\/plain/i.test(res.type) || !res.text.trimStart().startsWith("<")
    ? fromCSV(res.text, ids) : fromXML(res.text, ids);
  const series = toSeries(obs, cur);
  if (!series.length) {
    // Eurostat answers a large request with a footer pointing at a file it
    // will build later, rather than with data.
    const queued = /Footer|asynchronous|\.zip/i.test(res.text);
    const widest = cur.dims
      .map(d => [d, (cur.pick[d.id] || []).length || (d.codes ? d.codes.length : 0)])
      .sort((a, b) => b[1] - a[1])[0];
    out.replaceChildren(el("p", { class: "status warn" }, queued
      ? `Eurostat queued this request instead of answering it, which it does for large selections.${widest ? ` Narrow ${widest[0].id} (${widest[1]} codes selected) and try again.` : ""}`
      : "The provider answered with no observations for this selection. Leave a dimension on All to see what the dataset carries."));
    cur.result = null;
    return;
  }
  cur.fetched = n;
  cur.result = { series };
  loadUnitLabels(cur);
  renderResult();
}

// Unit attributes arrive as codes (BIS sends UNIT_MEASURE="368"). Resolve them
// through the attribute's codelist where the structure named one.
function loadUnitLabels(cur) {
  for (const a of cur.attrs) {
    if (!a.cl || a.labels || C.isMult(a.id)) continue;
    loadCodelist(cur.provider, a.cl).then(l => {
      if (state.current !== cur) return;
      a.labels = l;
      if (cur.result) renderResult();
    }).catch(() => {});
  }
}

function unitText(cur, units) {
  const parts = [];
  let mult = "";
  for (const [id, u] of Object.entries(units || {})) {
    if (!u.code) continue;
    if (C.isMult(id)) { mult = C.multLabel(u.code); continue; }
    const attr = cur.attrs.find(a => a.id === id);
    parts.push(u.label || (attr && attr.labels && attr.labels[u.code]) || u.code);
  }
  const text = [...new Set(parts)].join(", ");
  return [text, mult].filter(Boolean).join(", in ");
}

function seriesName(cur, s, vary) {
  if (!vary.length) return cur.name;
  return vary.map(d => s.labels[d.id] || label(cur, d.id, s.key[d.id]) || s.key[d.id]).join(" · ");
}

function renderResult() {
  const cur = state.current;
  const out = $("#out");
  if (!cur.result || !out) return;
  const all = cur.result.series;
  const vary = cur.dims.filter(d => new Set(all.map(s => s.key[d.id])).size > 1);
  const fixed = cur.dims.filter(d => !vary.includes(d));
  const s0 = all[0];

  // Transform, then trim to what was asked for. The extra year fetched for the
  // year-on-year view is only there to be divided by.
  const series = all.slice(0, MAX_SERIES).map(s => {
    const pts = C.transform(s.points, cur.view).slice(-cur.n);
    return { ...s, name: seriesName(cur, s, vary), shown: pts };
  }).filter(s => s.shown.length);

  const context = fixed
    .map(d => s0.labels[d.id] || label(cur, d.id, s0.key[d.id]) || s0.key[d.id])
    .filter(v => v && v !== "Not applicable" && v !== "_Z");
  const unitSets = [...new Set(all.map(s => unitText(cur, s.units)))];
  const measured = cur.view === "index" ? "Index, first period shown = 100"
    : cur.view === "yoy" ? "Percent change on the same period a year earlier"
    : unitSets.length === 1 ? unitSets[0] : unitSets.length > 1 ? "Units differ between series; see the table" : "";

  const parts = [];
  if (all.length > MAX_SERIES) parts.push(el("p", { class: "status warn" },
    `${all.length} series came back. The first ${MAX_SERIES} are charted; choose codes to narrow it.`));
  if (!series.length) {
    parts.push(el("p", { class: "status warn" }, cur.view === "yoy"
      ? "There is not a year of history to compare against. Switch to Level, or raise Latest observations."
      : "Nothing to show in this view."));
    out.replaceChildren(...parts);
    return;
  }
  const tabs = el("div", { class: "tabs", role: "tablist" },
    ["chart", "table"].map(v => el("button", { type: "button", role: "tab", "aria-selected": String((cur.tab || "chart") === v),
      onclick: () => { cur.tab = v; renderResult(); } }, v === "chart" ? "Chart" : "Table")));
  const actions = el("div", { class: "row" },
    el("button", { type: "button", class: "ghost", onclick: () => download(cur, series) }, "Download CSV"),
    copyButton("Copy link", () => location.href));
  const title = el("div", { class: "chart-title" },
    el("h3", {}, cur.name),
    context.length ? el("p", { class: "ctx" }, context.join(" · ")) : null,
    measured ? el("p", { class: "units" }, measured) : null);
  parts.push(title, el("div", { class: "tabbar" }, tabs, actions));
  if ((cur.tab || "chart") === "chart") {
    const box = el("div", { class: "chart-box" });
    parts.push(box);
    out.replaceChildren(...parts);
    drawChart(box, series);
  } else {
    parts.push(table(series));
    out.replaceChildren(...parts);
  }
}

function periodsOf(series) {
  return [...new Set(series.flatMap(s => s.shown.map(p => p[0])))]
    .sort((a, b) => ((C.parsePeriod(a) || {}).t ?? 0) - ((C.parsePeriod(b) || {}).t ?? 0));
}

function table(series) {
  const periods = periodsOf(series).reverse();
  const look = series.map(s => new Map(s.shown));
  return el("div", { class: "table-wrap", tabindex: 0, role: "region", "aria-label": "Data table" },
    el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Period"), series.map(s => el("th", {}, s.name)))),
      el("tbody", {}, periods.map(p => el("tr", {}, el("td", {}, p),
        look.map(m => el("td", {}, m.has(p) ? C.fmtNum(m.get(p)) : "–")))))));
}

function download(cur, series) {
  const periods = periodsOf(series);
  const look = series.map(s => new Map(s.shown));
  const rows = [["period", ...series.map(s => s.name)], ...periods.map(p => [p, ...look.map(m => (m.has(p) ? m.get(p) : ""))])];
  const blob = new Blob([C.toCSV(rows)], { type: "text/csv" });
  const a = el("a", { href: URL.createObjectURL(blob), download: `${cur.provider}_${cur.f.id}_${cur.view}.csv` });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

/* ---------- Chart ----------
   One y-axis, periods on a real time scale, a crosshair that follows the
   pointer, touch drag and the arrow keys. */
function drawChart(box, series) {
  const NS = "http://www.w3.org/2000/svg";
  const s = (tag, attrs = {}) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
  const periods = periodsOf(series);
  const tOf = new Map(periods.map(p => [p, (C.parsePeriod(p) || {}).t ?? periods.indexOf(p)]));
  const values = series.flatMap(x => x.shown.map(p => p[1]));
  const ticks = C.niceTicks(Math.min(...values), Math.max(...values));
  const t0 = tOf.get(periods[0]), t1 = tOf.get(periods[periods.length - 1]);

  const legend = series.length > 1 ? el("div", { class: "legend" }, series.map((x, i) =>
    el("span", {}, el("i", { class: "sw", style: `background:var(--s${i + 1})` }), x.name))) : null;
  const tip = el("div", { class: "tip", hidden: true, role: "status" });
  let focusIdx = periods.length - 1;

  function render() {
    const W = Math.max(280, box.clientWidth);
    const H = Math.round(Math.min(420, Math.max(240, W * 0.5)));
    // End labels need room beside the plot; on a phone the legend names the lines.
    const direct = series.length > 1 && series.length <= 4 && W >= 520;
    const labelW = direct ? Math.min(150, W * 0.22) : 14;
    const m = { t: 12, r: labelW, b: 28, l: 52 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const x = t => m.l + (t1 === t0 ? iw / 2 : ((t - t0) / (t1 - t0)) * iw);
    const xp = p => x(tOf.get(p));
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const y = v => m.t + ih - ((v - y0) / (y1 - y0)) * ih;

    const svg = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", tabindex: 0,
      "aria-label": `Line chart of ${series.length} series from ${periods[0]} to ${periods[periods.length - 1]}. Use the arrow keys to read values.` });
    for (const t of ticks) {
      svg.append(s("line", { class: t === 0 || t === y0 ? "base" : "grid", x1: m.l, x2: m.l + iw, y1: y(t), y2: y(t) }));
      const lab = s("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end" }); lab.textContent = C.fmtNum(t); svg.append(lab);
    }
    // Period labels: the last always, then every period that leaves room.
    const minGap = 74, placed = [periods.length - 1];
    for (let i = 0; i < periods.length - 1; i++) {
      const last = placed.length > 1 ? placed[placed.length - 1] : null;
      if ((last == null || xp(periods[i]) - xp(periods[last]) >= minGap) && xp(periods[periods.length - 1]) - xp(periods[i]) >= minGap) placed.push(i);
    }
    for (const i of placed) {
      const lab = s("text", { x: xp(periods[i]), y: H - 8,
        "text-anchor": i === periods.length - 1 ? "end" : i === 0 && periods.length > 1 ? "start" : "middle" });
      lab.textContent = periods[i]; svg.append(lab);
    }

    const ends = [];
    series.forEach((ser, k) => {
      const color = `var(--s${k + 1})`;
      const d = ser.shown.map(([p, v], j) => `${j ? "L" : "M"}${xp(p).toFixed(1)},${y(v).toFixed(1)}`).join("");
      svg.append(s("path", { class: "line", d, style: `stroke:${color}` }));
      const [lp, lv] = ser.shown[ser.shown.length - 1];
      svg.append(s("circle", { class: "end", cx: xp(lp), cy: y(lv), r: 4, style: `fill:${color}` }));
      ends.push({ y: y(lv), name: ser.name, x: xp(lp) });
    });
    if (direct) {
      const order = ends.map(e => ({ ...e })).sort((a, b) => a.y - b.y);
      for (let i = 1; i < order.length; i++) if (order[i].y - order[i - 1].y < 14) order[i].y = order[i - 1].y + 14;
      const floor = m.t + ih - 2;
      if (order.length && order[order.length - 1].y > floor) {
        order[order.length - 1].y = floor;
        for (let i = order.length - 2; i >= 0; i--) order[i].y = Math.min(order[i].y, order[i + 1].y - 14);
      }
      const max = Math.floor((labelW - 10) / 6.2);
      for (const e of order) {
        const t = s("text", { class: "dlabel", x: e.x + 8, y: e.y + 4 });
        t.textContent = e.name.length > max ? e.name.slice(0, max - 1) + "…" : e.name;
        svg.append(t);
      }
    }

    const cross = s("line", { class: "cross", y1: m.t, y2: m.t + ih, visibility: "hidden" });
    svg.append(cross);
    const dots = series.map((_, k) => { const c = s("circle", { r: 4, class: "end", style: `fill:var(--s${k + 1})`, visibility: "hidden" }); svg.append(c); return c; });
    const hit = s("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" });
    svg.append(hit);
    const looks = series.map(ser => new Map(ser.shown));

    function show(i) {
      focusIdx = i;
      const p = periods[i];
      cross.setAttribute("x1", xp(p)); cross.setAttribute("x2", xp(p)); cross.setAttribute("visibility", "visible");
      const rows = [];
      looks.forEach((lk, k) => {
        if (lk.has(p)) { dots[k].setAttribute("cx", xp(p)); dots[k].setAttribute("cy", y(lk.get(p))); dots[k].setAttribute("visibility", "visible"); rows.push([k, lk.get(p)]); }
        else dots[k].setAttribute("visibility", "hidden");
      });
      rows.sort((a, b) => b[1] - a[1]);
      tip.replaceChildren(el("div", { class: "tp" }, p), ...rows.map(([k, v]) =>
        el("div", { class: "row" }, el("i", { class: "sw", style: `background:var(--s${k + 1})` }),
          el("span", {}, series.length > 1 ? series[k].name : "Value"), el("strong", {}, C.fmtNum(v)))));
      tip.hidden = false;
      const r = svg.getBoundingClientRect(), bx = box.getBoundingClientRect();
      const left = (xp(p) / W) * r.width + (r.left - bx.left);
      const tw = tip.offsetWidth;
      tip.style.left = `${Math.max(0, left + 12 + tw > bx.width ? left - 12 - tw : left + 12)}px`;
      tip.style.top = `${m.t}px`;
    }
    function hide() { tip.hidden = true; cross.setAttribute("visibility", "hidden"); dots.forEach(d => d.setAttribute("visibility", "hidden")); }
    function nearest(ev) {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width);
      const t = t0 + ((px - m.l) / iw) * (t1 - t0);
      let best = 0;
      periods.forEach((p, i) => { if (Math.abs(tOf.get(p) - t) < Math.abs(tOf.get(periods[best]) - t)) best = i; });
      return best;
    }
    hit.addEventListener("pointermove", ev => show(nearest(ev)));
    hit.addEventListener("pointerdown", ev => show(nearest(ev)));
    hit.addEventListener("pointerleave", ev => { if (ev.pointerType === "mouse") hide(); });
    svg.addEventListener("keydown", ev => {
      const step = { ArrowLeft: -1, ArrowRight: 1 }[ev.key];
      if (step) { ev.preventDefault(); show(Math.max(0, Math.min(periods.length - 1, focusIdx + step))); }
      else if (ev.key === "Home") { ev.preventDefault(); show(0); }
      else if (ev.key === "End") { ev.preventDefault(); show(periods.length - 1); }
      else if (ev.key === "Escape") hide();
    });
    svg.addEventListener("focus", () => show(focusIdx));
    svg.addEventListener("blur", hide);
    box.replaceChildren(svg, tip, ...(legend ? [legend] : []));
  }
  render();
  let last = box.clientWidth;
  new ResizeObserver(() => { if (Math.abs(box.clientWidth - last) > 4) { last = box.clientWidth; render(); } }).observe(box);
}

/* ---------- Start ---------- */
async function optionalJSON(url) {
  try { const r = await fetch(url, { cache: "no-cache" }); return r.ok ? await r.json() : null; } catch { return null; }
}

(async () => {
  try {
    CATALOGUE = await (await fetch("catalogue.json")).json();
  } catch {
    $("#count").textContent = "The dataset index did not load. Serve this folder over HTTP rather than opening the file directly.";
    return;
  }
  // Fold IMF's monthly snapshots under the dataset they copy.
  for (const [p, flows] of Object.entries(CATALOGUE.providers)) {
    const ids = new Set(flows.map(f => f[0]));
    flows.hidden = new Set();
    for (const [id] of flows) {
      const base = C.vintageBase(id);
      if (base && ids.has(base)) { flows.hidden.add(id); VINTAGES[`${p}/${base}`] = (VINTAGES[`${p}/${base}`] || 0) + 1; }
    }
  }
  [STATUS, CHANGES] = await Promise.all([optionalJSON("status.json"), optionalJSON("changes.json")]);
  if (CHANGES) {
    // Only the last fortnight counts as new.
    const cutoff = new Date(Date.now() - 14 * 86400000).toISOString().slice(0, 10);
    CHANGES = Object.fromEntries(Object.entries(CHANGES.added || {}).filter(([, d]) => d >= cutoff));
  }
  const built = [`Search index: ${indexSize().toLocaleString("en")} datasets across ${Object.keys(PROVIDERS).length} providers, catalogued ${CATALOGUE.built}.`];
  if (STATUS) built.push(`Providers checked ${STATUS.checked}.`);
  $("#built").textContent = built.join(" ");

  $("#q").addEventListener("input", () => search());
  // A link names a dataset, a selection and a view: #PROVIDER/ID/KEY/VIEW,
  // e.g. #BIS/WS_CBPOL/M.US+XM+GB+JP/yoy. Everything after the id is optional.
  const [hp, hid, hkey, hview] = location.hash.slice(1).split("/").map(decodeURIComponent);
  const hit = hp in PROVIDERS && CATALOGUE.providers[hp].find(([id]) => id === hid);
  if (hit) {
    $("#q").value = hit[1].split(/[\s,(]+/).slice(0, 2).join(" ");
    search();
    openFlow(hp, hit[0], hit[1], hkey || null, ["index", "yoy"].includes(hview) ? hview : "level");
    return;
  }
  $("#q").value = "unemployment";
  search();
  // Open on a working example: monthly unemployment in the four largest euro economies.
  openFlow("ESTAT", "UNE_RT_M", "Unemployment by sex and age - monthly data",
    { freq: ["M"], s_adj: ["SA"], age: ["TOTAL"], unit: ["PC_ACT"], sex: ["T"], geo: ["DE", "FR", "IT", "ES"] });
})();
