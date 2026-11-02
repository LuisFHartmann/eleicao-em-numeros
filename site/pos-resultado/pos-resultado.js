// Página "Depois do resultado": lê dados/pos_resultado.json (gerado por pipeline/estudo_modelos.py) e desenha.
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const pct = (v, d = 1) => (v * 100).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }) + "%";
const pts = (v, d = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const mi = v => (v / 1e6).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " mi";
const tip = document.getElementById("tip");
const mostrar = (ev, html) => { tip.innerHTML = html; tip.style.opacity = 1; tip.style.left = Math.min(ev.clientX + 14, innerWidth - 310) + "px"; tip.style.top = (ev.clientY + 14) + "px"; };
const esconder = () => { tip.style.opacity = 0; };
const largura = el => Math.max(300, el.clientWidth || 640);
let D;

function eixoX(g, x, y0, fmt, n = 6) {
  x.ticks(n).forEach(t => {
    g.append("line").attr("class", "gridline").attr("x1", x(t)).attr("x2", x(t)).attr("y1", 0).attr("y2", y0);
    g.append("text").attr("x", x(t)).attr("y", y0 + 15).attr("text-anchor", "middle").text(fmt(t));
  });
}

// 1. previsões contra o resultado ------------------------------------------------------------
function previsoes() {
  const el = document.getElementById("ch-previsoes"), P = D.previsoes, W = largura(el), estreito = W < 560;
  const ml = estreito ? 8 : 250, mr = 16, rh = estreito ? 54 : 34, mt = 6, H = mt + P.length * rh + 28;
  const vals = P.flatMap(p => [p.p22, p.lo ?? p.p22, p.hi ?? p.p22]).concat(D.resultado.p22);
  const x = d3.scaleLinear().domain([Math.min(.44, d3.min(vals) - .005), Math.max(.56, d3.max(vals) + .005)]).range([ml, W - mr]);
  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "Previsões da fatia do 22 contra o resultado");
  const g = svg.append("g");
  eixoX(g, x, H - 24, v => pct(v, 0), estreito ? 4 : 7);
  g.append("line").attr("x1", x(.5)).attr("x2", x(.5)).attr("y1", 0).attr("y2", H - 24).attr("stroke", css("--line-strong")).attr("stroke-dasharray", "3 3");
  P.forEach((p, i) => {
    const y = mt + i * rh + (estreito ? 30 : rh / 2);
    const rot = g.append("text").attr("x", estreito ? ml : ml - 10).attr("y", estreito ? y - 22 : y).attr("dy", ".35em").attr("text-anchor", estreito ? "start" : "end").attr("class", "forte").text(p.rotulo);
    if (p.lo != null) g.append("line").attr("x1", x(p.lo)).attr("x2", x(p.hi)).attr("y1", y).attr("y2", y).attr("stroke", css("--c22")).attr("stroke-width", 6).attr("stroke-opacity", .28).attr("stroke-linecap", "round");
    g.append("circle").attr("cx", x(p.p22)).attr("cy", y).attr("r", 6).attr("fill", css("--c22")).attr("stroke", css("--surface")).attr("stroke-width", 2)
      .on("mousemove", ev => mostrar(ev, `<b>${p.rotulo}</b><br>22: ${pct(p.p22)} · 13: ${pct(1 - p.p22)}${p.lo != null ? `<br><span class="m">faixa: ${pct(p.lo)} a ${pct(p.hi)}</span>` : ""}${p.nota ? `<br><span class="m">${p.nota}</span>` : ""}`)).on("mouseleave", esconder);
    if (estreito) g.append("text").attr("x", x(p.p22) + (p.p22 > .5 ? -10 : 10)).attr("y", y).attr("dy", ".35em").attr("text-anchor", p.p22 > .5 ? "end" : "start").text(pct(p.p22));
    else g.append("text").attr("x", x(p.p22)).attr("y", y - 10).attr("text-anchor", "middle").text(pct(p.p22));
    void rot;
  });
  g.append("line").attr("x1", x(D.resultado.p22)).attr("x2", x(D.resultado.p22)).attr("y1", 0).attr("y2", H - 24).attr("stroke", css("--ink")).attr("stroke-width", 2);
  g.append("text").attr("x", x(D.resultado.p22) + 4).attr("y", H - 30).attr("class", "forte").text(`resultado ${pct(D.resultado.p22)}`);
  el.replaceChildren(svg.node());
  document.getElementById("cap-previsoes").textContent = `Fatia do 22 entre os votos válidos. Resultado oficial: 13 com ${pct(D.resultado.p13, 2)} e 22 com ${pct(D.resultado.p22, 2)}. À esquerda de 50%, vence o 13.`;
}

