"""Relatório em PDF da simulação de Monte Carlo do 2º turno de 2026 (site/relatorio/).

Reimplementa em Python o mesmo algoritmo do simulador da página site/segundo-turno/ (funções rodar() e
gruposUF() do HTML), com o mesmo gerador pseudoaleatório (mulberry32, semente 20261025). Com isso, os
números do relatório saem dos mesmos sorteios que a página faz no navegador.

Etapas:
  1. lê transferencia.json, votos.json (1º turno de 2026 por município) e pesquisas.json;
  2. roda as configurações do relatório (padrão, sensibilidade ao erro, um ano de referência por vez);
  3. confere os resultados com os números publicados na página (tolerância: 0,1 p.p. na mediana, 1 p.p. nas chances);
  4. desenha as figuras estáticas (SVG, texto convertido em curvas) em site/relatorio/fig/;
  5. preenche as tabelas marcadas em site/relatorio/index.html (<!-- gerado:NOME --> ... <!-- /gerado:NOME -->);
  6. gera o PDF com o Chrome sem cabeça, se ele estiver instalado.

Uso:  python pipeline/relatorio_simulacao.py [--sem-pdf]
"""
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from comum import DADOS, REGIAO, SITE

DIR = SITE / "relatorio"
FIG = DIR / "fig"
FONTES_ORIGEM = SITE.parents[1] / "relatorio" / "fontes"
PDF = DIR / "simulacao-segundo-turno-2026.pdf"

PESOS_PADRAO = {"2014": 15, "2018": 35, "2022": 50}
N = 20000
SEMENTE = 20261025

# Números publicados na página do simulador com as escolhas-padrão (fração dos válidos do 22 e chance do 22).
PAGINA = {
    "padrao": {"mediana": 0.527, "q05": 0.502, "q95": 0.548, "p22": 0.96},
    "erro2": {"mediana": 0.526, "q05": 0.491, "q95": 0.561, "p22": 0.89},
    "erro3": {"mediana": 0.526, "q05": 0.475, "q95": 0.577, "p22": 0.80},
    "ano2014": {"mediana": 0.510},
    "ano2018": {"mediana": 0.528},
    "ano2022": {"mediana": 0.530},
}

COR = {"13": "#e34948", "22": "#2a78d6", "tinta": "#15181a", "tinta2": "#4a504c", "fraco": "#7d837d",
       "linha": "#dcdfd7", "linha2": "#c3c7be", "acento": "#0f5a61", "fundo": "#ffffff"}


# ----------------------------------------------------------------------------------------------------------
# Gerador pseudoaleatório idêntico ao da página (mulberry32 + Box-Muller)
# ----------------------------------------------------------------------------------------------------------
M32 = 0xFFFFFFFF


def _imul(a, b):
    return (a * b) & M32


class Mulberry32:
    def __init__(self, semente):
        self.a = semente & M32

    def __call__(self):
        self.a = (self.a + 0x6D2B79F5) & M32
        a = self.a
        t = _imul(a ^ (a >> 15), 1 | a)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & M32) ^ t
        return ((t ^ (t >> 14)) & M32) / 4294967296


def normal(r):
    u = 0.0
    while u == 0:
        u = r()
    v = 0.0
    while v == 0:
        v = r()
    return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * v)


# ----------------------------------------------------------------------------------------------------------
# Dados
# ----------------------------------------------------------------------------------------------------------
def carregar():
    T = json.loads((DADOS / "transferencia.json").read_text(encoding="utf-8"))
    B = json.loads((DADOS / "votos.json").read_text(encoding="utf-8"))
    P = json.loads((DADOS / "pesquisas.json").read_text(encoding="utf-8"))
    C = B["candidatos"]
    M = B["municipios"]
    uf = {}
    for i in range(len(M["cod"])):
        d = uf.setdefault(M["uf"][i], {"aptos": 0, "comp": 0, "v": [0] * len(C)})
        d["aptos"] += M["aptos"][i]
        d["comp"] += M["comp"][i]
        for k, x in enumerate(M["pres"][i]):
            d["v"][k] += x or 0
    return T, C, uf, P


def classif_padrao(T, C):
    return {c["n"]: T["classif2026"].get(c["n"], "OD") for c in C if c["n"] not in ("95", "96")}


def grupos_uf(T, C, d, classif):
    g = {"E": 0, "D": 0, "OE": 0, "OC": 0, "OD": 0, "BN": 0, "AB": d["aptos"] - d["comp"]}
    for k, c in enumerate(C):
        if c["n"] in ("95", "96"):
            g["BN"] += d["v"][k]
        else:
            g[classif[c["n"]]] += d["v"][k]
    return [g[x] for x in T["g1"]]


def sigma_hist(T):
    v = T["validacao"]
    return math.sqrt(sum(x["erroPP"] ** 2 for x in v) / len(v)) / 100


def quantil(a, p):
    """Mesmo quantil do d3 (interpolação linear, R-7) em vetor já ordenado."""
    return float(np.quantile(a, p, method="linear"))


