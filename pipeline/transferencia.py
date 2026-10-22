"""Transferência de votos do 1º para o 2º turno (Presidente), 2014, 2018 e 2022, por inferência ecológica.

Para cada seção:  y2 = x1 · B   onde
  x1 = fração dos aptos em cada grupo no 1º turno  (E, D, OE, OC, OD, BN, AB)
  y2 = fração dos aptos em cada destino no 2º turno (E, D, BN, AB)
  B  = matriz de transferência 7x4, cada linha soma 1 e não tem negativos.
B é estimada por região com:
  - estimador "within": compara seções do mesmo município (mais 10% da variação entre municípios),
    o que tira boa parte da falácia ecológica (bairros que votam diferente por razões que não a migração);
  - efeito de contexto: a migração de outros-centro, brancos/nulos e abstenção pode variar com a
    inclinação política da seção (D / (E + D) no 1º turno);
  - agregação parcial: grupos com menos de 2,5% dos eleitores da região são puxados para o
    comportamento do mesmo campo em outros anos/regiões, na proporção do seu tamanho.
Incerteza: bootstrap reamostrando municípios. Detalhes em site/metodologia/.

Saída: site/dados/transferencia.json
"""
import json
import sys

import numpy as np
import polars as pl

from comum import DADOS, DATA

G1 = ["E", "D", "OE", "OC", "OD", "BN", "AB"]
G2 = ["E", "D", "BN", "AB"]
NOMES_G1 = {"E": "Candidato principal da esquerda", "D": "Candidato principal da direita", "OE": "Outros de esquerda e centro-esquerda",
            "OC": "Outros de centro", "OD": "Outros de direita", "BN": "Brancos e nulos", "AB": "Abstenção"}
NOMES_G2 = {"E": "Esquerda", "D": "Direita", "BN": "Brancos e nulos", "AB": "Abstenção"}
REGIAO = {**dict.fromkeys(["AC", "AM", "AP", "PA", "RO", "RR", "TO"], "Norte"),
          **dict.fromkeys(["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"], "Nordeste"),
          **dict.fromkeys(["DF", "GO", "MS", "MT"], "Centro-Oeste"),
          **dict.fromkeys(["ES", "MG", "RJ", "SP"], "Sudeste"),
          **dict.fromkeys(["PR", "RS", "SC"], "Sul")}

# Classificação dos candidatos do 1º turno. Os "outros" são agrupados pelo campo político declarado do partido
# e pelo apoio no 2º turno quando houve; é uma escolha editável, não um dado.
CLASSIF = {
    "2014": {"13": ("E", "Dilma Rousseff", "PT"), "45": ("D", "Aécio Neves", "PSDB"), "40": ("OC", "Marina Silva", "PSB"),
             "50": ("OE", "Luciana Genro", "PSOL"), "43": ("OE", "Eduardo Jorge", "PV"), "16": ("OE", "Zé Maria", "PSTU"),
             "21": ("OE", "Mauro Iasi", "PCB"), "29": ("OE", "Rui Costa Pimenta", "PCO"), "20": ("OD", "Pastor Everaldo", "PSC"),
             "28": ("OD", "Levy Fidelix", "PRTB"), "27": ("OD", "Eymael", "PSDC")},
    "2018": {"13": ("E", "Fernando Haddad", "PT"), "17": ("D", "Jair Bolsonaro", "PSL"), "12": ("OE", "Ciro Gomes", "PDT"),
             "50": ("OE", "Guilherme Boulos", "PSOL"), "18": ("OE", "Marina Silva", "REDE"), "16": ("OE", "Vera Lúcia", "PSTU"),
             "54": ("OE", "João Goulart Filho", "PPL"), "45": ("OC", "Geraldo Alckmin", "PSDB"), "15": ("OC", "Henrique Meirelles", "MDB"),
             "19": ("OC", "Alvaro Dias", "PODE"), "30": ("OD", "João Amoêdo", "NOVO"), "51": ("OD", "Cabo Daciolo", "PATRI"),
             "27": ("OD", "Eymael", "DC")},
    "2022": {"13": ("E", "Lula", "PT"), "22": ("D", "Jair Bolsonaro", "PL"), "12": ("OE", "Ciro Gomes", "PDT"),
             "80": ("OE", "Léo Péricles", "UP"), "21": ("OE", "Sofia Manzano", "PCB"), "16": ("OE", "Vera Lúcia", "PSTU"),
             "15": ("OC", "Simone Tebet", "MDB"), "44": ("OC", "Soraya Thronicke", "UNIÃO"), "30": ("OD", "Felipe d'Avila", "NOVO"),
             "14": ("OD", "Padre Kelmon", "PTB"), "27": ("OD", "Eymael", "DC")},
}
# proposta inicial para 2026 (o painel deixa reclassificar)
CLASSIF_2026 = {"13": "E", "22": "D", "70": "OC", "55": "OD", "14": "OD", "30": "OD", "80": "OE", "27": "OD",
                "21": "OE", "16": "OE", "29": "OE", "35": "OD", "28": "OD"}