// 2. projeção ao vivo -------------------------------------------------------------------------
function aovivo() {
  const el = document.getElementById("ch-aovivo"), A = D.aovivo.filter(a => a.a >= .01), W = largura(el), H = Math.round(Math.min(360, Math.max(240, W * .5)));
  const ml = 44, mr = 14, mt = 10, mb = 34;
  const x = d3.scaleLinear().domain([0, 1]).range([ml, W - mr]), y = d3.scaleLinear().domain([.44, .56]).range([H - mb, mt]).clamp(true);
  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "Projeção do 22 durante a apuração");
  y.ticks(6).forEach(t => { svg.append("line").attr("class", "gridline").attr("x1", ml).attr("x2", W - mr).attr("y1", y(t)).attr("y2", y(t)); svg.append("text").attr("x", ml - 6).attr("y", y(t)).attr("dy", ".35em").attr("text-anchor", "end").text(pct(t, 0)); });
  [0, .25, .5, .75, 1].forEach(t => svg.append("text").attr("x", x(t)).attr("y", H - mb + 16).attr("text-anchor", "middle").text(pct(t, 0)));
  svg.append("text").attr("x", W - mr).attr("y", H - 4).attr("text-anchor", "end").text("seções apuradas →");
  svg.append("path").attr("d", d3.area().x(d => x(d.a)).y0(d => y(d.lo)).y1(d => y(d.hi)).curve(d3.curveStepAfter)(A)).attr("fill", css("--c22")).attr("opacity", .18);
  svg.append("path").attr("d", d3.line().x(d => x(d.a)).y(d => y(d.m)).curve(d3.curveStepAfter)(A)).attr("fill", "none").attr("stroke", css("--c22")).attr("stroke-width", 2.2);
  svg.append("path").attr("d", d3.line().defined(d => d.c >= .44 && d.c <= .56).x(d => x(d.a)).y(d => y(d.c))(A)).attr("fill", "none").attr("stroke", css("--neutro")).attr("stroke-width", 1.4);
  svg.append("line").attr("x1", ml).attr("x2", W - mr).attr("y1", y(D.resultado.p22)).attr("y2", y(D.resultado.p22)).attr("stroke", css("--ink")).attr("stroke-dasharray", "5 4");
  svg.append("line").attr("x1", ml).attr("x2", W - mr).attr("y1", y(D.inicial.p22)).attr("y2", y(D.inicial.p22)).attr("stroke", css("--c22")).attr("stroke-dasharray", "2 3").attr("opacity", .7);
  svg.append("text").attr("x", W - mr).attr("y", y(D.inicial.p22) - 5).attr("text-anchor", "end").text(`projeção inicial ${pct(D.inicial.p22)}`);
  const alvo = svg.append("line").attr("y1", mt).attr("y2", H - mb).attr("stroke", css("--ink")).attr("opacity", 0);
  svg.append("rect").attr("x", ml).attr("y", mt).attr("width", W - ml - mr).attr("height", H - mt - mb).attr("fill", "transparent")
    .on("mousemove", ev => { const [mx] = d3.pointer(ev); const a = x.invert(mx); const d = A[Math.max(0, d3.bisector(v => v.a).right(A, a) - 1)];
      alvo.attr("x1", x(d.a)).attr("x2", x(d.a)).attr("opacity", .4);
      mostrar(ev, `<b>${pct(d.a)} apurado</b><br>projeção do 22: ${pct(d.m)} <span class="m">(${pct(d.lo)} a ${pct(d.hi)})</span><br>contagem: 22 com ${pct(d.c)}`); })
    .on("mouseleave", () => { esconder(); alvo.attr("opacity", 0); });
  el.replaceChildren(svg.node());
  document.getElementById("cap-aovivo").textContent = D.textos.aovivo;
}

