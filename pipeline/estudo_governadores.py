"""Quem tenta a reeleição ganha no 2º turno mais do que o 1º turno sugere? Teste com os 2º turnos de governador.

Seis eleições presidenciais são poucas para medir um "peso da continuidade". Os 2º turnos estaduais de 2002 a
2022 dão dezenas de casos com a mesma pergunta: num 2º turno em que um dos finalistas é o governador
concorrendo à reeleição, ele termina acima do que a fatia dos dois no 1º turno indicava?

Dados (TSE, dados abertos): votação por candidato (governador, por UF) e cadastro de candidatos (ST_REELEICAO).
Modelo: logit(fatia no 2º) = a + b * logit(fatia entre os dois no 1º) + c * (A tenta reeleição - B tenta reeleição),
com A = o mais votado no 1º turno. "c" é o efeito da reeleição; o intervalo vem de bootstrap das disputas.

Saída: data/estudo/governadores.json
Uso: python pipeline/estudo_governadores.py
"""
import io
import json
import zipfile

import numpy as np
import polars as pl

from comum import DATA, baixar_em_memoria, csv_do_zip

ODSELE = "https://cdn.tse.jus.br/estatistica/sead/odsele"
ANOS = [2002, 2006, 2010, 2014, 2018, 2022]


def votos_governador(ano):
    z = zipfile.ZipFile(io.BytesIO(baixar_em_memoria(f"{ODSELE}/votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip")))
    nomes = [n for n in z.namelist() if n.endswith(".csv")]
    nomes = [n for n in nomes if n.endswith("_BRASIL.csv")] if ano >= 2014 else [n for n in nomes if not n.endswith(("_BR.csv", "_BRASIL.csv"))]

    def reduzir(df):
        q = "QT_VOTOS_NOMINAIS_VALIDOS" if "QT_VOTOS_NOMINAIS_VALIDOS" in df.columns else "QT_VOTOS_NOMINAIS"
        # só eleições ordinárias: o arquivo do ano também traz as suplementares do mesmo mandato
        return (df.filter((pl.col("CD_CARGO") == "3") & (pl.col("CD_TIPO_ELEICAO") == "2")).group_by("NR_TURNO", "SG_UF", "NR_CANDIDATO")
                .agg(votos=pl.col(q).str.replace_all(r"\D", "").cast(pl.Int64).sum(), nome=pl.col("NM_URNA_CANDIDATO").first(),
                     partido=pl.col("SG_PARTIDO").first()))
    df = pl.concat([csv_do_zip(z, reduzir, nome=n) for n in nomes], how="diagonal_relaxed")
    return df.group_by("NR_TURNO", "SG_UF", "NR_CANDIDATO").agg(pl.col("votos").sum(), pl.col("nome").first(), pl.col("partido").first())


def reeleicao(ano):
    z = zipfile.ZipFile(io.BytesIO(baixar_em_memoria(f"{ODSELE}/consulta_cand/consulta_cand_{ano}.zip")))
    nome = next(n for n in z.namelist() if n.endswith("_BRASIL.csv"))

    def reduzir(df):
        return df.filter((pl.col("CD_CARGO") == "3") & (pl.col("CD_TIPO_ELEICAO") == "2")).select("SG_UF", "NR_CANDIDATO", "SQ_CANDIDATO",
                                                           *(["ST_REELEICAO"] if "ST_REELEICAO" in df.columns else []))
    c = csv_do_zip(z, reduzir, nome=nome)
    if "ST_REELEICAO" not in c.columns:  # a partir de 2022 a coluna fica no cadastro complementar
        zc = zipfile.ZipFile(io.BytesIO(baixar_em_memoria(f"{ODSELE}/consulta_cand_complementar/consulta_cand_complementar_{ano}.zip")))
        nc = next(n for n in zc.namelist() if n.endswith("_BRASIL.csv"))
        comp = csv_do_zip(zc, lambda df: df.select("SQ_CANDIDATO", "ST_REELEICAO"), nome=nc)
        c = c.join(comp.unique("SQ_CANDIDATO"), on="SQ_CANDIDATO", how="left")
    return c.select("SG_UF", "NR_CANDIDATO", "ST_REELEICAO").unique(["SG_UF", "NR_CANDIDATO"])


def logit(p):
    return np.log(p / (1 - p))


