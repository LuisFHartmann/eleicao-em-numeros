"""Dados do painel ao vivo do 2º turno (site/ao-vivo/dados/).

  prior_2026.json     o que se espera de cada município ANTES da apuração: votação esperada no 22
                      (entre os válidos) e votos válidos esperados por eleitor, aplicando ao 1º turno de 2026
                      a transferência de votos estimada em 2014/2018/2022 (transferencia.json).
                      Inclui a curva esperada da apuração (na ordem de chegada do 1º turno) e a curva do 1º turno.
  replay_2022.json    a noite real do 2º turno de 2022, para testar o modelo: o prior é o que teríamos
                      tido na época (1º turno de 2022 + transferência de 2014 e 2018), e os eventos são
                      os boletins na hora em que chegaram.
  sim_2026.json       uma noite SIMULADA de 2026: votos sorteados em torno do esperado, com erros regionais,
                      estaduais, municipais e por seção; o resultado final fica na mediana do modelo (cenário central).
                      Os boletins chegam na hora em que chegaram no 1º turno.

Uso: python pipeline/ao_vivo.py
"""
from datetime import datetime, timedelta

import numpy as np
import polars as pl

from comum import DADOS, DATA, REGIAO, SITE, UFS, baixar_json, gravar_json

SAIDA = SITE / "ao-vivo" / "dados"
REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
PASSO_MIN = 2
G1 = ["E", "D", "OE", "OC", "OD", "BN", "AB"]
# incerteza a priori, em logit da fatia do 22 entre os válidos (o modelo do navegador usa os mesmos valores)
# medido em 2022 (resíduo do 2º turno em relação ao esperado): município 0,064, estado 0,046.
# secao = quanto o esperado das seções de um mesmo município varia entre si (0,34 em logit, 1º turno de 2026):
# uma contagem parcial, de poucas seções, é uma amostra pequena do município e pesa pouco.
SIGMA = dict(nacional=0.035, regiao=0.04, uf=0.05, municipio=0.07, secao=0.34)
RUIDO_SECAO_SIM = 0.05  # na noite simulada: desvio de cada seção em relação ao seu próprio esperado
# choque extra pela ordem de chegada (ver modelo.js), calibrado na noite de 2022 com pipeline/teste_ao_vivo.js
VIES = dict(nacional=0.045, uf=0.05)  # nacional + vies: largura inicial igual à do Monte Carlo do 2º turno (96%)
ZZ_1T = "https://resultados.tse.jus.br/oficial/ele2026/6257/dados/zz/zz-c0001-e006257-u.json"



def matrizes(pesos):
    import json
    tr = json.load(open(DADOS / "transferencia.json", encoding="utf-8"))
    tot = sum(pesos.values())
    return {r: sum(np.array(tr["anos"][a]["regioes"][r]["media"]) * w for a, w in pesos.items()) / tot for r in REGIOES}, tr


def aplicar(x, B):
    """x: (n, 7) eleitores por grupo no 1º turno; B: (7, 4). Devolve (n, 4): E, D, BN, AB esperados no 2º turno."""
    return x @ B


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def sig(z):
    return 1 / (1 + np.exp(-z))


# ---------------------------------------------------------------- 2026
def secoes_2026(classif):
    b = pl.concat([pl.read_parquet(DATA / f"bweb_{u}.parquet", columns=[
        "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO_PERGUNTA", "DT_BU_RECEBIDO", "NR_VOTAVEL", "QT_VOTOS",
        "QT_APTOS", "QT_COMPARECIMENTO"]) for u in UFS]).filter(pl.col("CD_CARGO_PERGUNTA") == "1")
    b = b.with_columns(pl.col("QT_VOTOS", "QT_APTOS", "QT_COMPARECIMENTO").cast(pl.Int64), mun=pl.col("CD_MUNICIPIO").str.zfill(5),
                       g=pl.when(pl.col("NR_VOTAVEL").is_in(["95", "96"])).then(pl.lit("BN"))
                       .otherwise(pl.col("NR_VOTAVEL").replace_strict(classif, default="OD")))
    s = b.group_by("SG_UF", "mun", "NR_ZONA", "NR_SECAO").agg(
        t=pl.col("DT_BU_RECEBIDO").first().str.to_datetime(), aptos=pl.col("QT_APTOS").first(), comp=pl.col("QT_COMPARECIMENTO").first(),
        v13=pl.col("QT_VOTOS").filter(pl.col("NR_VOTAVEL") == "13").sum(), v22=pl.col("QT_VOTOS").filter(pl.col("NR_VOTAVEL") == "22").sum(),
        **{g: pl.col("QT_VOTOS").filter(pl.col("g") == g).sum() for g in G1 if g != "AB"})
    return s.with_columns(AB=(pl.col("aptos") - pl.col("comp")).clip(0)).rename({"SG_UF": "uf"})