// 3. onde a simulação errou --------------------------------------------------------------------
let modoErro = "margem";
function erro() {
  const el = document.getElementById("ch-erro"), F = D.fluxos, W = largura(el), estreito = W < 560;
  const grupos = F.grupos.map((g, i) => ({ g, i, nome: F.nomes[g] }));
  const leg = document.getElementById("leg-erro");
  if (modoErro === "margem") {
    leg.innerHTML = `<span><i class="sw" style="background:var(--c13)"></i>o grupo deu mais ao 13 do que o modelo supunha</span><span><i class="sw" style="background:var(--c22)"></i>deu mais ao 22</span>`;
    const lin = grupos.map(d => ({ ...d, v: (F.estimado[d.i][0] - F.estimado[d.i][1]) - (F.esperado[d.i][0] - F.esperado[d.i][1]),
      lo: (F.q05[d.i][0] - F.q95[d.i][1]) - (F.esperado[d.i][0] - F.esperado[d.i][1]), hi: (F.q95[d.i][0] - F.q05[d.i][1]) - (F.esperado[d.i][0] - F.esperado[d.i][1]) }))
      .sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
    const tot = d3.sum(lin, d => d.v); lin.push({ nome: "Total", v: tot, total: true });
    const ml = estreito ? 120 : 190, mr = 64, rh = 30, H = lin.length * rh + 30;
    const ext = d3.extent([0, ...lin.flatMap(d => [d.v, d.lo ?? d.v, d.hi ?? d.v])]);
    const x = d3.scaleLinear().domain(ext).nice().range([ml, W - mr]);
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "Erro na margem por grupo de eleitores");
    eixoX(svg, x, H - 24, v => (v / 1e6).toLocaleString("pt-BR") + " mi", estreito ? 4 : 6);
    svg.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", 0).attr("y2", H - 24).attr("stroke", css("--ink")).attr("opacity", .5);
    lin.forEach((d, k) => {
      const y = k * rh + 6;
      if (d.total) svg.append("line").attr("x1", 0).attr("x2", W).attr("y1", y - 3).attr("y2", y - 3).attr("stroke", css("--line-strong"));
      svg.append("rect").attr("x", Math.min(x(0), x(d.v))).attr("y", y + 3).attr("width", Math.abs(x(d.v) - x(0))).attr("height", rh - 12).attr("rx", 3)
        .attr("fill", css(d.v >= 0 ? "--c13" : "--c22")).attr("opacity", d.total ? 1 : .85)
        .on("mousemove", ev => mostrar(ev, `<b>${d.nome}</b><br>${d.v >= 0 ? "a mais para o 13" : "a mais para o 22"}: ${mi(Math.abs(d.v))}${d.lo != null ? `<br><span class="m">faixa de 90%: ${pts(d.lo / 1e6, 2)} a ${pts(d.hi / 1e6, 2)} mi</span>` : ""}`)).on("mouseleave", esconder);
      if (d.lo != null) svg.append("line").attr("x1", x(d.lo)).attr("x2", x(d.hi)).attr("y1", y + rh / 2 - 3).attr("y2", y + rh / 2 - 3).attr("stroke", css("--ink")).attr("opacity", .55).attr("stroke-width", 1.5);
      svg.append("text").attr("x", ml - 10).attr("y", y + rh / 2 - 3).attr("dy", ".35em").attr("text-anchor", "end").attr("class", d.total ? "forte" : null).text(d.nome);
      svg.append("text").attr("x", Math.max(x(d.v), x(0), x(d.hi ?? d.v)) + 6).attr("y", y + rh / 2 - 3).attr("dy", ".35em").attr("class", "forte").text(pts(d.v / 1e6, 2));
    });
    el.replaceChildren(svg.node());
    document.getElementById("cap-erro").textContent = D.textos.erro_margem;
  } else {
    leg.innerHTML = `<span><i class="sw" style="background:var(--c13)"></i>13</span><span><i class="sw" style="background:var(--c22)"></i>22</span><span><i class="sw" style="background:var(--neutro)"></i>branco ou nulo</span><span><i class="sw" style="background:var(--line-strong)"></i>não foi votar</span><span class="nota">barra de cima: o que o modelo supunha · de baixo: o que aconteceu</span>`;
    const cores = ["--c13", "--c22", "--neutro", "--line-strong"], nomesD = ["13", "22", "branco ou nulo", "não foi votar"];
    const ml = estreito ? 110 : 170, mr = 10, bh = 13, gap = 3, rh = bh * 2 + gap + 14, H = grupos.length * rh + 26;
    const x = d3.scaleLinear().domain([0, 1]).range([ml, W - mr]);
    const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "Para onde cada grupo foi: suposto e estimado");
    eixoX(svg, x, H - 22, v => pct(v, 0), 5);
    grupos.forEach((d, k) => {
      const y0 = k * rh + 4;
      [["esperado", "suposto pelo modelo"], ["estimado", "estimado com os boletins"]].forEach(([chave, rot], j) => {
        const linha = F[chave][d.i], s = d3.sum(linha); let acc = 0;
        linha.forEach((v, c) => {
          const f = v / s;
          svg.append("rect").attr("x", x(acc)).attr("y", y0 + j * (bh + gap)).attr("width", Math.max(0, x(acc + f) - x(acc) - 1)).attr("height", bh)
            .attr("fill", css(cores[c])).attr("opacity", j === 0 ? .45 : 1)
            .on("mousemove", ev => mostrar(ev, `<b>${d.nome}</b> · ${rot}<br>${nomesD[c]}: ${pct(f)} <span class="m">(${mi(v)})</span>`)).on("mouseleave", esconder);
          acc += f;
        });
      });
      svg.append("text").attr("x", ml - 8).attr("y", y0 + bh + gap / 2).attr("dy", ".35em").attr("text-anchor", "end").attr("class", "forte").text(d.nome);
    });
    el.replaceChildren(svg.node());
    document.getElementById("cap-erro").textContent = D.textos.erro_taxas;
  }
}