def rodar(T, C, UF, cfg):
    """Uma rodada de Monte Carlo, na mesma ordem de sorteios da função rodar(cfg) da página.
    Implementa o caso usado no relatório: sem incerteza extra (Dirichlet) e sem mudança de comparecimento."""
    assert not cfg.get("extra") and not cfg.get("comp"), "o relatório usa extra = 0 e comp = 0"
    pesos = cfg["pesos"]
    anos = [a for a in pesos if pesos[a] > 0]
    tot = sum(pesos[a] for a in anos)
    r = Mulberry32(SEMENTE)
    ufs = list(UF)
    regioes = T["regioes"]
    # Sem mudança de comparecimento o resultado é linear nos grupos: somar os estados de cada região antes de
    # aplicar a matriz dá o mesmo total que aplicar estado a estado.
    Greg = {reg: np.zeros(len(T["g1"])) for reg in regioes}
    for u in ufs:
        Greg[REGIAO[u]] += np.array(grupos_uf(T, C, UF[u], cfg["classif"]), dtype=float)
    draws = {a: {reg: np.array(T["anos"][a]["regioes"][reg]["draws"]) for reg in regioes} for a in T["anos"]}
    sigma = cfg["sigma"]
    nac = np.empty(cfg["N"])
    ano_s = []
    for s in range(cfg["N"]):
        x, ano = r() * tot, anos[0]
        for a in anos:
            if x < pesos[a]:
                ano = a
                break
            x -= pesos[a]
        ano_s.append(ano)
        E = D = 0.0
        for reg in regioes:
            R = T["anos"][ano]["regioes"][reg]
            base = draws[ano][reg][math.floor(r() * len(R["draws"]))].copy()
            for k in range(base.shape[0]):
                if R["ok"][k]:
                    continue
                pares = [(a, reg, pesos[a]) for a in anos if T["anos"][a]["regioes"][reg]["ok"][k]]
                if not pares:
                    pares = [(a, g, pesos[a] * T["anos"][a]["regioes"][g]["parte"][k])
                             for a in anos for g in regioes if T["anos"][a]["regioes"][g]["ok"][k]]
                if not pares:
                    base[k] = R["outros"]
                    continue
                tp = sum(p[2] for p in pares)
                y, esc = r() * tp, pares[0]
                for p in pares:
                    if y < p[2]:
                        esc = p
                        break
                    y -= p[2]
                d2 = draws[esc[0]][esc[1]]
                base[k] = d2[math.floor(r() * len(d2))][k]
            yv = Greg[reg] @ base
            E += yv[0]
            D += yv[1]
        choque = normal(r) * sigma if sigma else 0.0
        nac[s] = D / (E + D) + choque
    nac.sort()
    return {"nac": nac, "p22": float((nac > 0.5).mean()), "mediana": quantil(nac, 0.5),
            "q05": quantil(nac, 0.05), "q95": quantil(nac, 0.95), "anos": ano_s}


def configs(T, C):
    base = {"pesos": dict(PESOS_PADRAO), "sigma": sigma_hist(T), "classif": classif_padrao(T, C), "N": N}
    return {
        "padrao": base,
        "erro2": {**base, "sigma": 0.02},
        "erro3": {**base, "sigma": 0.03},
        "ano2014": {**base, "pesos": {"2014": 100}},
        "ano2018": {**base, "pesos": {"2018": 100}},
        "ano2022": {**base, "pesos": {"2022": 100}},
    }


def conferir(res):
    print("\nConferência Python x página (fatia do 22 nos válidos; chance = 22 passa de 50%)")
    print(f"{'config':9} {'med py':>8} {'med pág':>8} {'dif pp':>7}   {'q05/q95 py':>14}   {'p22 py':>7} {'p22 pág':>7} {'dif pp':>7}")
    ok = True
    for k, ref in PAGINA.items():
        R = res[k]
        dm = (R["mediana"] - ref["mediana"]) * 100
        linha = f"{k:9} {R['mediana']*100:8.2f} {ref['mediana']*100:8.1f} {dm:+7.2f}   {R['q05']*100:6.2f}–{R['q95']*100:5.2f}"
        # a página arredonda para 0,1 p.p.: a diferença de arredondamento cabe em 0,05 + 0,1
        ok &= abs(dm) <= 0.1 + 0.05
        if "p22" in ref:
            dp = (R["p22"] - ref["p22"]) * 100
            linha += f"   {R['p22']*100:7.2f} {ref['p22']*100:7.0f} {dp:+7.2f}"
            ok &= abs(dp) <= 1 + 0.5
        print(linha)
    print("conferência:", "OK" if ok else "DIVERGENTE")
    return ok




# ----------------------------------------------------------------------------------------------------------
# Pesquisas: média recente, erros históricos e a faixa "média ± erro típico"
# ----------------------------------------------------------------------------------------------------------
PRIMEIRA_REF_PESQ = 11  # numeração das referências das pesquisas em index.html (1 a 10 são dados e métodos)
Z90 = 1.6449  # quantil de 95% da normal: ± Z90 · σ cobre 90%


