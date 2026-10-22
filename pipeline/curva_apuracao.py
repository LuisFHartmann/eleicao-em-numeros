"""Curva da apuração reconstruída pela hora de chegada de cada boletim (DT_BU_RECEBIDO),
e a mesma apuração "normalizada": cada estado mantém a ordem em que seus boletins chegaram,
mas todos os estados andam no mesmo ritmo (o 1º boletim de cada estado no instante 0, o último no fim).

Saída: site/apuracao/dados/curva.json             1º turno 2026, mais a comparação normalizada das três eleições
       site/apuracao/dados/curva_2022_1t.json     mesma estrutura, 1º turno de 2022
       site/apuracao/dados/curva_2022_2t.json     mesma estrutura, 2º turno de 2022
"""
from datetime import datetime

import numpy as np
import polars as pl

from comum import DATA, REGIAO, SITE, UFS, gravar_json

PASSO_MIN = 2
INICIO = datetime(2026, 10, 4, 17, 0)
N_CAND = 4
PONTOS = 200  # resolução das curvas por % apurado
FONTE = "https://dadosabertos.tse.jus.br/dataset/resultados-{ano}-boletim-de-urna"
# 2022: nomes e partidos como aparecem nos boletins de urna
CAND_2022 = {"13": ("LULA", "PT"), "22": ("JAIR BOLSONARO", "PL"), "15": ("SIMONE TEBET", "MDB"), "12": ("CIRO GOMES", "PDT")}
NOMES_2022 = {"13": "Lula", "22": "Jair Bolsonaro"}


def secoes_2026():
    b = pl.concat([pl.read_parquet(DATA / f"bweb_{u}.parquet", columns=[
        "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO_PERGUNTA", "DT_BU_RECEBIDO", "NR_VOTAVEL", "NM_VOTAVEL",
        "SG_PARTIDO", "QT_VOTOS", "QT_APTOS"]) for u in UFS]).filter(pl.col("CD_CARGO_PERGUNTA") == "1")
    return b.select(uf="SG_UF", sec=pl.concat_str("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", separator="-"),
                    t=pl.col("DT_BU_RECEBIDO").str.to_datetime(), n="NR_VOTAVEL", nome="NM_VOTAVEL", partido="SG_PARTIDO",
                    v=pl.col("QT_VOTOS").cast(pl.Int64), aptos=pl.col("QT_APTOS").cast(pl.Int64))


def comparar(sec, a, b):
    """sec: uf, t, va, vb, val (uma linha por seção). Curvas de a e b por % de seções apuradas:
    real (ordem nacional de chegada) e normalizada (cada UF no próprio ritmo, todas juntas)."""
    sec = sec.drop_nulls("t").sort("t")
    n = sec.height
    # real: k-ésima seção a chegar no país
    ca, cb, cv = (np.cumsum(sec[c].to_numpy()) for c in ("va", "vb", "val"))
    # normalizada: posição de cada seção dentro do seu estado, de 0 a 1
    sec = sec.with_columns(p=(pl.int_range(pl.len()).over("uf") + 1) / pl.len().over("uf")).sort("p")
    na, nb, nv = (np.cumsum(sec[c].to_numpy()) for c in ("va", "vb", "val"))
    q = np.linspace(0, 1, PONTOS + 1)[1:]
    idx_r = np.clip((q * n).astype(int) - 1, 0, n - 1)
    pos = sec["p"].to_numpy()
    idx_n = np.clip(np.searchsorted(pos, q, side="right") - 1, 0, n - 1)
    r = lambda x: [round(float(v), 5) for v in x]
    return dict(q=r(q), real={a: r(ca[idx_r] / cv[idx_r]), b: r(cb[idx_r] / cv[idx_r])},
                normalizada={a: r(na[idx_n] / nv[idx_n]), b: r(nb[idx_n] / nv[idx_n])},
                final={a: round(float(ca[-1] / cv[-1]), 5), b: round(float(cb[-1] / cv[-1]), 5)})


