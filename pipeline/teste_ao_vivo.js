// Testa o modelo do painel ao vivo numa noite gravada (replay): projeta a cada 10 minutos e compara com o final.
// Uso: node pipeline/teste_ao_vivo.js [replay_2022|sim_2026]
// Saída: site/ao-vivo/dados/teste_{nome}.json (para o gráfico do painel) e um resumo no terminal.
"use strict";
const fs = require("fs");
const path = require("path");
const Modelo = require("../site/ao-vivo/modelo.js");

const DADOS = path.join(__dirname, "..", "site", "ao-vivo", "dados");
const nome = process.argv[2] || "replay_2022";
const R = JSON.parse(fs.readFileSync(path.join(DADOS, `${nome}.json`), "utf8"));
const prior = JSON.parse(fs.readFileSync(path.join(DADOS, R.prior), "utf8"));
const P = Modelo.preparar(prior);
const obs = Modelo.vazio(P);
const final = R.final.b;
const hora = k => { const t = new Date(new Date(R.inicio).getTime() + k * R.passoMin * 60000); return t.toTimeString().slice(0, 5); };

const linhas = [];
let i = 0;
const t0 = Date.now();
for (let k = 0; k <= R.passos; k += 5) {
  i = Modelo.aplicarEventos(obs, R.eventos, i, k);
  const p = Modelo.projetar(P, obs, { sims: 2000, semente: k + 1 });
  linhas.push({ k, hora: hora(k), apurado: +p.apurado.toFixed(4), atual: p.atual == null ? null : +p.atual.toFixed(5),
    mediana: +p.mediana.toFixed(5), q05: +p.q05.toFixed(5), q95: +p.q95.toFixed(5), pB: +p.pB.toFixed(4) });
  if (p.apurado >= 0.9999) break;
}
const ms = (Date.now() - t0) / linhas.length;
const dentro = linhas.filter(l => l.q05 <= final && final <= l.q95).length;
console.log(`${R.nome}: final ${(final * 100).toFixed(2)}% | ${linhas.length} projeções, ${ms.toFixed(0)} ms cada | final dentro do intervalo de 90% em ${dentro}/${linhas.length}`);
for (const l of linhas.filter((_, j) => j % 3 === 0 || j < 8))
  console.log(`${l.hora}  apurado ${(l.apurado * 100).toFixed(1).padStart(5)}%  contagem ${l.atual == null ? "   —  " : (l.atual * 100).toFixed(2)}%  projeção ${(l.mediana * 100).toFixed(2)}% [${(l.q05 * 100).toFixed(2)}–${(l.q95 * 100).toFixed(2)}]  P(B vence) ${(l.pB * 100).toFixed(0)}%`);
fs.writeFileSync(path.join(DADOS, `teste_${nome}.json`), JSON.stringify({ nome: R.nome, final, linhas, dentro, total: linhas.length }));
