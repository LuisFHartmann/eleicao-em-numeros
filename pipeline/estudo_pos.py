"""Estudo pós-resultado: rejeição e continuidade de governo melhorariam a previsão do 2º turno?

Ideia. O modelo do site previa o 2º turno a partir do 1º turno de cada município e de como os eleitores de
cada grupo (13, 22, outros de esquerda, centro, direita, branco/nulo, abstenção) migraram em 2014, 2018 e 2022.
Aqui o mesmo raciocínio é refeito com seis eleições (2002 a 2022) por município, e cada ano é previsto só com
os outros ("deixa um de fora"). O que essa previsão erra, ano a ano, é comparado com duas informações que
existiam antes de cada 2º turno: a rejeição dos dois candidatos nas pesquisas e a avaliação do governo.

Etapas:
  1. matriz de transferência 1º -> 2º turno por região e por ano (inferência ecológica nos municípios);
  2. previsão de cada ano com a média das matrizes dos outros anos (base);
  3. resíduo de cada ano (resultado menos base, em logit) contra rejeição e aprovação;
  4. modelos com esses ajustes, avaliados deixando um ano de fora, e a previsão que dariam para 2026.

Lado "E" = finalista de esquerda (o 13 em todos os anos); "D" = finalista de direita.
Saída: data/estudo/estudo_pos.json (completo) e site/dados/pos_resultado.json (o que a página usa).

Uso: python pipeline/estudo_pos.py
"""
import json
import numpy as np
import polars as pl

from comum import DATA, REGIAO, SITE, UFS, gravar_json

G1 = ["E", "D", "OE", "OC", "OD", "BN", "AB"]
G2 = ["E", "D", "BN", "AB"]
REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
ANOS = [2002, 2006, 2010, 2014, 2018, 2022, 2026]
CLASSIF = {
    2002: {"13": "E", "45": "D", "40": "OC", "23": "OE", "16": "OE", "29": "OE"},
    2006: {"13": "E", "45": "D", "50": "OE", "12": "OE", "44": "OD", "27": "OD", "17": "OD"},
    2010: {"13": "E", "45": "D", "43": "OC", "50": "OE", "27": "OD", "16": "OE", "28": "OD", "21": "OE", "29": "OE"},
}
FINALISTAS = {2002: ("13", "45"), 2006: ("13", "45"), 2010: ("13", "45"), 2014: ("13", "45"), 2018: ("13", "17"),
              2022: ("13", "22"), 2026: ("13", "22")}
NOMES = {2002: ("Lula", "Serra"), 2006: ("Lula", "Alckmin"), 2010: ("Dilma", "Serra"), 2014: ("Dilma", "Aécio"),
         2018: ("Haddad", "Bolsonaro"), 2022: ("Lula", "Bolsonaro"), 2026: ("Lula", "Flávio Bolsonaro")}
# lado do governo no 2º turno: +1 se o finalista de esquerda era o governista, -1 se o de direita, 0 se nenhum
GOVERNO = {2002: -1, 2006: 1, 2010: 1, 2014: 1, 2018: 0, 2022: -1, 2026: 1}
ESTUDO = DATA / "estudo"


def classif(ano):
    if ano in CLASSIF:
        return CLASSIF[ano]
    tr = json.load(open(SITE / "dados" / "transferencia.json", encoding="utf-8"))
    if ano == 2026:
        return tr["classif2026"]
    return {k: v["grupo"] for k, v in tr["classif"][str(ano)].items()}


def municipios_hist():
    """(ano, uf, mun) -> grupos do 1º turno e destinos do 2º, em votos, de 2002 a 2022."""
    h = pl.read_parquet(DATA / "historico_presidente.parquet").filter(~pl.col("uf").is_in(["ZZ", "VT", "BR"]))
    out = []
    for ano in ANOS[:-1]:
        c = classif(ano)
        x = h.filter(pl.col("ano") == ano)
        t1 = (x.filter(pl.col("turno") == 1).with_columns(
            g=pl.when(pl.col("votavel").is_in(["BRANCO", "NULO"])).then(pl.lit("BN"))
            .when(pl.col("votavel") == "ABSTENCAO").then(pl.lit("AB"))
            .otherwise(pl.col("votavel").replace_strict(c, default="OD")))
            .group_by("uf", "mun", "g").agg(pl.col("votos").sum())
            .pivot(on="g", index=["uf", "mun"], values="votos").fill_null(0))
        e, d = FINALISTAS[ano]
        t2 = (x.filter(pl.col("turno") == 2).with_columns(
            g=pl.when(pl.col("votavel").is_in(["BRANCO", "NULO"])).then(pl.lit("BN2"))
            .when(pl.col("votavel") == "ABSTENCAO").then(pl.lit("AB2"))
            .when(pl.col("votavel") == e).then(pl.lit("E2")).when(pl.col("votavel") == d).then(pl.lit("D2")).otherwise(pl.lit("X")))
            .filter(pl.col("g") != "X").group_by("uf", "mun", "g").agg(pl.col("votos").sum())
            .pivot(on="g", index=["uf", "mun"], values="votos").fill_null(0))
        m = t1.join(t2, on=["uf", "mun"])
        for g in G1:
            if g not in m.columns:
                m = m.with_columns(pl.lit(0).alias(g))
        out.append(m.with_columns(ano=pl.lit(ano)))
    return pl.concat(out, how="diagonal_relaxed")