def prior_secoes(s, Bs):
    """Acrescenta a cada seção os valores esperados no 2º turno (e2, d2: votos no candidato E e D)."""
    x = s.select(G1).to_numpy().astype(float)
    reg = s["uf"].replace_strict(REGIAO).to_numpy()
    y = np.zeros((len(s), 4))
    for r in REGIOES:
        m = reg == r
        y[m] = aplicar(x[m], Bs[r])
    return s.with_columns(e2=pl.Series(y[:, 0]), d2=pl.Series(y[:, 1]))


def prior_municipios(s, nome, rotulos, extra=None):
    m = s.group_by("uf", "mun").agg(te=pl.col("aptos").sum(), ts=pl.len(), e2=pl.col("e2").sum(), d2=pl.col("d2").sum()).sort("uf", "mun")
    if extra is not None:
        m = pl.concat([m, extra], how="diagonal_relaxed")
    p = (m["d2"] / (m["e2"] + m["d2"])).to_numpy()
    vpe = ((m["e2"] + m["d2"]) / m["te"]).to_numpy()
    return dict(eleicao=nome, rotulos=rotulos, sigma=SIGMA, vies=VIES, regioes=REGIOES,
                ufs=sorted(m["uf"].unique().to_list()), regiaoUF={u: REGIAO.get(u, "Sudeste") for u in m["uf"].unique().to_list()},
                uf=m["uf"].to_list(), cod=m["mun"].to_list(), te=m["te"].to_list(), ts=m["ts"].to_list(),
                p=[round(float(v), 5) for v in p], vpe=[round(float(v), 5) for v in vpe],
                esperado=round(float(m["d2"].sum() / (m["e2"].sum() + m["d2"].sum())), 5))


def curva_por_q(t, num, den, pontos=200):
    o = np.argsort(t, kind="stable")
    cn, cd = np.cumsum(np.asarray(num, float)[o]), np.cumsum(np.asarray(den, float)[o])
    q = np.linspace(0, 1, pontos + 1)[1:]
    i = np.clip((q * len(o)).astype(int) - 1, 0, len(o) - 1)
    return dict(q=[round(float(v), 4) for v in q], b=[round(float(v), 5) for v in cn[i] / cd[i]])