N_BOOT = 120
# grupo com menos que isso dos eleitores da região não tem sinal suficiente nos dados agregados para ser estimado
MIN_GRUPO = 0.025


def matriz_secoes(ano):
    v = pl.read_parquet(DATA / f"hist_{ano}_votos.parquet").filter(pl.col("SG_UF") != "ZZ")
    d = pl.read_parquet(DATA / f"hist_{ano}_detalhe.parquet").filter(pl.col("SG_UF") != "ZZ")
    cl = CLASSIF[ano]
    v = v.filter(~pl.col("NR_VOTAVEL").is_in(["95", "96", "97"])).with_columns(
        g=pl.col("NR_VOTAVEL").replace_strict({k: x[0] for k, x in cl.items()}, default="OD"))
    k = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]
    por_g = v.group_by(k + ["NR_TURNO", "g"]).agg(pl.col("QT_VOTOS").sum()).pivot(on="g", index=k + ["NR_TURNO"], values="QT_VOTOS").fill_null(0)
    t = d.join(por_g, on=k + ["NR_TURNO"], how="left").fill_null(0).with_columns(
        BN=pl.col("QT_VOTOS_BRANCOS") + pl.col("QT_VOTOS_NULOS"), AB=pl.col("QT_APTOS") - pl.col("QT_COMPARECIMENTO"))
    for g in G1:
        if g not in t.columns:
            t = t.with_columns(pl.lit(0).alias(g))
    t1 = t.filter(pl.col("NR_TURNO") == "1").select(k + ["QT_APTOS"] + G1)
    t2 = t.filter(pl.col("NR_TURNO") == "2").select(k + [pl.col("QT_APTOS").alias("APTOS2")] + [pl.col(g).alias(g + "_2") for g in G2])
    m = t1.join(t2, on=k, how="inner").filter((pl.col("QT_APTOS") >= 20) & (pl.col("APTOS2") >= 20))
    return m.with_columns(regiao=pl.col("SG_UF").replace_strict(REGIAO), muni=pl.concat_str("SG_UF", "CD_MUNICIPIO"))


def projetar_linhas(Bm):
    """Projeção euclidiana de cada linha no simplex (soma 1, sem negativos)."""
    u = -np.sort(-Bm, axis=1)
    css = np.cumsum(u, axis=1) - 1
    k = np.arange(1, Bm.shape[1] + 1)
    rho = (u - css / k > 0).sum(axis=1)
    theta = css[np.arange(Bm.shape[0]), rho - 1] / rho
    return np.maximum(Bm - theta[:, None], 0)


# grupos grandes cuja migração pode variar com a inclinação política da seção (outros de centro, brancos/nulos, abstenção)
CTX = [3, 5, 6]


def _projetar_ctx(Bm, nb):
    """Linhas principais no simplex; linhas de interação com soma zero, para que cada linha continue somando 1
    em qualquer contexto."""
    out = Bm.copy()
    out[:nb] = projetar_linhas(Bm[:nb])
    out[nb:] = Bm[nb:] - Bm[nb:].mean(axis=1, keepdims=True)
    return out