def resumo_pesquisas(P):
    L = P["segundoTurno2026"]
    rec = [p for p in L if (p.get("divulgacao") or "") >= "2026-10-18"]
    v = np.array([p["v22"] for p in rec])
    res = P["resultados"]
    erros = []
    for e in P["erros"]:
        r = res[e["eleicao"]]
        dois_real = r["v22"] / (r["v13"] + r["v22"]) * 100
        e22 = e["v22"] - r["v22"]
        e13 = None if e["v13"] is None else e["v13"] - r["v13"]
        # erro na disputa a dois: fatia do 22 entre 13 + 22 na pesquisa menos a mesma fatia no resultado
        d2 = None if e["v13"] is None else e["v22"] / (e["v13"] + e["v22"]) * 100 - dois_real
        erros.append({**e, "e22": e22, "e13": e13, "d2": d2})
    base = [e["d2"] for e in erros if e["eleicao"] in ("1t2026", "2t2022")]
    rms = math.sqrt(sum(x * x for x in base) / len(base))
    vies = {el: float(np.mean([e["d2"] for e in erros if e["eleicao"] == el])) for el in ("1t2026", "2t2022")}
    media = float(v.mean())
    return {"L": L, "rec": rec, "media": media, "min": float(v.min()), "max": float(v.max()), "n": len(rec),
            "erros": erros, "rms": rms, "nbase": len(base), "vies": vies,
            "faixa": (media - Z90 * rms, media + Z90 * rms)}


# ----------------------------------------------------------------------------------------------------------
# Formatação
# ----------------------------------------------------------------------------------------------------------
def nf(x, d=1):
    s = f"{abs(x):,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if x < 0 and round(abs(x), d) > 0 else "") + s


def sinal(x, d=1):
    return ("+" if round(x, d) > 0 else "") + nf(x, d)


def pc(x, d=1):
    return nf(x * 100, d) + "%"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def mil(x):
    return f"{int(round(x)):,}".replace(",", ".")


# ----------------------------------------------------------------------------------------------------------
# Figuras (matplotlib, SVG com o texto em curvas; uma versão larga para o PDF e telas grandes e uma estreita)
# ----------------------------------------------------------------------------------------------------------
def preparar_mpl():
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    for f in sorted((DIR / "fontes").glob("*.ttf")):
        font_manager.fontManager.addfont(str(f))
    matplotlib.rcParams.update({
        "font.family": ["Public Sans", "DejaVu Sans"], "font.size": 8.5, "svg.fonttype": "path", "svg.hashsalt": "eleicaoemnumeros",
        "axes.edgecolor": COR["linha2"], "axes.labelcolor": COR["tinta2"], "axes.linewidth": 0.8,
        "xtick.color": COR["fraco"], "ytick.color": COR["fraco"], "xtick.labelcolor": COR["tinta2"],
        "ytick.labelcolor": COR["tinta2"], "xtick.major.size": 0, "ytick.major.size": 0,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    })
    import matplotlib.pyplot as plt
    return plt


def salvar(fig, nome):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / nome, format="svg", metadata={"Date": None, "Creator": None})
    import matplotlib.pyplot as plt
    plt.close(fig)


def fmt_pct_eixo(ax, eixo="x", d=0):
    from matplotlib.ticker import FuncFormatter
    f = FuncFormatter(lambda v, _: nf(v, d) + "%")
    (ax.xaxis if eixo == "x" else ax.yaxis).set_major_formatter(f)


def fig_distribuicao(plt, R, estreita):
    tam = 9.5 if estreita else 8.5
    fig, ax = plt.subplots(figsize=(4.3, 3.5) if estreita else (7.0, 2.9), layout="constrained")
    nac = R["nac"] * 100
    lo, hi, passo = 44.0, 61.0, 0.25
    bordas = np.arange(lo, hi + passo / 2, passo)
    cont, _ = np.histogram(nac, bins=bordas)
    meio = (bordas[:-1] + bordas[1:]) / 2
    cores = [COR["22"] if m > 50 else COR["13"] for m in meio]
    ax.bar(meio, cont, width=passo, color=cores, edgecolor="white", linewidth=0.5)
    topo = cont.max()
    ax.set_ylim(0, topo * 1.42)
    ax.set_xlim(44.5, 60.5) if not estreita else ax.set_xlim(45.5, 59.5)
    ax.axvline(50, color=COR["tinta"], lw=1.1, ymax=1 / 1.42 * 1.12)
    ax.text(50, topo * 1.15, "50%", ha="center", va="bottom", fontsize=tam, color=COR["tinta"], fontweight=600)
    med, q05, q95 = R["mediana"] * 100, R["q05"] * 100, R["q95"] * 100
    ax.axvline(med, color=COR["tinta"], lw=0.9, ls=(0, (4, 3)), ymax=1 / 1.42 * 1.02)
    # colchete da faixa de 90%
    yb = topo * 1.3
    ax.plot([q05, q05, q95, q95], [yb - topo * 0.05, yb, yb, yb - topo * 0.05], color=COR["tinta2"], lw=0.9)
    ax.text((q05 + q95) / 2, yb + topo * 0.03, f"90% das simulações: {nf(q05)}% a {nf(q95)}%  ·  mediana {nf(med)}%",
            ha="center", va="bottom", fontsize=tam - (1 if estreita else 0), color=COR["tinta"])
    p22 = R["p22"]
    ax.text(49.6, topo * 0.55, f"13 com mais\nvotos: {pc(1 - p22, 0)}", ha="right", va="center", fontsize=tam, color=COR["13"], fontweight=600)
    ax.text(q95 + 0.6, topo * 0.55, f"22 com mais\nvotos: {pc(p22, 0)}", ha="left", va="center", fontsize=tam, color=COR["22"], fontweight=600)
    ax.set_yticks([])
    ax.set_xticks(range(46 if estreita else 45, 60 if estreita else 61, 2 if estreita else 1))
    fmt_pct_eixo(ax)
    ax.tick_params(labelsize=tam)
    ax.set_xlabel("fatia do 22 nos válidos (a do 13 é o complemento)" if estreita else
                  "fatia do 22 nos votos válidos do 2º turno simulado (a do 13 é o complemento)", fontsize=tam - (0.5 if estreita else 0))
    salvar(fig, f"fig1-distribuicao{'-estreita' if estreita else ''}.svg")