def secoes_2022(turno):
    """Uma linha por seção (só as 27 UFs): uf, t, aptos e uma coluna de votos por grupo. Grupos: candidatos
    (do mais ao menos votado), "outros" no 1º turno, 95 e 96."""
    if turno == "1":
        s = pl.read_parquet(DATA / "curva_2022_1t.parquet")
        cands = sorted([c[1:] for c in s.columns if c.startswith("v") and c[1:].isdigit() and c[1:] not in ("95", "96")],
                       key=lambda n: -s[f"v{n}"].sum())
        s = s.with_columns(outros=pl.col("val") - pl.sum_horizontal([f"v{n}" for n in cands]))
        n_outros = int(pl.read_parquet(DATA / "hist_2022_votos.parquet").filter(
            (pl.col("NR_TURNO") == "1") & ~pl.col("NR_VOTAVEL").is_in(["95", "96"]))["NR_VOTAVEL"].n_unique()) - len(cands)
    else:
        # o arquivo do 2º turno só tem 13 e 22; aptos, brancos e nulos vêm do detalhe por seção
        det = pl.read_parquet(DATA / "hist_2022_detalhe.parquet").filter(pl.col("NR_TURNO") == "2").select(
            "SG_UF", sec=pl.concat_str("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", separator="-"),
            aptos="QT_APTOS", v95="QT_VOTOS_BRANCOS", v96="QT_VOTOS_NULOS")
        s = pl.read_parquet(DATA / "curva_2022_2t.parquet").join(det, on=["SG_UF", "sec"], how="left")
        cands = sorted(["13", "22"], key=lambda n: -s[f"v{n}"].sum())
        s = s.with_columns(val=pl.col("v13") + pl.col("v22"))
        n_outros = 0
    s = s.filter(pl.col("SG_UF").is_in(UFS)).rename({"SG_UF": "uf"}).rename({f"v{n}": n for n in cands + ["95", "96"]})
    grupos = cands + (["outros"] if n_outros else []) + ["95", "96"]
    cands = [dict(n=n, nome=CAND_2022[n][0], partido=CAND_2022[n][1]) for n in cands]
    if n_outros:
        cands.append(dict(n="outros", nome=f"Outros {n_outros} candidatos", partido=None))
    cands += [dict(n="95", nome="Branco", partido=None), dict(n="96", nome="Nulo", partido=None)]
    return s.with_columns(pl.col(grupos + ["aptos"]).fill_null(0)), grupos, cands