def main():
    disputas = []
    for ano in ANOS:
        v, r = votos_governador(ano), reeleicao(ano)
        for uf in v.filter(pl.col("NR_TURNO") == "2")["SG_UF"].unique().to_list():
            t2 = v.filter((pl.col("NR_TURNO") == "2") & (pl.col("SG_UF") == uf)).sort("votos", descending=True)
            if t2.height != 2:
                continue
            t1 = v.filter((pl.col("NR_TURNO") == "1") & (pl.col("SG_UF") == uf))
            fin = t2["NR_CANDIDATO"].to_list()
            v1 = {n: t1.filter(pl.col("NR_CANDIDATO") == n)["votos"].sum() for n in fin}
            a, b = sorted(fin, key=lambda n: -v1[n])  # A = mais votado no 1º turno
            v2 = dict(zip(t2["NR_CANDIDATO"], t2["votos"]))
            reel = {n: (r.filter((pl.col("SG_UF") == uf) & (pl.col("NR_CANDIDATO") == n))["ST_REELEICAO"].to_list() or ["?"])[0] for n in fin}
            nm = dict(zip(t2["NR_CANDIDATO"], t2["nome"]))
            pt = dict(zip(t2["NR_CANDIDATO"], t2["partido"]))
            val1 = t1["votos"].sum()
            disputas.append(dict(ano=ano, uf=uf, a=nm[a], a_partido=pt[a], b=nm[b], b_partido=pt[b],
                                 h2h1=v1[a] / (v1[a] + v1[b]), fatia1_a=v1[a] / val1, fatia1_b=v1[b] / val1,
                                 fatia2=v2[a] / (v2[a] + v2[b]), reel_a=reel[a] == "S", reel_b=reel[b] == "S"))
        print(ano, sum(1 for d in disputas if d["ano"] == ano), "disputas de 2º turno", flush=True)
    d = pl.DataFrame(disputas).with_columns(inc=pl.col("reel_a").cast(pl.Int8) - pl.col("reel_b").cast(pl.Int8))
    y = logit(d["fatia2"].to_numpy())
    X = np.c_[np.ones(d.height), logit(d["h2h1"].to_numpy()), d["inc"].to_numpy()]
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    rng = np.random.default_rng(1)
    bs = []
    for _ in range(4000):
        i = rng.integers(0, d.height, d.height)
        bs.append(np.linalg.lstsq(X[i], y[i], rcond=None)[0])
    bs = np.array(bs)
    # efeito em pontos de fatia, numa disputa de 50/50 no 1º turno
    pts = (1 / (1 + np.exp(-(beta[0] + beta[2]))) - 1 / (1 + np.exp(-beta[0]))) * 100
    pts_b = (1 / (1 + np.exp(-(bs[:, 0] + bs[:, 2]))) - 1 / (1 + np.exp(-bs[:, 0]))) * 100
    com = d.filter(pl.col("inc") != 0)
    # ganho simples do governador: fatia no 2º menos fatia entre os dois no 1º, do ponto de vista dele
    ganho = np.where(com["inc"] == 1, com["fatia2"] - com["h2h1"], (1 - com["fatia2"]) - (1 - com["h2h1"])) * 100
    venceu = np.where(com["inc"] == 1, com["fatia2"] > .5, com["fatia2"] < .5)
    lider1 = np.where(com["inc"] == 1, com["h2h1"] > .5, com["h2h1"] < .5)
    res = dict(n_disputas=d.height, n_com_reeleicao=com.height, beta=beta.tolist(),
               efeito_pontos=float(pts), efeito_q05=float(np.percentile(pts_b, 5)), efeito_q95=float(np.percentile(pts_b, 95)),
               ganho_medio=float(ganho.mean()), ganho_mediana=float(np.median(ganho)), ganho_positivo=int((ganho > 0).sum()),
               venceu=int(venceu.sum()), liderava_1t=int(lider1.sum()),
               virou_a_favor=int((venceu & ~lider1).sum()), virou_contra=int((~venceu & lider1).sum()),
               disputas=[{k: (round(v, 5) if isinstance(v, float) else v) for k, v in x.items()} for x in d.to_dicts()])
    (DATA / "estudo").mkdir(exist_ok=True)
    (DATA / "estudo" / "governadores.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{d.height} disputas; {com.height} com um governador tentando a reeleição")
    print(f"efeito da reeleição (disputa 50/50 no 1º turno): {pts:+.2f} pontos [90%: {res['efeito_q05']:+.2f} a {res['efeito_q95']:+.2f}]"
          f" · inclinação b = {beta[1]:.2f}")
    print(f"ganho do governador sobre o 1º turno: média {ganho.mean():+.2f}, mediana {np.median(ganho):+.2f}, positivo em {(ganho > 0).sum()} de {len(ganho)}")
    print(f"governador venceu {venceu.sum()} de {len(venceu)}; liderava o 1º turno em {lider1.sum()}; virou a favor {res['virou_a_favor']}, perdeu liderando {res['virou_contra']}")


if __name__ == "__main__":
    main()