def municipios_2026():
    """1º turno do BWeb e 2º turno dos boletins de todas as seções (run_uf_2t.py)."""
    c = classif(2026)
    b = pl.concat([pl.read_parquet(DATA / f"bweb_{u}.parquet", columns=[
        "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO_PERGUNTA", "NR_VOTAVEL", "QT_VOTOS", "QT_APTOS",
        "QT_COMPARECIMENTO"]) for u in UFS if u != "ZZ"]).filter(pl.col("CD_CARGO_PERGUNTA") == "1")
    b = b.with_columns(pl.col("QT_VOTOS", "QT_APTOS", "QT_COMPARECIMENTO").cast(pl.Int64),
                       g=pl.when(pl.col("NR_VOTAVEL").is_in(["95", "96"])).then(pl.lit("BN"))
                       .otherwise(pl.col("NR_VOTAVEL").replace_strict(c, default="OD")))
    s = b.group_by("SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO").agg(
        ap=pl.col("QT_APTOS").first(), co=pl.col("QT_COMPARECIMENTO").first(),
        **{g: pl.col("QT_VOTOS").filter(pl.col("g") == g).sum() for g in G1 if g != "AB"})
    t1 = (s.with_columns(AB=pl.col("ap") - pl.col("co")).group_by(uf="SG_UF", mun=pl.col("CD_MUNICIPIO").str.zfill(5))
          .agg(pl.col(G1).sum()))
    arqs = sorted((DATA / "2t_nacional").glob("bu_*.parquet"))
    bu = pl.concat([pl.read_parquet(p) for p in arqs], how="diagonal_relaxed").filter(pl.col("erro").is_null() & pl.col("aptos").is_not_null())
    t2 = (bu.with_columns(pl.col("uf").str.to_uppercase(), mun=pl.col("mun").str.zfill(5))
          .group_by("uf", "mun").agg(E2=pl.col("v13").sum(), D2=pl.col("v22").sum(), BN2=(pl.col("branco") + pl.col("nulo")).sum(),
                                    AB2=(pl.col("aptos") - pl.col("comparecimento")).sum()))
    print(f"2026: boletins do 2º turno de {len(arqs)} UFs, {bu.height} seções")
    return t1.join(t2, on=["uf", "mun"]).with_columns(ano=pl.lit(2026)), len(arqs)


def proj_simplex(v):
    u = np.sort(v)[::-1]
    c = np.cumsum(u) - 1
    k = np.arange(1, len(v) + 1)
    r = k[u - c / k > 0][-1]
    return np.clip(v - c[r - 1] / r, 0, None)


def ajusta(X, Y, w, B0, ridge=0.002, iters=4000):
    """Mínimos quadrados ponderados, cada linha no simplex, com leve puxão para B0 (grupos minúsculos)."""
    B = B0.copy()
    Xw = X * w[:, None]
    A = Xw.T @ X
    L = np.linalg.eigvalsh(A).max() + ridge * w.sum()
    z, t = B.copy(), 1.0
    for _ in range(iters):
        grad = Xw.T @ (X @ z - Y) + ridge * w.sum() * (z - B0)
        Bn = np.apply_along_axis(proj_simplex, 1, z - grad / L)
        tn = (1 + np.sqrt(1 + 4 * t * t)) / 2
        z, B, t = Bn + (t - 1) / tn * (Bn - B), Bn, tn
    return B


def matrizes(m):
    """Matriz 7x4 por ano e região. B0: transferência "neutra" (finalistas fiéis; o resto dividido)."""
    B0 = np.array([[.95, 0, .02, .03], [0, .95, .02, .03], [.5, .2, .2, .1], [.35, .35, .2, .1], [.2, .5, .2, .1],
                   [.25, .25, .45, .05], [.04, .04, .02, .9]])
    out = {}
    for ano in ANOS:
        x = m.filter(pl.col("ano") == ano).with_columns(reg=pl.col("uf").replace_strict(REGIAO, default="Sudeste"))
        for r in REGIOES:
            z = x.filter((pl.col("reg") == r) & (pl.sum_horizontal(G1) > 0) & (pl.sum_horizontal(["E2", "D2", "BN2", "AB2"]) > 0))
            if z.height < 30:  # região sem dados (2026 enquanto os boletins não chegam): fica a matriz neutra
                out[(ano, r)] = B0
                continue
            ap1 = z.select(G1).sum_horizontal().to_numpy().astype(float)
            ap2 = z.select(["E2", "D2", "BN2", "AB2"]).sum_horizontal().to_numpy().astype(float)
            X = z.select(G1).to_numpy() / ap1[:, None]
            Y = z.select(["E2", "D2", "BN2", "AB2"]).to_numpy() / ap2[:, None]
            out[(ano, r)] = ajusta(X, Y, ap1, B0)
    return out