// 4. história: tabela, gráfico de resíduos e modelos ----------------------------------------------
function historia() {
  const H = D.historia;
  const cab = `<tr><th>Ano</th><th>Finalistas</th><th>Governo</th><th class="r">1º turno</th><th class="r">Previsão</th><th class="r">Resultado</th><th class="r">Erro</th><th class="r">Aprovação</th><th class="r">Rejeição</th></tr>`;
  const linhas = H.anos.map(a => `<tr${a.ano === 2026 ? ' class="destaque"' : ""}><td>${a.ano}</td><td>${a.nomes[0]} × ${a.nomes[1].replace("Flávio Bolsonaro", "Flávio")}</td><td>${a.governo === 1 ? a.nomes[0] : a.governo === -1 ? a.nomes[1] : "nenhum"}</td>`
    + `<td class="r">${pct(a.h2h)}</td><td class="r">${pct(a.base)}</td><td class="r"><b>${pct(a.real)}</b></td><td class="r">${pts((a.real - a.base) * 100)}</td>`
    + `<td class="r" title="${a.aprov ? `ótimo/bom ${a.aprov.ob}%, ruim/péssimo ${a.aprov.rp}%` : ""}">${a.aprov ? `${pts(a.aprov.ob - a.aprov.rp, 0)} <small>(${a.aprov.ob}/${a.aprov.rp})</small>` : "<small>—</small>"}</td><td class="r">${a.rej ? `${a.rej.E} / ${a.rej.D}` : "<small>—</small>"}</td></tr>`).join("");
  document.getElementById("tb-historia").innerHTML = `<thead>${cab}</thead><tbody>${linhas}</tbody>`;
  document.getElementById("nota-historia").innerHTML = D.textos.nota_historia;
  const sel = document.getElementById("sel-explica");
  sel.innerHTML = H.variaveis.map((v, i) => `<button data-i="${i}" aria-pressed="${i === 0}">${v.rotulo}</button>`).join("");
  sel.onclick = e => { const b = e.target.closest("button"); if (!b) return; [...sel.children].forEach(c => c.setAttribute("aria-pressed", c === b)); explica(+b.dataset.i); };
  explica(0);
  const M = D.modelos;
  document.getElementById("tb-modelos").innerHTML = `<thead><tr><th>Forma de prever</th><th class="r">Erro médio 2002–2022</th><th class="r">Maior erro</th><th class="r">Para 2026 (13 / 22)</th><th class="r">Erro em 2026</th></tr></thead><tbody>`
    + M.map(m => `<tr${m.destaque ? ' class="destaque"' : ""}><td><b>${m.nome}</b><br><small>${m.descricao}</small></td><td class="r">${m.mae != null ? m.mae.toLocaleString("pt-BR", { maximumFractionDigits: 1, minimumFractionDigits: 1 }) + " pt" : "—"}</td>`
      + `<td class="r">${m.max != null ? m.max.toLocaleString("pt-BR", { maximumFractionDigits: 1, minimumFractionDigits: 1 }) + " pt" : "—"}</td><td class="r">${m.p2026 != null ? `${pct(m.p2026)} / ${pct(1 - m.p2026)}` : "—"}</td>`
      + `<td class="r">${m.p2026 != null ? pts((m.p2026 - D.resultado.p13) * 100) + " pt" : "—"}</td></tr>`).join("") + "</tbody>";
  document.getElementById("nota-modelos").innerHTML = D.textos.nota_modelos;
}