def ajustar(X, Y, w, grupo, mu=0.1, iters=12000):
    """Matriz de transferência estimada sobretudo DENTRO de cada município, com efeito de contexto.

    Dois cuidados contra a falácia ecológica (atribuir a um grupo o comportamento do lugar onde ele mora):
    1. comparar seções do mesmo município, o que tira a diferença entre lugares (capital x interior); um pouco
       (peso mu) da variação entre municípios entra para determinar a direção que a comparação interna não fixa;
    2. deixar a migração dos grupos grandes (CTX) variar com a inclinação política da seção no 1º turno, para que
       essa variação não seja atribuída aos grupos pequenos concentrados em certos bairros.
    Devolve só as linhas principais (a transferência no contexto médio)."""
    z = X[:, 1] / np.maximum(X[:, 0] + X[:, 1], 1e-6)
    z = z - np.average(z, weights=w)
    Xa = np.column_stack([X] + [X[:, k] * z for k in CTX])
    w = w / w.sum()
    ng = int(grupo.max()) + 1
    sw = np.bincount(grupo, weights=w, minlength=ng)
    ok = sw > 0
    Xm = np.zeros((ng, Xa.shape[1]))
    Ym = np.zeros((ng, Y.shape[1]))
    for k in range(Xa.shape[1]):
        Xm[ok, k] = np.bincount(grupo, weights=w * Xa[:, k], minlength=ng)[ok] / sw[ok]
    for k in range(Y.shape[1]):
        Ym[ok, k] = np.bincount(grupo, weights=w * Y[:, k], minlength=ng)[ok] / sw[ok]
    Xd, Yd = Xa - Xm[grupo], Y - Ym[grupo]
    XtX = (Xd * w[:, None]).T @ Xd + mu * (Xm * sw[:, None]).T @ Xm
    XtY = (Xd * w[:, None]).T @ Yd + mu * (Xm * sw[:, None]).T @ Ym
    nb = X.shape[1]
    L = 2 * np.linalg.eigvalsh(XtX).max()
    Bm = np.zeros((Xa.shape[1], Y.shape[1]))
    Bm[:nb] = 1 / Y.shape[1]
    Z, t = Bm.copy(), 1.0
    for _ in range(iters):
        novo = _projetar_ctx(Z - (2 * (XtX @ Z - XtY)) / L, nb)
        t2 = (1 + np.sqrt(1 + 4 * t * t)) / 2
        Z = novo + ((t - 1) / t2) * (novo - Bm)
        if np.abs(novo - Bm).max() < 1e-10:
            Bm = novo
            break
        Bm, t = novo, t2
    return Bm[:nb]


def agregar_parcial(medias, partes, linhas=(2, 3, 4, 5)):
    """Grupo pequeno empresta força do mesmo campo político medido em outras eleições e regiões.

    Para cada linha, a estimativa final é  p * própria + (1 - p) * campo,  com p = min(1, parte / MIN_GRUPO):
    um grupo com 2,5% ou mais dos eleitores da região usa só os próprios dados; um com 0,8% usa 32% dos próprios
    dados. "campo" é a média da mesma linha em todas as eleições e regiões, ponderada por parte * p (as medições
    de grupos grandes pesam mais). medias: {(ano, reg): matriz}; partes: {(ano, reg): vetor}."""
    final = {c: np.array(B, dtype=float) for c, B in medias.items()}
    pesos = {}
    for k in linhas:
        pw = {c: min(1.0, partes[c][k] / MIN_GRUPO) for c in medias}
        den = sum(partes[c][k] * pw[c] for c in medias)
        campo = sum(np.array(medias[c][k]) * partes[c][k] * pw[c] for c in medias) / den
        for c in medias:
            final[c][k] = pw[c] * np.array(medias[c][k]) + (1 - pw[c]) * campo
            pesos.setdefault(c, [1.0] * 7)[k] = round(pw[c], 3)
    return final, pesos


def frac(m):
    X = (m.select(G1).to_numpy() / m["QT_APTOS"].to_numpy()[:, None]).astype(float)
    Y = (m.select([g + "_2" for g in G2]).to_numpy() / m["APTOS2"].to_numpy()[:, None]).astype(float)
    return X, Y, m["QT_APTOS"].to_numpy().astype(float)