def logit(p):
    return np.log(p / (1 - p))


def sig(z):
    return 1 / (1 + np.exp(-z))


def prever(m, ano, Bs):
    """Fatia do E entre E e D no 2º turno, aplicando Bs[região] ao 1º turno de cada município do ano."""
    x = m.filter(pl.col("ano") == ano).with_columns(reg=pl.col("uf").replace_strict(REGIAO, default="Sudeste"))
    tot = np.zeros(4)
    for r in REGIOES:
        z = x.filter(pl.col("reg") == r)
        tot += z.select(G1).to_numpy().sum(0) @ Bs[r]
    return tot[0] / (tot[0] + tot[1]), tot


def real(m, ano):
    x = m.filter(pl.col("ano") == ano)
    e, d = x["E2"].sum(), x["D2"].sum()
    e1, d1 = x["E"].sum(), x["D"].sum()
    return e / (e + d), e1 / (e1 + d1)


def main():
    ESTUDO.mkdir(parents=True, exist_ok=True)
    m26, n_uf = municipios_2026()
    m = pl.concat([municipios_hist(), m26], how="diagonal_relaxed").fill_null(0)
    Bs = matrizes(m)
    linhas = []
    for ano in ANOS:
        outros = [a for a in ANOS if a != ano and a < 2026]  # 2026 nunca entra no treino
        Bm = {r: np.mean([Bs[(a, r)] for a in outros], axis=0) for r in REGIOES}
        p_base, _ = prever(m, ano, Bm)
        p_proprio, _ = prever(m, ano, {r: Bs[(ano, r)] for r in REGIOES})
        p_real, h2h = real(m, ano)
        x = m.filter(pl.col("ano") == ano)
        tot1 = x.select(G1).sum().to_numpy()[0]
        validos1 = tot1[:5].sum()
        # taxa nacional de cada grupo para o E e para o D (média das regiões ponderada pelo tamanho do grupo)
        taxa = {}
        for i, g in enumerate(G1):
            pesos = np.array([x.filter(pl.col("uf").replace_strict(REGIAO, default="Sudeste") == r)[g].sum() for r in REGIOES], float)
            taxa[g] = [float(np.average([Bs[(ano, r)][i, k] for r in REGIOES], weights=pesos if pesos.sum() else None)) for k in range(4)]
        linhas.append(dict(ano=ano, nomes=NOMES[ano], governo=GOVERNO[ano], real=p_real, h2h=h2h, base=p_base, ajuste_proprio=p_proprio,
                           res_logit=float(logit(p_real) - logit(p_base)), grupos1={g: float(tot1[i] / validos1) for i, g in enumerate(G1[:5])},
                           taxas=taxa))
        print(f"{ano}: real {p_real * 100:5.2f} · 1º turno entre os dois {h2h * 100:5.2f} · base (outros anos) {p_base * 100:5.2f}"
              f" (erro {(p_base - p_real) * 100:+.2f}) · ajuste do próprio ano {p_proprio * 100:5.2f}")
    # 2026 com outras escolhas de histórico: as três eleições e os pesos do modelo publicado, e só as mais antigas
    variantes = {}
    for nome, pesos in (("site_2014_2022", {2014: 15, 2018: 35, 2022: 50}), ("seis_iguais", {a: 1 for a in ANOS[:-1]}),
                        ("2002_2010", {2002: 1, 2006: 1, 2010: 1}), ("2014_2022_iguais", {2014: 1, 2018: 1, 2022: 1})):
        tot = sum(pesos.values())
        Bv = {r: sum(Bs[(a, r)] * w for a, w in pesos.items()) / tot for r in REGIOES}
        variantes[nome] = float(prever(m, 2026, Bv)[0])
        print(f"2026 com {nome}: {variantes[nome] * 100:.2f}")
    est = dict(anos=linhas, ufs_2026=n_uf, variantes_2026=variantes,
               matrizes={f"{a}|{r}": Bs[(a, r)].round(4).tolist() for a in ANOS for r in REGIOES})
    (ESTUDO / "transferencias.json").write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    print("gravado", ESTUDO / "transferencias.json")


if __name__ == "__main__":
    main()
