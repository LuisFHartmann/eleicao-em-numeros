/* Projeção do resultado final a partir da apuração parcial.
 *
 * Ideia: antes da eleição, cada município tem uma votação esperada no candidato B (p, entre os válidos) e um
 * número esperado de votos válidos por eleitor (vpe). Durante a apuração, a diferença entre o que chegou e o
 * esperado, em logit, é explicada por efeitos em camadas: Brasil, região, estado e município.
 *
 *   r_m = logit(fatia observada de B em m) − logit(p_m) = δ_Brasil + δ_região + δ_estado + ε_m
 *
 * Os efeitos têm prior normal com média 0 (o que se esperava) e são atualizados com todos os municípios que já
 * mandaram boletins (regressão bayesiana com peso pelo tamanho da amostra). Os votos que faltam em cada município
 * são projetados com esses efeitos, e um Monte Carlo sorteia os efeitos para dar o intervalo e a chance de vitória.
 * Os municípios que ainda não apuraram nada herdam o efeito do seu estado e da sua região, e é assim que o modelo
 * desconta o fato de os primeiros boletins virem de lugares que votam diferente.
 *
 * Ordem de chegada: os municípios que apuram primeiro não são uma amostra ao acaso dos outros (capitais e cidades
 * grandes chegam antes do interior, e votam diferente mesmo depois de descontado o 1º turno). Por isso o que falta
 * recebe um choque extra, comum ao país (vies.nacional) e a cada estado (vies.uf), que encolhe à medida que a
 * apuração avança: desvio = vies × √(fração do eleitorado ainda não apurada). Calibrado na noite real de 2022.
 *
 * Funciona no navegador (window.Modelo) e no Node (require), com o mesmo código.
 */