def curva_completa(sec, grupos, inicio):
    """sec: uma linha por seção com uf, t, aptos e uma coluna por grupo. Séries acumuladas por passo e por UF."""
    sec = sec.drop_nulls("t").with_columns(
        passo=((pl.col("t") - inicio).dt.total_seconds() // (60 * PASSO_MIN)).clip(0).cast(pl.Int32))
    # alguns boletins só chegam no dia seguinte: tudo o que chega depois de 99,9% das seções + 1 h
    # entra no último passo (o total final não muda, e a página só mostra até 99,9% + 30 min)
    corte = int(sec["passo"].sort()[int(0.999 * sec.height)]) + 60 // PASSO_MIN
    sec = sec.with_columns(pl.col("passo").clip(upper_bound=corte))
    n_passos = int(sec["passo"].max()) + 1
    estados = {}
    for uf in UFS:
        s = sec.filter(pl.col("uf") == uf)
        p = s["passo"].to_numpy()
        acum = lambda w=None: np.cumsum(np.bincount(p, weights=w, minlength=n_passos)).round().astype(np.int64).tolist()
        estados[uf] = dict(regiao=REGIAO[uf], secoes=s.height, aptos=int(s["aptos"].sum()), recebidas=acum(),
                           votos={g: acum(s[g].to_numpy().astype(float)) for g in grupos})
    return n_passos, estados


def main():
    df = secoes_2026()
    tot = df.group_by("n", "nome", "partido").agg(v=pl.col("v").sum()).sort("v", descending=True)
    nominais = tot.filter(~pl.col("n").is_in(["95", "96"]))
    principais = nominais.head(N_CAND)["n"].to_list()
    grupos = principais + ["outros", "95", "96"]
    df = df.with_columns(g=pl.when(pl.col("n").is_in(principais + ["95", "96"])).then(pl.col("n")).otherwise(pl.lit("outros")),
                         passo=((pl.col("t") - INICIO).dt.total_seconds() // (60 * PASSO_MIN)).clip(0).cast(pl.Int32))
    n_passos = int(df["passo"].max()) + 1

    def serie(sub, col):
        s = sub.group_by("passo").agg(x=pl.col(col).sum())
        arr = np.zeros(n_passos, dtype=np.int64)
        for p, x in s.iter_rows():
            arr[p] += x
        return np.cumsum(arr).tolist()

    secs = df.group_by("uf", "sec").agg(pl.col("passo", "aptos", "t").first(),
                                        va=pl.col("v").filter(pl.col("n") == principais[0]).sum(),
                                        vb=pl.col("v").filter(pl.col("n") == principais[1]).sum(),
                                        val=pl.col("v").filter(~pl.col("n").is_in(["95", "96"])).sum())
    estados = {}
    for uf in UFS:
        d, s = df.filter(pl.col("uf") == uf), secs.filter(pl.col("uf") == uf).with_columns(um=pl.lit(1))
        estados[uf] = dict(regiao=REGIAO[uf], secoes=s.height, aptos=int(s["aptos"].sum()), recebidas=serie(s, "um"),
                           votos={g: serie(d.filter(pl.col("g") == g), "v") for g in grupos})
    cands = []
    for g in grupos:
        if g == "outros":
            cands.append(dict(n="outros", nome=f"Outros {nominais.height - len(principais)} candidatos", partido=None))
        else:
            x = tot.filter(pl.col("n") == g).row(0, named=True)
            cands.append(dict(n=g, nome=x["nome"].title() if g in ("95", "96") else x["nome"],
                              partido=None if x["partido"] == "#NULO#" else x["partido"]))
    # comparação real x normalizada: 1º turno 2026 (22 x 13) e 2º turno 2022 (13 x 22)
    c26 = comparar(secs.select("uf", "t", "va", "vb", "val"), principais[0], principais[1])
    s22 = pl.read_parquet(DATA / "curva_2022_2t.parquet").filter(pl.col("SG_UF") != "ZZ")
    c22 = comparar(s22.select(uf="SG_UF", t="t", va="v13", vb="v22", val=pl.col("v13") + pl.col("v22")), "13", "22")
    c22["nomes"] = NOMES_2022
    c26["nomes"] = {c["n"]: c["nome"] for c in cands if c["n"] in principais[:2]}
    # 1º turno 2022: fatias de 13 e 22 entre todos os votos nominais (havia outros 9 candidatos)
    s1, g1, cand1 = secoes_2022("1")
    c22_1 = comparar(s1.select("uf", "t", va="13", vb="22", val="val"), "13", "22")
    c22_1["nomes"] = NOMES_2022
    normalizada = {"2026": c26, "2022": c22, "2022_1t": c22_1}
    gravar_json(dict(inicio=INICIO.isoformat(), passoMin=PASSO_MIN, passos=n_passos, candidatos=cands, estados=estados,
                     normalizada=normalizada, fonte=FONTE.format(ano=2026)),
                SITE / "apuracao" / "dados" / "curva.json")
    # arquivos completos das eleições de 2022, para a curva principal trocar de eleição
    for chave, turno, inicio, norm in (("2022_1t", "1", datetime(2022, 10, 2, 17, 0), "2022_1t"),
                                       ("2022_2t", "2", datetime(2022, 10, 30, 17, 0), "2022")):
        sec, grupos, cs = (s1, g1, cand1) if turno == "1" else secoes_2022("2")
        passos, est = curva_completa(sec, grupos, inicio)
        gravar_json(dict(inicio=inicio.isoformat(), passoMin=PASSO_MIN, passos=passos, candidatos=cs, estados=est,
                         normalizada={norm: normalizada[norm]}, fonte=FONTE.format(ano=2022)),
                    SITE / "apuracao" / "dados" / f"curva_{chave}.json")
        tot = {g: sum(e["votos"][g][-1] for e in est.values()) for g in grupos}
        val = sum(v for g, v in tot.items() if g not in ("95", "96"))
        print(chave, "seções", sum(e["secoes"] for e in est.values()), "passos", passos,
              " ".join(f"{g}={tot[g] / val:.4%}" for g in grupos if g not in ("95", "96")))
    for k, c in normalizada.items():
        a, b = list(c["final"])
        for i in (9, 19, 49, 99):
            print(k, f"{c['q'][i]:.0%}", "real", a, c["real"][a][i], b, c["real"][b][i], "| norm", c["normalizada"][a][i], c["normalizada"][b][i])


if __name__ == "__main__":
    main()