def _intervalos(ax, linhas, tam, xlim, rotulo_dir=True):
    """linhas: [(rótulo, q05, med, q95, texto_dir)] em %. O trecho abaixo de 50% fica vermelho (13), o acima, azul (22)."""
    n = len(linhas)
    for i, (rot, a, m, b, txt) in enumerate(linhas):
        y = n - 1 - i
        if a is not None:
            if a < 50:
                ax.plot([a, min(b, 50)], [y, y], color=COR["13"], lw=5, solid_capstyle="butt")
            if b > 50:
                ax.plot([max(a, 50), b], [y, y], color=COR["22"], lw=5, solid_capstyle="butt")
            ax.text(a - 0.25, y, nf(a), ha="right", va="center", fontsize=tam - 1, color=COR["tinta2"])
            ax.text(b + 0.25, y, nf(b), ha="left", va="center", fontsize=tam - 1, color=COR["tinta2"])
        if m is not None:
            ax.plot([m], [y], "o", ms=6.5, mfc="white", mec=COR["tinta"], mew=1.4, zorder=5)
        if rotulo_dir and txt:
            ax.text(xlim[1] + 0.3, y, txt, ha="left", va="center", fontsize=tam - 0.5, color=COR["tinta"])
    ax.axvline(50, color=COR["tinta"], lw=1, zorder=0)
    ax.set_yticks(range(n))
    ax.set_yticklabels([l[0] for l in linhas][::-1], fontsize=tam)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_xlim(*xlim)
    ax.grid(axis="x", color=COR["linha"], lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", labelsize=tam)
    fmt_pct_eixo(ax)


def fig_sensibilidade(plt, res, sig, estreita):
    tam = 9.5 if estreita else 8.5
    linhas = []
    nomes = [("padrao", f"Padrão (erro ±{nf(sig * 100)})"), ("erro2", "Erro ±2 pontos"), ("erro3", "Erro ±3 pontos"),
             ("ano2014", "Só 2014"), ("ano2018", "Só 2018"), ("ano2022", "Só 2022")]
    for k, rot in nomes:
        R = res[k]
        linhas.append((rot, R["q05"] * 100, R["mediana"] * 100, R["q95"] * 100, f"22 > 50%: {pc(R['p22'], 0)}"))
    fig, ax = plt.subplots(figsize=(4.3, 3.6) if estreita else (7.0, 2.7), layout="constrained")
    xlim = (46, 59) if estreita else (46, 59)
    _intervalos(ax, linhas, tam, xlim, rotulo_dir=not estreita)
    if estreita:
        for i, (_, _, _, _, txt) in enumerate(linhas):
            ax.text(xlim[0] + 0.2, len(linhas) - 1 - i + 0.33, txt, ha="left", va="center", fontsize=tam - 1.5, color=COR["fraco"])
    ax.set_xlabel("fatia do 22: faixa de 90% e mediana (○)" if estreita else "fatia do 22 nos votos válidos: faixa de 90% e mediana (○)", fontsize=tam)
    salvar(fig, f"fig2-sensibilidade{'-estreita' if estreita else ''}.svg")


def fig_pesquisas(plt, PS, R, estreita):
    import datetime as dt
    import matplotlib.dates as mdates
    tam = 9.5 if estreita else 8.5
    fig, ax = plt.subplots(figsize=(4.3, 4.0) if estreita else (7.0, 3.4), layout="constrained")
    dia = lambda iso: dt.date(int(iso[:4]), int(iso[5:7]), int(iso[8:10]))
    x0, x1 = dt.date(2026, 10, 6), dt.date(2026, 10, 26)
    # faixas da simulação
    for cor, a, b, m in [(COR["22"], R["q05"], R["q95"], R["mediana"]), (COR["13"], 1 - R["q95"], 1 - R["q05"], 1 - R["mediana"])]:
        ax.axhspan(a * 100, b * 100, color=cor, alpha=0.12, lw=0)
        ax.axhline(m * 100, color=cor, lw=1, ls=(0, (5, 4)), alpha=0.9)
    ax.axhline(50, color=COR["linha2"], lw=1.2)
    ax.axvline(dt.date(2026, 10, 25), color=COR["linha2"], lw=1, ls=(0, (2, 3)))
    ax.text(dt.date(2026, 10, 25) - dt.timedelta(hours=8), 55.6, "2º turno", ha="right", va="top", fontsize=tam - 1, color=COR["fraco"])
    # média móvel de 7 dias (por data do fim do campo), a partir de 3 pesquisas na janela
    L = PS["L"]
    fins = sorted({dia(p["fim"]) for p in L})
    dias = [fins[0] + dt.timedelta(days=i) for i in range((fins[-1] - fins[0]).days + 1)]
    med = []
    for d in dias:
        j = [p["v22"] for p in L if d - dt.timedelta(days=7) < dia(p["fim"]) <= d]
        if len(j) >= 3:
            med.append((d, float(np.mean(j))))
    md = [m[0] for m in med]
    ax.plot(md, [m[1] for m in med], color=COR["22"], lw=1.8)
    ax.plot(md, [100 - m[1] for m in med], color=COR["13"], lw=1.8)
    # pontos (mesmo dia lado a lado)
    por_dia = {}
    for p in L:
        por_dia.setdefault(p["fim"], []).append(p)
    for f, grupo in por_dia.items():
        for k, p in enumerate(grupo):
            x = dia(f) + dt.timedelta(hours=(k - (len(grupo) - 1) / 2) * 7)
            conv = p["base"] != "válidos"
            for v, cor in [(p["v13"], COR["13"]), (p["v22"], COR["22"])]:
                ax.plot([x], [v], "o", ms=6, mfc="white" if conv else cor, mec=cor if conv else "white", mew=1.4 if conv else 0.8, zorder=4)
    ax.set_ylim(44, 56)
    ax.set_xlim(x0, x1)
    ax.set_yticks(range(44, 57, 2))
    fmt_pct_eixo(ax, "y")
    ax.grid(axis="y", color=COR["linha"], lw=0.6)
    ax.set_axisbelow(True)
    ticks = [dt.date(2026, 10, d) for d in ([7, 11, 15, 19, 23] if estreita else [7, 9, 11, 13, 15, 17, 19, 21, 23, 25])]
    ax.set_xticks(ticks)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%-d/10"))
    ax.tick_params(labelsize=tam)
    if not estreita:
        ax.text(x1 + dt.timedelta(hours=10), R["mediana"] * 100, f"22: simulação\n{pc(R['mediana'])} (mediana)", fontsize=tam - 0.5, color=COR["22"], va="center", fontweight=600)
        ax.text(x1 + dt.timedelta(hours=10), (1 - R["mediana"]) * 100, f"13: simulação\n{pc(1 - R['mediana'])} (mediana)", fontsize=tam - 0.5, color=COR["13"], va="center", fontweight=600)
    ax.set_ylabel("% dos votos válidos", fontsize=tam)
    salvar(fig, f"fig3-pesquisas{'-estreita' if estreita else ''}.svg")


def fig_comparacao(plt, PS, res, sig, estreita):
    tam = 9.5 if estreita else 8.5
    R0, R3 = res["padrao"], res["erro3"]
    a, b = PS["faixa"]
    m = PS["media"]
    linhas = [
        (f"Simulação, erro ±{nf(sig * 100)}", R0["q05"] * 100, R0["mediana"] * 100, R0["q95"] * 100, "faixa de 90%"),
        ("Simulação, erro ±3", R3["q05"] * 100, R3["mediana"] * 100, R3["q95"] * 100, "faixa de 90%"),
        (f"Pesquisas de 18 a 21/10", PS["min"], m, PS["max"], f"menor e maior; média {nf(m)}%"),
        ("Média ± erro típico", a, m, b, f"média ± {nf(Z90, 3)} × {nf(PS['rms'], 2)}"),
        ("Média sem o viés do 1º t. 2026", None, m - PS["vies"]["1t2026"], None, f"{nf(m)} {sinal(-PS['vies']['1t2026'])}"),
        ("Média sem o viés do 2º t. 2022", None, m - PS["vies"]["2t2022"], None, f"{nf(m)} {sinal(-PS['vies']['2t2022'])}"),
    ]
    fig, ax = plt.subplots(figsize=(4.3, 3.8) if estreita else (7.0, 2.8), layout="constrained")
    xlim = (45, 59)
    _intervalos(ax, linhas, tam, xlim, rotulo_dir=not estreita)
    for i, l in enumerate(linhas):
        if l[1] is None:
            y = len(linhas) - 1 - i
            ax.text(l[2] + 0.35, y, nf(l[2]), ha="left", va="center", fontsize=tam - 1, color=COR["tinta2"])
    if estreita:
        for i, l in enumerate(linhas):
            ax.text(xlim[0] + 0.2, len(linhas) - 1 - i + 0.33, l[4], ha="left", va="center", fontsize=tam - 1.5, color=COR["fraco"])
    ax.set_xlabel("fatia do 22 nos votos válidos (%)", fontsize=tam)
    salvar(fig, f"fig4-comparacao{'-estreita' if estreita else ''}.svg")


# ----------------------------------------------------------------------------------------------------------
# Tabelas (HTML inserido entre os marcadores de site/relatorio/index.html)
# ----------------------------------------------------------------------------------------------------------
def media_nacional(T, ano):
    A = T["anos"][ano]
    linhas = []
    for k in range(len(T["g1"])):
        s, w, peso = np.zeros(4), 0.0, 0.0
        for r in T["regioes"]:
            R = A["regioes"][r]
            n = sum(R["totalReal"]) * R["parte"][k]
            s += np.array(R["media"][k]) * n
            w += n
            peso += R["peso"][k] * n
        linhas.append((s / w, peso / w))
    return linhas


def tab_grupos2026(T, C, UF):
    cl = classif_padrao(T, C)
    G = np.zeros(7)
    for u in UF:
        G += np.array(grupos_uf(T, C, UF[u], cl), dtype=float)
    aptos = sum(d["aptos"] for d in UF.values())
    validos = G[:5].sum()
    tot = {c["n"]: sum(UF[u]["v"][k] for u in UF) for k, c in enumerate(C)}
    nome = lambda c: c["nome"].replace("ESCRITOR ", "").replace("VETERINÁRIO ", "").title().replace("Flavio", "Flávio")
    quem = {}
    for c in sorted(C, key=lambda c: -tot[c["n"]]):
        if c["n"] in ("95", "96"):
            continue
        quem.setdefault(cl[c["n"]], []).append(f"{nome(c)} ({c['n']})")
    quem["BN"], quem["AB"] = ["votos em branco e nulos"], ["eleitores aptos que não votaram"]
    corpo = ""
    for g, x in zip(T["g1"], G):
        lista = quem.get(g, [])
        txt = ", ".join(lista[:4]) + (f" e mais {len(lista) - 4}" if len(lista) > 4 else "")
        corpo += (f"<tr><td><b>{g}</b></td><td>{esc(T['nomesG1'][g])}<br><small>{esc(txt)}</small></td>"
                  f"<td class=\"r\">{mil(x)}</td><td class=\"r\">{pc(x / aptos)}</td>"
                  f"<td class=\"r\">{pc(x / validos) if g in ('E', 'D', 'OE', 'OC', 'OD') else '—'}</td></tr>")
    corpo += f"<tr class=\"total\"><td></td><td>Total de eleitores aptos</td><td class=\"r\">{mil(aptos)}</td><td class=\"r\">100,0%</td><td></td></tr>"
    return ("<table class=\"dados\"><thead><tr><th>Grupo</th><th>Quem está no grupo</th><th class=\"r\">Eleitores</th>"
            "<th class=\"r\">% dos aptos</th><th class=\"r\">% dos válidos</th></tr></thead><tbody>" + corpo + "</tbody></table>")


def tab_matrizes(T):
    corpo = ""
    for ano in ["2014", "2018", "2022"]:
        cl = T["classif"][ano]
        quem = {}
        for c in cl.values():
            quem.setdefault(c["grupo"], []).append(c["nome"])
        corpo += f"<tr class=\"grupo\"><th colspan=\"5\">{ano}</th></tr>"
        for g, (v, peso) in zip(T["g1"], media_nacional(T, ano)):
            q = quem.get(g, [])
            q = ", ".join(q[:3]) + (" e outros" if len(q) > 3 else "")
            celulas = "".join(f"<td class=\"r heat\" style=\"--v:{round(x * 100)}\">{nf(x * 100, 0)}</td>" for x in v)
            corpo += (f"<tr><td>{esc(T['nomesG1'][g])}{' *' if peso < 0.9 else ''}"
                      f"{f'<br><small>{esc(q)}</small>' if q else ''}</td>{celulas}</tr>")
    cab = "".join(f"<th class=\"r\">{esc(T['nomesG2'][d])}</th>" for d in T["g2"])
    return f"<table class=\"dados matriz\"><thead><tr><th>Grupo no 1º turno</th>{cab}</tr></thead><tbody>{corpo}</tbody></table>"


def tab_validacao(T):
    corpo = "".join(
        f"<tr><td>{v['treino']}</td><td>{v['teste']}</td><td class=\"r\">{pc(v['previstoE'])}</td><td class=\"r\">{pc(v['realE'])}</td>"
        f"<td class=\"r\"><b>{sinal(v['erroPP'], 2)}</b></td><td class=\"r\">{pc(v['previstoComp'])}</td><td class=\"r\">{pc(v['realComp'])}</td></tr>"
        for v in T["validacao"])
    s = sigma_hist(T) * 100
    corpo += f"<tr class=\"total\"><td colspan=\"4\">Raiz da média dos quadrados dos erros</td><td class=\"r\"><b>{nf(s, 2)}</b></td><td colspan=\"2\"></td></tr>"
    return ("<table class=\"dados\"><thead><tr><th>Migração de</th><th>Aplicada a</th><th class=\"r\">Esquerda prevista</th>"
            "<th class=\"r\">Esquerda real</th><th class=\"r\">Erro (p.p.)</th><th class=\"r\">Compar. previsto</th><th class=\"r\">Compar. real</th></tr></thead>"
            "<tbody>" + corpo + "</tbody></table>")


def tab_sensibilidade(res, sig):
    nomes = [("padrao", f"±{nf(sig * 100)} ponto (erro dos testes)", "15 / 35 / 50"), ("erro2", "±2 pontos", "15 / 35 / 50"),
             ("erro3", "±3 pontos", "15 / 35 / 50"), ("ano2014", f"±{nf(sig * 100)} ponto", "só 2014"),
             ("ano2018", f"±{nf(sig * 100)} ponto", "só 2018"), ("ano2022", f"±{nf(sig * 100)} ponto", "só 2022")]
    corpo = ""
    for k, rot, pesos in nomes:
        R = res[k]
        corpo += (f"<tr{' class=\"destaque\"' if k == 'padrao' else ''}><td>{pesos}</td><td>{rot}</td><td class=\"r\">{pc(1 - R['mediana'])}</td>"
                  f"<td class=\"r\">{pc(R['mediana'])}</td><td class=\"r\">{pc(R['q05'])} a {pc(R['q95'])}</td>"
                  f"<td class=\"r\">{pc(1 - R['p22'], 0)}</td><td class=\"r\">{pc(R['p22'], 0)}</td></tr>")
    return ("<table class=\"dados sens\"><thead><tr><th>Pesos 2014/18/22</th><th>Erro somado</th><th class=\"r\">Mediana 13</th><th class=\"r\">Mediana 22</th>"
            "<th class=\"r\">Faixa de 90% do 22</th><th class=\"r\">13 &gt; 50%</th><th class=\"r\">22 &gt; 50%</th></tr></thead><tbody>" + corpo + "</tbody></table>")


def tab_erros(P, PS):
    E = PS["erros"]
    insts = []
    for e in E:
        if e["instituto"] not in insts:
            insts.append(e["instituto"])
    acha = lambda i, el: next((e for e in E if e["instituto"] == i and e["eleicao"] == el), None)
    insts.sort(key=lambda i: (acha(i, "1t2026") is None, i))
    cel = lambda e, k: f"<td class=\"r\">{sinal(e[k])}</td>" if e and e.get(k) is not None else "<td class=\"r vazio\">—</td>"
    corpo = ""
    for i in insts:
        a, b, c = acha(i, "1t2026"), acha(i, "1t2022"), acha(i, "2t2022")
        corpo += f"<tr><td>{esc(i)}</td>{cel(a, 'e13')}{cel(a, 'e22')}{cel(a, 'd2')}{cel(b, 'e22')}{cel(c, 'e13')}{cel(c, 'e22')}</tr>"
    res = P["resultados"]
    media = lambda el, k: np.mean([e[k] for e in E if e["eleicao"] == el and e.get(k) is not None])
    corpo += (f"<tr class=\"total\"><td>Média</td><td class=\"r\">{sinal(media('1t2026', 'e13'))}</td><td class=\"r\">{sinal(media('1t2026', 'e22'))}</td>"
              f"<td class=\"r\">{sinal(media('1t2026', 'd2'))}</td><td class=\"r\">{sinal(media('1t2022', 'e22'))}</td>"
              f"<td class=\"r\">{sinal(media('2t2022', 'e13'))}</td><td class=\"r\">{sinal(media('2t2022', 'e22'))}</td></tr>")
    r26 = res["1t2026"]
    corpo += (f"<tr class=\"nota\"><td>Resultado (% dos válidos)</td><td class=\"r\">{nf(r26['v13'])}</td><td class=\"r\">{nf(r26['v22'])}</td>"
              f"<td class=\"r\">{nf(r26['v22'] / (r26['v13'] + r26['v22']) * 100)}</td><td class=\"r\">{nf(res['1t2022']['v22'])}</td>"
              f"<td class=\"r\">{nf(res['2t2022']['v13'])}</td><td class=\"r\">{nf(res['2t2022']['v22'])}</td></tr>")
    return ("<table class=\"dados\"><thead><tr class=\"grupo\"><th></th><th colspan=\"3\" class=\"r\">1º turno de 2026</th><th class=\"r\">1º turno 2022</th>"
            "<th colspan=\"2\" class=\"r\">2º turno de 2022</th></tr><tr><th>Instituto</th><th class=\"r\">13</th><th class=\"r\">22</th>"
            "<th class=\"r\">22 a dois</th><th class=\"r\">22</th><th class=\"r\">13</th><th class=\"r\">22</th></tr></thead><tbody>" + corpo + "</tbody></table>")


def tab_conta(PS, res):
    R0, R3 = res["padrao"], res["erro3"]
    a, b = PS["faixa"]
    d = [e["d2"] for e in PS["erros"] if e["eleicao"] in ("1t2026", "2t2022")]
    linhas = [
        ("1", f"Média das {PS['n']} pesquisas divulgadas de 18 a 21/10 (fatia do 22 nos válidos)", f"{nf(PS['media'], 2)}%"),
        ("2", f"Erro típico das pesquisas de véspera: raiz da média dos quadrados dos {PS['nbase']} erros na disputa a dois "
              "(1º turno de 2026 e 2º turno de 2022)", f"{nf(PS['rms'], 2)} p.p."),
        ("3", f"Faixa de 90% supondo erro normal: média ± {nf(Z90, 3)} × erro típico", f"{nf(a)}% a {nf(b)}%"),
        ("4", "Faixa de 90% da simulação, escolhas-padrão", f"{pc(R0['q05'])} a {pc(R0['q95'])}"),
        ("5", "Faixa de 90% da simulação com erro de ±3 pontos", f"{pc(R3['q05'])} a {pc(R3['q95'])}"),
        ("6", "Média das pesquisas corrigida pelo viés médio do 1º turno de 2026 na disputa a dois", f"{nf(PS['media'] - PS['vies']['1t2026'])}%"),
        ("7", "Média das pesquisas corrigida pelo viés médio do 2º turno de 2022", f"{nf(PS['media'] - PS['vies']['2t2022'])}%"),
    ]
    corpo = "".join(f"<tr><td>{n}</td><td>{t}</td><td class=\"r nowrap\"><b>{v}</b></td></tr>" for n, t, v in linhas)
    return f"<table class=\"dados conta\"><thead><tr><th></th><th>Passo</th><th class=\"r\">Valor</th></tr></thead><tbody>{corpo}</tbody></table>"


def lista_fontes(P):
    fontes = {}
    rot = {"1t2026": "1º turno de 2026", "1t2022": "1º turno de 2022", "2t2022": "2º turno de 2022"}
    for p in P["segundoTurno2026"]:
        for f in p["fontes"]:
            fontes.setdefault(f["url"], [f["nome"], []])[1].append(
                "2º turno de 2026" if "compilação" in f["nome"] else f"{p['instituto']}, 2º turno de 2026")
    for e in P["erros"]:
        fontes.setdefault(e["fonte"]["url"], [e["fonte"]["nome"], []])[1].append(f"{e['instituto']}, {rot[e['eleicao']]}")
    itens = []
    for i, (url, (nome, usos)) in enumerate(fontes.items()):
        u = list(dict.fromkeys(usos))
        itens.append(f"<li id=\"ref-{PRIMEIRA_REF_PESQ + i}\">{esc(nome)} ({esc('; '.join(u))}). <a href=\"{esc(url)}\">{esc(url)}</a></li>")
    return f"<ol class=\"refs\" start=\"{PRIMEIRA_REF_PESQ}\">" + "".join(itens) + "</ol>"


def tab_conferencia(res):
    nomes = {"padrao": "Padrão", "erro2": "Erro ±2", "erro3": "Erro ±3", "ano2014": "Só 2014", "ano2018": "Só 2018", "ano2022": "Só 2022"}
    corpo = ""
    for k, ref in PAGINA.items():
        R = res[k]
        corpo += (f"<tr><td>{nomes[k]}</td><td class=\"r\">{nf(ref['mediana'] * 100)}%</td><td class=\"r\">{nf(R['mediana'] * 100, 2)}%</td>"
                  + (f"<td class=\"r\">{nf(ref['p22'] * 100, 0)}%</td><td class=\"r\">{nf(R['p22'] * 100, 2)}%</td>" if "p22" in ref else "<td class=\"r vazio\">—</td><td class=\"r\">" + nf(R['p22'] * 100, 2) + "%</td>")
                  + "</tr>")
    return ("<table class=\"dados\"><thead><tr><th>Configuração</th><th class=\"r\">Mediana do 22 (página)</th><th class=\"r\">Mediana do 22 (Python)</th>"
            "<th class=\"r\">22 &gt; 50% (página)</th><th class=\"r\">22 &gt; 50% (Python)</th></tr></thead><tbody>" + corpo + "</tbody></table>")


def preencher(html, nome, conteudo):
    padrao = re.compile(rf"(<!-- gerado:{nome} -->)(.*?)(<!-- /gerado:{nome} -->)", re.S)
    if not padrao.search(html):
        raise KeyError(f"marcador {nome} ausente em index.html")
    return padrao.sub(lambda m: m.group(1) + conteudo + m.group(3), html)


# ----------------------------------------------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------------------------------------------
def gerar_pdf():
    chrome = next((c for c in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser") if shutil.which(c)), None)
    if not chrome:
        print("Chrome não encontrado; PDF não gerado.")
        return
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=10000",
           f"--print-to-pdf={PDF}", (DIR / "index.html").as_uri()]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"{PDF.relative_to(SITE.parent)}: {PDF.stat().st_size // 1024} KB")


def main():
    T, C, UF, P = carregar()
    (DIR / "fontes").mkdir(parents=True, exist_ok=True)
    for f in ["PublicSans-400.ttf", "PublicSans-600.ttf", "PublicSans-700.ttf", "Archivo-Cond-700.ttf"]:
        if not (DIR / "fontes" / f).exists() and (FONTES_ORIGEM / f).exists():
            shutil.copy(FONTES_ORIGEM / f, DIR / "fontes" / f)
    cf = configs(T, C)
    res = {k: rodar(T, C, UF, c) for k, c in cf.items()}
    if not conferir(res):
        sys.exit("Os números do Python não batem com os da página; confira antes de publicar.")
    sig = sigma_hist(T)
    PS = resumo_pesquisas(P)
    print(f"\nPesquisas de 18 a 21/10: n = {PS['n']}, média do 22 = {PS['media']:.2f} (de {PS['min']} a {PS['max']})")
    print(f"Erro típico (RMS, disputa a dois, 1t2026 + 2t2022, n = {PS['nbase']}): {PS['rms']:.2f} p.p.; "
          f"viés médio 1t2026 = {PS['vies']['1t2026']:+.2f}, 2t2022 = {PS['vies']['2t2022']:+.2f}")
    print(f"Faixa média ± {Z90}·σ: {PS['faixa'][0]:.2f} a {PS['faixa'][1]:.2f}")
    plt = preparar_mpl()
    for estreita in (False, True):
        fig_distribuicao(plt, res["padrao"], estreita)
        fig_sensibilidade(plt, res, sig, estreita)
        fig_pesquisas(plt, PS, res["padrao"], estreita)
        fig_comparacao(plt, PS, res, sig, estreita)
    html = (DIR / "index.html").read_text(encoding="utf-8")
    for nome, conteudo in [("grupos2026", tab_grupos2026(T, C, UF)), ("matrizes", tab_matrizes(T)), ("validacao", tab_validacao(T)),
                           ("sensibilidade", tab_sensibilidade(res, sig)), ("erros", tab_erros(P, PS)), ("conta", tab_conta(PS, res)),
                           ("fontes", lista_fontes(P)), ("conferencia", tab_conferencia(res))]:
        html = preencher(html, nome, conteudo)
    (DIR / "index.html").write_text(html, encoding="utf-8")
    print("site/relatorio/index.html: tabelas atualizadas")
    if "--sem-pdf" not in sys.argv:
        gerar_pdf()


if __name__ == "__main__":
    main()