(function (raiz, fabrica) {
  if (typeof module === "object" && module.exports) module.exports = fabrica();
  else raiz.Modelo = fabrica();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const logit = p => { p = Math.min(1 - 1e-4, Math.max(1e-4, p)); return Math.log(p / (1 - p)); };
  const sig = z => 1 / (1 + Math.exp(-z));

  function rng(semente) { // mulberry32: reprodutível
    let a = semente >>> 0;
    return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  function normal(u) { // Box-Muller com um gerador uniforme
    let x = 0, y = 0;
    while (x === 0) x = u();
    y = u();
    return Math.sqrt(-2 * Math.log(x)) * Math.cos(2 * Math.PI * y);
  }

  /** Índices e logits pré-calculados a partir do prior (JSON gerado por pipeline/ao_vivo.py). */
  function preparar(prior) {
    const ufs = prior.ufs, regioes = prior.regioes;
    const iUF = Object.fromEntries(ufs.map((u, i) => [u, i]));
    const iReg = Object.fromEntries(regioes.map((r, i) => [r, i]));
    const M = prior.cod.length;
    const P = {
      prior, M, ufs, regioes, nU: ufs.length, nR: regioes.length,
      u: new Int16Array(M), r: new Int8Array(M), lp: new Float64Array(M), vpe: Float64Array.from(prior.vpe),
      te: Float64Array.from(prior.te), ts: Float64Array.from(prior.ts),
      chave: new Map(),
    };
    for (let m = 0; m < M; m++) {
      P.u[m] = iUF[prior.uf[m]];
      P.r[m] = iReg[prior.regiaoUF[prior.uf[m]]];
      P.lp[m] = logit(prior.p[m]);
      P.chave.set(`${prior.uf[m].toLowerCase()}${prior.cod[m]}`, m);
    }
    return P;
  }

  /** Observação vazia: tudo zerado. Campos acumulados por município. */
  function vazio(P) {
    return { st: new Float64Array(P.M), est: new Float64Array(P.M), a: new Float64Array(P.M), b: new Float64Array(P.M) };
  }

  function cholesky(A, n) { // A: Float64Array n*n simétrica positiva definida -> L (triangular inferior)
    const L = new Float64Array(n * n);
    for (let i = 0; i < n; i++) for (let j = 0; j <= i; j++) {
      let s = A[i * n + j];
      for (let k = 0; k < j; k++) s -= L[i * n + k] * L[j * n + k];
      L[i * n + j] = i === j ? Math.sqrt(Math.max(s, 1e-12)) : s / L[j * n + j];
    }
    return L;
  }
  const resolveL = (L, b, n) => { const x = new Float64Array(n); for (let i = 0; i < n; i++) { let s = b[i]; for (let k = 0; k < i; k++) s -= L[i * n + k] * x[k]; x[i] = s / L[i * n + i]; } return x; };
  const resolveLt = (L, b, n) => { const x = new Float64Array(n); for (let i = n - 1; i >= 0; i--) { let s = b[i]; for (let k = i + 1; k < n; k++) s -= L[k * n + i] * x[k]; x[i] = s / L[i * n + i]; } return x; };

  /**
   * obs: { st, est, a, b } por município (acumulados). Devolve a projeção.
   * opções: sims (nº de sorteios), semente, rho (quanto o que falta num município se parece com o que já chegou dele),
   *         kComp (votos que "valem" o prior de comparecimento em cada estado).
   */
  function projetar(P, obs, { sims = 2000, semente = 1, rho = 0.7, kComp = 20000, sigma = P.prior.sigma, vies = P.prior.vies } = {}) {
    const { M, nU, nR } = P, n = 1 + nR + nU;
    const s0 = sigma.nacional, sR = sigma.regiao, sU = sigma.uf, sM = sigma.municipio, sM2 = sM * sM;
    // 1) efeitos: regressão bayesiana com prior N(0, σ²)
    const A = new Float64Array(n * n), bv = new Float64Array(n);
    A[0] = 1 / (s0 * s0);
    for (let i = 0; i < nR; i++) A[(1 + i) * n + 1 + i] = 1 / (sR * sR);
    for (let i = 0; i < nU; i++) A[(1 + nR + i) * n + 1 + nR + i] = 1 / (sU * sU);
    const res = new Float64Array(M), vobs = new Float64Array(M), peso = new Float64Array(M), lista = [];
    const cU = new Float64Array(nU), espU = new Float64Array(nU);
    let ca = 0, cb = 0, st = 0, ts = 0, estT = 0, teT = 0;
    const estU = new Float64Array(nU), teU = new Float64Array(nU);
    for (let m = 0; m < M; m++) {
      const a = obs.a[m], b = obs.b[m], c = a + b;
      ca += a; cb += b; st += obs.st[m]; ts += P.ts[m];
      estU[P.u[m]] += obs.est[m]; teU[P.u[m]] += P.te[m]; estT += obs.est[m]; teT += P.te[m];
      if (c <= 0) continue;
      cU[P.u[m]] += c; espU[P.u[m]] += obs.est[m] * P.vpe[m];
      const s = (b + 0.5) / (c + 1);
      res[m] = logit(s) - P.lp[m];
      // acaso binomial + amostra de seções: o que já chegou é parte do município, e o esperado de cada seção varia
      // em torno do esperado do município. O tamanho da amostra é medido em eleitores (seções "equivalentes"):
      // os primeiros boletins costumam ser de aldeias, quilombos e comunidades pequenas, que votam diferente da sede.
      const nEq = Math.max(0.05, P.ts[m] * Math.min(1, obs.est[m] / P.te[m]));
      vobs[m] = 1 / (c * s * (1 - s)) + (sigma.secao ?? 0) ** 2 * Math.max(0, 1 / nEq - 1 / P.ts[m]);
      peso[m] = 1 / (sM2 + vobs[m]);
      lista.push(m);
    }
    // regressão robusta (pesos de Huber, 3 iterações): um município muito fora do padrão conta, mas com influência limitada
    const HUBER = 1.5;
    let L, mu, wr = Float64Array.from(peso);
    for (let it = 0; it < 3; it++) {
      A.fill(0); bv.fill(0);
      A[0] = 1 / (s0 * s0);
      for (let i = 0; i < nR; i++) A[(1 + i) * n + 1 + i] = 1 / (sR * sR);
      for (let i = 0; i < nU; i++) A[(1 + nR + i) * n + 1 + nR + i] = 1 / (sU * sU);
      for (const m of lista) {
        const w = wr[m], idx = [0, 1 + P.r[m], 1 + nR + P.u[m]];
        for (const i of idx) { bv[i] += w * res[m]; for (const j of idx) A[i * n + j] += w; }
      }
      L = cholesky(A, n);
      mu = resolveLt(L, resolveL(L, bv, n), n);
      if (it === 2) break;
      for (const m of lista) {
        const z = Math.abs(res[m] - mu[0] - mu[1 + P.r[m]] - mu[1 + nR + P.u[m]]) * Math.sqrt(peso[m]);
        wr[m] = peso[m] * (z > HUBER ? HUBER / z : 1);
      }
    }
    // 2) comparecimento: razão entre votos válidos que chegaram e o esperado para os eleitores já apurados, por estado
    const fU = Array.from(cU, (c, i) => (c + kComp) / (espU[i] + kComp));
    // 3) o que falta em cada município: votos válidos e ajuste próprio (só onde já chegou parte)
    const rest = [], R = [], base = [], eh = [], ed = [];
    let Rtot = 0;
    for (let m = 0; m < M; m++) {
      const falta = Math.max(0, P.te[m] - obs.est[m]);
      if (falta <= 0) continue;
      const Rm = falta * P.vpe[m] * fU[P.u[m]];
      if (Rm <= 0) continue;
      let e = 0, v = sM2;
      if (obs.a[m] + obs.b[m] > 0) {
        const k = sM2 / (sM2 + vobs[m]);
        e = rho * k * (res[m] - mu[0] - mu[1 + P.r[m]] - mu[1 + nR + P.u[m]]);
        v = sM2 * (1 - rho * k);
      }
      rest.push(m); R.push(Rm); base.push(P.lp[m] + e); eh.push(Math.sqrt(v)); Rtot += Rm;
    }
    // 4) Monte Carlo
    const u = rng(semente), out = new Float64Array(sims), validos = ca + cb + Rtot;
    const porUFb = new Float64Array(nU), porUFv = new Float64Array(nU);
    for (let k = 0; k < rest.length; k++) { const m = rest[k], z = base[k] + mu[0] + mu[1 + P.r[m]] + mu[1 + nR + P.u[m]]; porUFb[P.u[m]] += R[k] * sig(z); porUFv[P.u[m]] += R[k]; }
    const tN = (vies?.nacional ?? 0) * Math.sqrt(Math.max(0, 1 - estT / teT)), tU = Array.from(teU, (t, i) => (vies?.uf ?? 0) * Math.sqrt(Math.max(0, 1 - (t ? estU[i] / t : 0))));
    for (let s = 0; s < sims; s++) {
      const zz = new Float64Array(n);
      for (let i = 0; i < n; i++) zz[i] = normal(u);
      const th = resolveLt(L, zz, n);
      for (let i = 0; i < n; i++) th[i] += mu[i];
      th[0] += tN * normal(u);
      for (let i = 0; i < nU; i++) th[1 + nR + i] += tU[i] * normal(u);
      let tb = 0;
      for (let k = 0; k < rest.length; k++) {
        const m = rest[k];
        tb += R[k] * sig(base[k] + th[0] + th[1 + P.r[m]] + th[1 + nR + P.u[m]] + eh[k] * normal(u));
      }
      out[s] = (cb + tb) / validos;
    }
    out.sort();
    const q = p => out[Math.min(sims - 1, Math.max(0, Math.round(p * (sims - 1))))];
    let vence = 0;
    for (let s = 0; s < sims; s++) if (out[s] > 0.5) vence++;
    const ufs = P.ufs.map((uf, i) => {
      let a = 0, b = 0, sti = 0, tsi = 0;
      for (let m = 0; m < M; m++) if (P.u[m] === i) { a += obs.a[m]; b += obs.b[m]; sti += obs.st[m]; tsi += P.ts[m]; }
      return { uf, apurado: tsi ? sti / tsi : 0, atual: a + b ? b / (a + b) : null, projetado: (b + porUFb[i]) / (a + b + porUFv[i]), validosProj: a + b + porUFv[i] };
    });
    const regioes = P.regioes.map((r, i) => ({ regiao: r, efeito: mu[1 + i] }));
    return {
      apurado: ts ? st / ts : 0, contados: ca + cb, atual: ca + cb ? cb / (ca + cb) : null, validosProj: validos,
      mediana: q(0.5), q05: q(0.05), q25: q(0.25), q75: q(0.75), q95: q(0.95), pB: vence / sims,
      efeitoNacional: mu[0], efeitoNacionalSd: 1 / Math.sqrt(A[0]), regioes, ufs, amostras: out,
    };
  }

  /** Aplica um bloco de eventos (formato dos arquivos de replay) até o passo k (exclusivo). */
  function aplicarEventos(obs, ev, de, ate) {
    for (let i = de; i < ev.k.length && ev.k[i] < ate; i++) {
      const m = ev.m[i];
      obs.st[m] += ev.st[i]; obs.est[m] += ev.est[i]; obs.a[m] += ev.a[i]; obs.b[m] += ev.b[i];
    }
    let i = de;
    while (i < ev.k.length && ev.k[i] < ate) i++;
    return i;
  }

  return { preparar, vazio, projetar, aplicarEventos, logit, sig, rng };
});
