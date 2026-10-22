"""Votos para Presidente no 1º turno de 2026 por município, e distribuição das seções (2026 x 2022).

Saída: site/dados/votos.json       municípios (colunar), UFs, candidatos
       site/dados/votos_hist.json  histogramas da fatia de 13 e 22 por seção, 2026 e 2022 (1º turno)
"""
import polars as pl

from comum import DADOS, DATA, REGIAO, UF_IBGE, UFS, baixar_json, gravar_json

CONFIG_MUN = "https://resultados.tse.jus.br/oficial/ele2026/6257/config/mun-e006257-cm.json"
BINS, MINIMO = 50, 50


def secoes():
    b = pl.concat([pl.read_parquet(DATA / f"bweb_{u}.parquet", columns=[
        "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO_PERGUNTA", "NR_VOTAVEL", "NM_VOTAVEL",
        "SG_PARTIDO", "QT_VOTOS", "QT_APTOS", "QT_COMPARECIMENTO"]) for u in UFS]).filter(pl.col("CD_CARGO_PERGUNTA") == "1")
    return b.with_columns(pl.col("QT_VOTOS", "QT_APTOS", "QT_COMPARECIMENTO").cast(pl.Int64),
                          mun=pl.col("CD_MUNICIPIO").str.zfill(5), zona=pl.col("NR_ZONA").str.zfill(4), secao=pl.col("NR_SECAO").str.zfill(4))


def candidatos(b):
    tot = b.group_by("NR_VOTAVEL", "NM_VOTAVEL", "SG_PARTIDO").agg(v=pl.col("QT_VOTOS").sum()).sort("v", descending=True)
    nom = [x for x in tot.iter_rows(named=True) if x["NR_VOTAVEL"] not in ("95", "96")]
    esp = sorted([x for x in tot.iter_rows(named=True) if x["NR_VOTAVEL"] in ("95", "96")], key=lambda x: x["NR_VOTAVEL"])
    return [dict(n=x["NR_VOTAVEL"], nome=x["NM_VOTAVEL"].title() if x["NR_VOTAVEL"] in ("95", "96") else x["NM_VOTAVEL"],
                 partido=None if x["SG_PARTIDO"] == "#NULO#" else x["SG_PARTIDO"], votos=x["v"]) for x in nom + esp]


def centroides():
    """Centro de cada município ponderado pelo número de seções de cada local de votação."""
    lv = pl.read_parquet(DATA / "locais_votacao_BR.parquet").filter(pl.col("NR_TURNO") == "1").select(
        uf=pl.col("SG_UF"), mun=pl.col("CD_MUNICIPIO").str.zfill(5),
        lat=pl.col("NR_LATITUDE").str.replace(",", ".").cast(pl.Float64, strict=False),
        lon=pl.col("NR_LONGITUDE").str.replace(",", ".").cast(pl.Float64, strict=False))
    lv = lv.filter(pl.col("lat").abs() > 0.01)
    return lv.group_by("uf", "mun").agg(pl.col("lat").mean().round(4), pl.col("lon").mean().round(4))


def histos(df):
    val = df.filter(~pl.col("NR_VOTAVEL").is_in(["95", "96"])).group_by("SG_UF", "sec").agg(
        validos=pl.col("QT_VOTOS").sum(),
        v13=pl.col("QT_VOTOS").filter(pl.col("NR_VOTAVEL") == "13").sum(),
        v22=pl.col("QT_VOTOS").filter(pl.col("NR_VOTAVEL") == "22").sum()).filter(pl.col("validos") >= MINIMO)
    out = {}
    for c in ("13", "22"):
        b = val.with_columns(b=(pl.col(f"v{c}") / pl.col("validos") * BINS).floor().clip(0, BINS - 1).cast(pl.Int32))
        for (uf,), g in [(("BR",), b)] + list(b.group_by("SG_UF")):
            arr = [0] * BINS
            for i, n in g.group_by("b").len().iter_rows():
                arr[i] = n
            out.setdefault(uf, {})[c] = arr
    return out


def main():
    b = secoes()
    cands = candidatos(b)
    ordem = {c["n"]: i for i, c in enumerate(cands)}
    cfg = {(u["cd"].upper(), m["cd"]): m for u in baixar_json(CONFIG_MUN)["abr"] for m in u["mu"]}
    sec = b.group_by("SG_UF", "mun", "zona", "secao").agg(pl.col("QT_APTOS", "QT_COMPARECIMENTO").first())
    mun_tot = sec.group_by("SG_UF", "mun").agg(secoes=pl.len(), aptos=pl.col("QT_APTOS").sum(), comp=pl.col("QT_COMPARECIMENTO").sum())
    votos = b.group_by("SG_UF", "mun", "NR_VOTAVEL").agg(pl.col("QT_VOTOS").sum())
    pres = {}
    for uf, mun, n, v in votos.iter_rows():
        pres.setdefault((uf, mun), [0] * len(cands))[ordem[n]] += v
    cen = {(u, m): (la, lo) for u, m, la, lo in centroides().iter_rows()}
    linhas = []
    for x in mun_tot.sort("SG_UF", "mun").iter_rows(named=True):
        k = (x["SG_UF"], x["mun"])
        c = cfg.get(k, {})
        la, lo = cen.get(k, (None, None))
        linhas.append(dict(cod=x["mun"], uf=x["SG_UF"], nome=c.get("nm", "").title(), ibge=int(c["cdi"]) if c.get("cdi") else None,
                           secoes=x["secoes"], aptos=x["aptos"], comp=x["comp"], pres=pres[k], lat=la, lon=lo))
    gravar_json(dict(municipios={k: [r[k] for r in linhas] for k in linhas[0]},
                     ufs={u: dict(regiao=REGIAO[u], ibge=UF_IBGE[u]) for u in UFS}, candidatos=cands,
                     meta=dict(turno=1, dataEleicao="2026-10-04",
                               fonte="https://dadosabertos.tse.jus.br/dataset/resultados-2026-boletim-de-urna")),
                DADOS / "votos.json")
    atual = b.select("SG_UF", sec=pl.concat_str("mun", "zona", "secao", separator="-"), NR_VOTAVEL="NR_VOTAVEL", QT_VOTOS="QT_VOTOS")
    ant = pl.read_parquet(DATA / "hist_2022_votos.parquet").filter((pl.col("NR_TURNO") == "1") & (pl.col("SG_UF") != "ZZ"))
    ant = ant.select("SG_UF", sec=pl.concat_str("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", separator="-"), NR_VOTAVEL="NR_VOTAVEL", QT_VOTOS="QT_VOTOS")
    gravar_json(dict(h2026=histos(atual), h2022=histos(ant), bins=BINS, minimo=MINIMO), DADOS / "votos_hist.json")


if __name__ == "__main__":
    main()