def main():
    rng = np.random.default_rng(2026)
    saida = dict(g1=G1, g2=G2, nomesG1=NOMES_G1, nomesG2=NOMES_G2, regioes=sorted(set(REGIAO.values())), anos={},
                 classif={a: {n: dict(grupo=g, nome=nm, partido=p) for n, (g, nm, p) in c.items()} for a, c in CLASSIF.items()},
                 classif2026=CLASSIF_2026, minGrupo=MIN_GRUPO)
    medias, partes, draws_brutos, matrizes = {}, {}, {}, {}
    for ano in ["2014", "2018", "2022"]:
        m = matriz_secoes(ano)
        matrizes[ano] = m
        saida["anos"][ano] = dict(regioes={}, secoes=m.height)
        for reg in saida["regioes"]:
            mr = m.filter(pl.col("regiao") == reg)
            X, Y, w = frac(mr)
            grupo = np.unique(mr["muni"].to_numpy(), return_inverse=True)[1]
            Bm = ajustar(X, Y, w, grupo)
            parte = np.average(X, axis=0, weights=w)
            medias[(ano, reg)], partes[(ano, reg)] = Bm, parte
            # bootstrap por município
            ng = grupo.max() + 1
            linhas = np.split(np.argsort(grupo, kind="stable"), np.cumsum(np.bincount(grupo, minlength=ng))[:-1])
            dr = []
            for _ in range(N_BOOT):
                esc = rng.integers(0, ng, ng)
                sel = np.concatenate([linhas[i] for i in esc])
                novo_g = np.repeat(np.arange(ng), [len(linhas[i]) for i in esc])
                dr.append(ajustar(X[sel], Y[sel], w[sel], novo_g))
            draws_brutos[(ano, reg)] = dr
            saida["anos"][ano]["regioes"][reg] = dict(
                parte=np.round(parte, 4).tolist(), mediaDados=np.round(Bm, 4).tolist(),
                rmse=float(np.sqrt(np.average(((X @ Bm) - Y) ** 2, axis=0, weights=w)).mean()),
                totalReal=np.round((Y * w[:, None]).sum(axis=0)).tolist())
            print(ano, reg, "seções", mr.height, "| partes OE/OC/OD", np.round(parte[2:5] * 100, 1),
                  "| OE", np.round(Bm[2], 2), "OC", np.round(Bm[3], 2), "OD", np.round(Bm[4], 2), flush=True)
        saida["anos"][ano]["t1"] = m.select(G1).sum().row(0, named=True)
        saida["anos"][ano]["t2"] = {g: float(m[g + "_2"].sum()) for g in G2}
    # agregação parcial dos grupos pequenos, na média e em cada sorteio do bootstrap
    finais, pesos = agregar_parcial(medias, partes)
    dr_finais = [agregar_parcial({c: draws_brutos[c][d] for c in medias}, partes)[0] for d in range(N_BOOT)]
    for (ano, reg), Bf in finais.items():
        R = saida["anos"][ano]["regioes"][reg]
        R.update(media=np.round(Bf, 4).tolist(), peso=pesos[(ano, reg)], ok=[True] * len(G1),
                 draws=[np.round(dr_finais[d][(ano, reg)], 4).tolist() for d in range(N_BOOT)])
        print(ano, reg, "final | OE", np.round(Bf[2], 2), "OC", np.round(Bf[3], 2), "OD", np.round(Bf[4], 2),
              "| peso próprio", pesos[(ano, reg)][2:5], flush=True)
    # validação: transferências de um ano aplicadas ao 1º turno do ano seguinte
    val = []
    for treino, teste in [("2014", "2018"), ("2018", "2022"), ("2014", "2022")]:
        m = matrizes[teste]
        tot = np.zeros(len(G2))
        for reg in saida["regioes"]:
            tot += m.filter(pl.col("regiao") == reg).select(G1).to_numpy().sum(axis=0) @ finais[(treino, reg)]
        real = np.array([saida["anos"][teste]["t2"][g] for g in G2])
        pe, re = tot[0] / (tot[0] + tot[1]), real[0] / (real[0] + real[1])
        val.append(dict(treino=treino, teste=teste, previstoE=round(pe, 4), realE=round(re, 4), erroPP=round((pe - re) * 100, 2),
                        previstoComp=round(1 - tot[3] / tot.sum(), 4), realComp=round(1 - real[3] / real.sum(), 4)))
        print("validação", treino, "->", teste, val[-1], flush=True)
    saida["validacao"] = val
    with open(DADOS / "transferencia.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