def eventos(s, inicio, col_b, col_a, col_est):
    """Boletins agregados por (município, passo de 2 min): incrementos de seções, eleitores e votos."""
    s = s.drop_nulls("t").with_columns(k=((pl.col("t") - inicio).dt.total_seconds() // (60 * PASSO_MIN)).clip(0).cast(pl.Int32))
    e = s.group_by("uf", "mun", "k").agg(st=pl.len(), est=pl.col(col_est).sum(), a=pl.col(col_a).sum(), b=pl.col(col_b).sum()).sort("k")
    return e


def empacotar_eventos(e, prior):
    idx = {(u, c): i for i, (u, c) in enumerate(zip(prior["uf"], prior["cod"]))}
    e = e.with_columns(m=pl.struct("uf", "mun").map_elements(lambda r: idx.get((r["uf"], r["mun"]), -1), return_dtype=pl.Int32)).filter(pl.col("m") >= 0)
    return dict(m=e["m"].to_list(), k=e["k"].to_list(), st=e["st"].to_list(), est=[int(v) for v in e["est"]],
                a=[int(v) for v in e["a"]], b=[int(v) for v in e["b"]]), int(e["k"].max()) + 1


def exterior_2026(Bs):
    """Votos no exterior (zz) do 1º turno, pela API do TSE, como um 'município' a mais."""
    try:
        u = baixar_json(ZZ_1T)
    except Exception as err:
        print("exterior indisponível:", err)
        return None
    num = lambda x: int(str(x).replace(".", "") or 0)
    vap = {c["n"]: num(c["vap"]) for a in u["carg"][0]["agr"] for p in a["par"] for c in p["cand"]}
    classif = {"13": "E", "22": "D"}
    x = np.zeros(7)
    for n, v in vap.items():
        x[G1.index(classif.get(n, "OD" if n not in ("80", "21", "16", "29") else "OE"))] += v
    x[G1.index("BN")] = num(u["v"]["vb"]) + num(u["v"]["tvn"])
    te, c = num(u["e"]["te"]), num(u["e"]["c"])
    x[G1.index("AB")] = te - c
    y = aplicar(x[None, :], Bs["Sudeste"])[0]
    return pl.DataFrame(dict(uf=["ZZ"], mun=["ZZ"], te=[te], ts=[num(u["s"]["ts"])], e2=[y[0]], d2=[y[1]]))


def main_2026(rng):
    Bs, tr = matrizes({"2014": 15, "2018": 35, "2022": 50})
    s = prior_secoes(secoes_2026(tr["classif2026"]), Bs)
    prior = prior_municipios(s, "2º turno de 2026", dict(a="13", b="22", nomeA="Lula", nomeB="Flávio Bolsonaro"), exterior_2026(Bs))
    t = s["t"].to_numpy()
    prior["curvaEsperada"] = curva_por_q(t, s["d2"], s["e2"] + s["d2"])
    prior["curva1T"] = curva_por_q(t, s["v22"], s["v13"] + s["v22"])
    # no relógio: mesma hora de chegada do 1º turno (a curva esperada supõe que os boletins chegam no mesmo ritmo)
    inicio = datetime(2026, 10, 4, 17, 0)
    prior["curvaEsperadaHora"] = curva_hora(s, "d2", "e2", inicio)
    prior["curva1THora"] = curva_hora(s, "v22", "v13", inicio)
    gravar_json(prior, SAIDA / "prior_2026.json")
    print("2026 esperado:", prior["esperado"])

    # ---- noite simulada: votos sorteados em torno do esperado, com erros por região, estado, município e seção;
    # o erro nacional é ajustado para o resultado final cair na mediana da projeção inicial (o cenário central do modelo)
    q = quantis_iniciais(SAIDA / "prior_2026.json")
    sim, d0 = simular_noite(s, rng, q["q50"])
    ev, n = empacotar_eventos(eventos(sim, datetime(2026, 10, 25, 17, 0), "b", "a", "aptos"), prior)
    final = float(sim["b"].sum() / (sim["a"].sum() + sim["b"].sum()))
    gravar_json(dict(nome="Simulação 2026 (cenário central do modelo)",
                     descricao="Noite inventada para ensaiar o painel: votos do 1º turno de 2026 redistribuídos pela migração de 2014/2018/2022, com erros sorteados; boletins na hora em que chegaram no 1º turno.",
                     inicio="2026-10-25T17:00:00", passoMin=PASSO_MIN, passos=n, prior="prior_2026.json", eventos=ev,
                     final=dict(b=round(final, 5))), SAIDA / "sim_2026.json")
    print("simulação: final", round(final, 4))


def curva_hora(s, col_b, col_a, inicio, rotulo="17:00"):
    """Fatia de B entre A+B (acumulada) e fração de seções recebidas, em passos de 2 min desde as 17h."""
    k = ((s["t"] - inicio).dt.total_seconds() // (60 * PASSO_MIN)).clip(0).fill_null(0).to_numpy().astype(int)
    nk = k.max() + 1
    cb, ca, cs = (np.cumsum(np.bincount(k, weights=w, minlength=nk)) for w in (s[col_b].to_numpy().astype(float), s[col_a].to_numpy().astype(float), np.ones(len(k))))
    return dict(inicio=rotulo, passoMin=PASSO_MIN, b=[round(float(v), 5) for v in cb / np.maximum(cb + ca, 1)],
                q=[round(float(v), 4) for v in cs / len(k)])


def quantis_iniciais(arq_prior):
    """Percentis da projeção antes do primeiro boletim, calculados pelo mesmo modelo do navegador."""
    import json
    import subprocess
    js = ("const M=require(process.argv[1]);const pr=require(process.argv[2]);const P=M.preparar(pr);"
          "const p=M.projetar(P,M.vazio(P),{sims:20000,semente:3});const a=p.amostras;"
          "const q=x=>a[Math.round(x*(a.length-1))];console.log(JSON.stringify({q05:q(.05),q50:q(.5),q95:q(.95)}))")
    out = subprocess.run(["node", "-e", js, str(SITE / "ao-vivo" / "modelo.js"), str(arq_prior)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def simular_noite(s, rng, alvo):
    """Votos por seção = esperado + erros por região, estado, município e seção; o erro nacional é
    ajustado para o resultado final cair no alvo. Boletins chegam na hora do 1º turno, 21 dias depois."""
    ufs = sorted(s["uf"].unique().to_list())
    dr = {r: rng.normal(0, SIGMA["regiao"]) for r in REGIOES}
    du = {u: rng.normal(0, SIGMA["uf"]) for u in ufs}
    muns = s.select("uf", "mun").unique()
    dm = dict(zip(zip(muns["uf"], muns["mun"]), rng.normal(0, SIGMA["municipio"], muns.height)))
    p = (s["d2"] / (s["e2"] + s["d2"])).to_numpy()
    base = logit(p) + np.array([dr[REGIAO[u]] + du[u] + dm[(u, m)] for u, m in zip(s["uf"], s["mun"])]) + rng.normal(0, RUIDO_SECAO_SIM, len(p))
    val = rng.poisson(np.maximum(s["e2"] + s["d2"], 0).to_numpy())
    lo, hi = -1.0, 1.0
    for _ in range(50):  # erro nacional que leva o resultado esperado ao alvo
        d0 = (lo + hi) / 2
        if (val * sig(base + d0)).sum() / val.sum() < alvo:
            lo = d0
        else:
            hi = d0
    vb = rng.binomial(val, sig(base + d0))
    return s.with_columns(a=pl.Series(val - vb), b=pl.Series(vb), t=pl.col("t") + timedelta(days=21)), d0


# ---------------------------------------------------------------- 2022 (teste com a noite real)
def main_2022():
    Bs, tr = matrizes({"2014": 30, "2018": 70})  # só o que se sabia antes de 2022
    classif = {n: c["grupo"] for n, c in tr["classif"]["2022"].items()}
    chave = lambda df: df.filter(pl.col("SG_UF") != "ZZ").with_columns(
        uf=pl.col("SG_UF"), mun=pl.col("CD_MUNICIPIO").str.zfill(5), z=pl.col("NR_ZONA").cast(pl.Int32), sc=pl.col("NR_SECAO").cast(pl.Int32))
    v = chave(pl.read_parquet(DATA / "hist_2022_votos.parquet"))
    d = chave(pl.read_parquet(DATA / "hist_2022_detalhe.parquet"))
    v1 = v.filter(pl.col("NR_TURNO") == "1").with_columns(
        g=pl.when(pl.col("NR_VOTAVEL").is_in(["95", "96"])).then(pl.lit("BN")).otherwise(pl.col("NR_VOTAVEL").replace_strict(classif, default="OD")))
    x = v1.group_by("uf", "mun", "z", "sc").agg(**{g: pl.col("QT_VOTOS").filter(pl.col("g") == g).sum() for g in G1 if g != "AB"})
    d1 = d.filter(pl.col("NR_TURNO") == "1").select("uf", "mun", "z", "sc", ab=(pl.col("QT_APTOS") - pl.col("QT_COMPARECIMENTO")).clip(0))
    d2 = d.filter(pl.col("NR_TURNO") == "2").select("uf", "mun", "z", "sc", aptos="QT_APTOS")
    s = x.join(d1, on=["uf", "mun", "z", "sc"]).join(d2, on=["uf", "mun", "z", "sc"]).rename({"ab": "AB"})
    s = prior_secoes(s, Bs)
    prior = prior_municipios(s, "2º turno de 2022 (teste)", dict(a="13", b="22", nomeA="Lula", nomeB="Jair Bolsonaro"))
    c = pl.read_parquet(DATA / "curva_2022_2t.parquet").filter(pl.col("SG_UF") != "ZZ")
    p = c["sec"].str.split("-")
    c = c.with_columns(uf=pl.col("SG_UF"), mun=p.list.get(0).str.zfill(5), z=p.list.get(1).cast(pl.Int32), sc=p.list.get(2).cast(pl.Int32))
    c = c.join(d2, on=["uf", "mun", "z", "sc"], how="left").with_columns(pl.col("aptos").fill_null(0))
    c = c.join(s.select("uf", "mun", "z", "sc", "e2", "d2"), on=["uf", "mun", "z", "sc"], how="left")
    t = c["t"].to_numpy()
    cc = c.drop_nulls("d2")
    prior["curvaEsperada"] = curva_por_q(cc["t"].to_numpy(), cc["d2"], cc["e2"] + cc["d2"])
    prior["curvaEsperadaHora"] = curva_hora(cc, "d2", "e2", datetime(2022, 10, 30, 17, 0))
    ev, n = empacotar_eventos(eventos(c, datetime(2022, 10, 30, 17, 0), "v22", "v13", "aptos"), prior)
    final = float(c["v22"].sum() / (c["v13"].sum() + c["v22"].sum()))
    gravar_json(prior, SAIDA / "prior_2022.json")
    gravar_json(dict(nome="2º turno de 2022 (noite real)", descricao="Boletins reais na hora em que chegaram; o modelo só sabe o que se sabia antes da eleição.",
                     inicio="2022-10-30T17:00:00", passoMin=PASSO_MIN, passos=n, prior="prior_2022.json", eventos=ev,
                     final=dict(b=round(final, 5))), SAIDA / "replay_2022.json")
    print("2022 esperado:", prior["esperado"], "real:", final, "seções sem prior:", c.height - cc.height, len(t))


if __name__ == "__main__":
    main_2022()
    main_2026(np.random.default_rng(25102026))