function explica(i) {
  const el = document.getElementById("ch-explica"), v = D.historia.variaveis[i], pts_ = D.historia.anos.filter(a => a[v.chave] != null);
  const W = largura(el), H = Math.round(Math.min(340, Math.max(240, W * .52))), ml = 46, mr = 16, mt = 12, mb = 40;
  const xs = pts_.map(a => a[v.chave]), ys = pts_.map(a => (a.real - a.base) * 100 * (v.lado ? (a.governo || 0) : 1));
  const x = d3.scaleLinear().domain(d3.extent(xs.concat(v.dominio || []))).nice().range([ml, W - mr]);
  const y = d3.scaleLinear().domain(d3.extent(ys.concat([0, 2, -2]))).nice().range([H - mb, mt]);
  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "Erro da previsão contra " + v.rotulo);
  y.ticks(6).forEach(t => { svg.append("line").attr("class", "gridline").attr("x1", ml).attr("x2", W - mr).attr("y1", y(t)).attr("y2", y(t)); svg.append("text").attr("x", ml - 6).attr("y", y(t)).attr("dy", ".35em").attr("text-anchor", "end").text(pts(t, 0)); });
  (v.ticks || x.ticks(6)).forEach(t => svg.append("text").attr("x", x(t)).attr("y", H - mb + 16).attr("text-anchor", "middle").text(v.fmt ? v.fmt[String(t)] ?? t : pts(t, 0)));
  svg.append("line").attr("x1", ml).attr("x2", W - mr).attr("y1", y(0)).attr("y2", y(0)).attr("stroke", css("--ink")).attr("opacity", .45);
  svg.append("text").attr("x", W - mr).attr("y", H - 4).attr("text-anchor", "end").text(v.eixo + " →");
  svg.append("text").attr("x", ml + 4).attr("y", mt + 8).text(v.lado ? "↑ governo foi melhor que o previsto (pontos)" : "↑ esquerda foi melhor que o previsto (pontos)");
  if (v.reta) { const [a, b] = v.reta, [d0, d1] = x.domain(); svg.append("line").attr("x1", x(d0)).attr("x2", x(d1)).attr("y1", y(a + b * d0)).attr("y2", y(a + b * d1)).attr("stroke", css("--gov")).attr("stroke-dasharray", "6 4").attr("stroke-width", 1.6); }
  const desloc = xs.map((xv, k) => { if (!v.jitter) return 0; const mesmos = xs.map((z, j) => j).filter(j => xs[j] === xv); return (mesmos.indexOf(k) - (mesmos.length - 1) / 2) * 34; });
  pts_.forEach((a, k) => {
    const cx = x(xs[k]) + desloc[k], cy = y(ys[k]), novo = a.ano === 2026;
    svg.append("circle").attr("cx", cx).attr("cy", cy).attr("r", 7).attr("fill", css(novo ? "--accent" : "--gov")).attr("stroke", css("--surface")).attr("stroke-width", 2)
      .on("mousemove", ev => mostrar(ev, `<b>${a.ano}</b> · ${a.nomes[0]} × ${a.nomes[1]}<br>${v.rotulo}: ${v.fmt ? v.fmt[String(xs[k])] ?? xs[k] : pts(xs[k], 1)}<br>erro da previsão: ${pts(ys[k], 1)} pontos${novo ? '<br><span class="m">2026 não entra no ajuste</span>' : ""}`)).on("mouseleave", esconder);
    svg.append("text").attr("x", desloc[k] < 0 ? cx - 9 : cx + 9).attr("y", cy).attr("dy", ".35em").attr("text-anchor", desloc[k] < 0 ? "end" : "start").attr("class", "forte").text(a.ano);
  });
  el.replaceChildren(svg.node());
  document.getElementById("cap-explica").innerHTML = v.legenda;
}

