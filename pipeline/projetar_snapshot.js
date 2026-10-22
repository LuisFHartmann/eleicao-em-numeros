// Acrescenta ao snapshot do coletor a projeção do momento (mesmo modelo do navegador), para o histórico da noite.
// Uso: node pipeline/projetar_snapshot.js site/ao-vivo/dados/vivo_6258.json
"use strict";
const fs = require("fs");
const path = require("path");
const Modelo = require("../site/ao-vivo/modelo.js");

const arq = process.argv[2];
const snap = JSON.parse(fs.readFileSync(arq, "utf8"));
const prior = JSON.parse(fs.readFileSync(path.join(path.dirname(arq), "prior_2026.json"), "utf8"));
const P = Modelo.preparar(prior);
const obs = Object.fromEntries(["st", "est", "a", "b"].map(k => [k, Float64Array.from(snap.obs[k])]));
const p = Modelo.projetar(P, obs, { sims: 4000, semente: (snap.hist?.length ?? 0) + 11 });
const t = Date.parse(snap.atualizado);
const ponto = { t, apurado: snap.apurado ?? p.apurado, atual: p.atual, mediana: p.mediana, q05: p.q05, q95: p.q95, q25: p.q25, q75: p.q75, pB: p.pB };
snap.hist = (snap.hist ?? []).filter(h => h.t !== t).concat([ponto]);
fs.writeFileSync(arq, JSON.stringify(snap));
console.log(`projeção: ${(p.mediana * 100).toFixed(2)}% [${(p.q05 * 100).toFixed(2)}–${(p.q95 * 100).toFixed(2)}], P(B) ${(p.pB * 100).toFixed(0)}%`);