// 5. governadores ---------------------------------------------------------------------------------
function governadores() {
  const el = document.getElementById("ch-gov"), G = D.governadores, W = largura(el), H = Math.round(Math.min(420, Math.max(280, W * .62)));
  const ml = 46, mr = 14, mt = 10, mb = 40;
  // ponto de vista do governador quando ele está na final; senão, do mais votado no 1º turno
  const P = G.disputas.map(d => { const inc = d.reel_a && !d.reel_b ? 1 : d.reel_b && !d.reel_a ? -1 : 0;
    return { ...d, inc, x: inc === -1 ? 1 - d.h2h1 : d.h2h1, y: inc === -1 ? 1 - d.fatia2 : d.fatia2, quem: inc === -1 ? d.b : d.a }; });
  const x = d3.scaleLinear().domain([.2, .85]).range([ml, W - mr]).clamp(true), y = d3.scaleLinear().domain([.2, .85]).range([H - mb, mt]).clamp(true);
  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "2º turnos de governador: 1º turno contra 2º turno");
  y.ticks(6).forEach(t => { svg.append("line").attr("class", "gridline").attr("x1", ml).attr("x2", W - mr).attr("y1", y(t)).attr("y2", y(t)); svg.append("text").attr("x", ml - 6).attr("y", y(t)).attr("dy", ".35em").attr("text-anchor", "end").text(pct(t, 0)); });
  x.ticks(6).forEach(t => svg.append("text").attr("x", x(t)).attr("y", H - mb + 16).attr("text-anchor", "middle").text(pct(t, 0)));
  svg.append("line").attr("x1", x(.2)).attr("x2", x(.85)).attr("y1", y(.2)).attr("y2", y(.85)).attr("stroke", css("--ink")).attr("opacity", .35).attr("stroke-dasharray", "4 4");
  svg.append("line").attr("x1", ml).attr("x2", W - mr).attr("y1", y(.5)).attr("y2", y(.5)).attr("stroke", css("--line-strong"));
  svg.append("text").attr("x", W - mr).attr("y", H - 4).attr("text-anchor", "end").text("fatia entre os dois finalistas no 1º turno →");
  svg.append("text").attr("x", ml + 4).attr("y", mt + 8).text("↑ fatia no 2º turno");
  for (const d of [...P].sort((a, b) => Math.abs(a.inc) - Math.abs(b.inc))) {
    svg.append("circle").attr("cx", x(d.x)).attr("cy", y(d.y)).attr("r", d.inc ? 5.5 : 4).attr("fill", css(d.inc ? "--gov" : "--neutro")).attr("fill-opacity", d.inc ? .9 : .5)
      .attr("stroke", css("--surface")).attr("stroke-width", 1)
      .on("mousemove", ev => mostrar(ev, `<b>${d.uf} ${d.ano}</b>: ${d.a} (${d.a_partido}) × ${d.b} (${d.b_partido})<br>${d.inc ? `governador tentando a reeleição: <b>${d.quem}</b>` : "sem governador na final"}<br>${d.quem}: ${pct(d.x)} entre os dois no 1º turno → ${pct(d.y)} no 2º`)).on("mouseleave", esconder);
  }
  el.replaceChildren(svg.node());
  document.getElementById("cap-gov").innerHTML = D.textos.governadores;
}

function tudo() { previsoes(); aovivo(); erro(); historia(); governadores(); }
fetch("../dados/pos_resultado.json", { cache: "no-cache" }).then(r => r.json()).then(d => {
  D = d;
  document.getElementById("atualizado").textContent = "Análise pós-resultado · atualizada em " + D.atualizado;
  document.getElementById("t-res").textContent = `${pct(D.resultado.p13, 2)} dos votos válidos contra ${pct(D.resultado.p22, 2)}`;
  document.getElementById("resumo-lista").innerHTML = D.resumo.map(s => `<li>${s}</li>`).join("");
  document.getElementById("licoes-texto").innerHTML = D.licoes.map(s => `<p>${s}</p>`).join("");
  const sf = document.getElementById("sel-fluxo");
  sf.onclick = e => { const b = e.target.closest("button"); if (!b) return; [...sf.children].forEach(c => c.setAttribute("aria-pressed", c === b)); modoErro = b.dataset.v; erro(); };
  tudo();
  let t; addEventListener("resize", () => { clearTimeout(t); t = setTimeout(tudo, 150); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", tudo);
});
