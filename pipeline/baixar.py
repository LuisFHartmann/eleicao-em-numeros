"""Baixa (em memória) e reduz os dados abertos do TSE usados pelo site.

Uso: python pipeline/baixar.py            (pula o que já existe em data/)

  data/bweb_{UF}.parquet           boletins de urna do 1º turno de 2026 (Presidente e Governador)
  data/locais_votacao_BR.parquet   locais de votação com coordenadas
  data/hist_{ano}_votos.parquet    votos por seção para Presidente, 2014/2018/2022, dois turnos
  data/hist_{ano}_detalhe.parquet  aptos, comparecimento, brancos e nulos por seção
  data/curva_2022_2t.parquet       hora de chegada de cada boletim no 2º turno de 2022
  data/curva_2022_1t.parquet       idem, 1º turno de 2022: 4 principais, válidos, brancos, nulos e aptos por seção
"""
import io
import sys
import zipfile

import polars as pl

from comum import DATA, UFS, baixar_json, baixar_em_memoria, csv_do_zip

CKAN = "https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-{ano}-boletim-de-urna"
LOCAIS = "https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/eleitorado_local_votacao_2026.zip"
ODSELE = "https://cdn.tse.jus.br/estatistica/sead/odsele"
CHAVE = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]


def bweb_2026():
    urls = {r["url"].split("_")[-2]: r["url"] for r in baixar_json(CKAN.format(ano=2026))["result"]["resources"]
            if "/bweb_1t_" in r["url"] and r["url"].endswith(".zip")}
    for uf in UFS:
        alvo = DATA / f"bweb_{uf}.parquet"
        if not alvo.exists():
            csv_do_zip(urls[uf], lambda df: df.filter(pl.col("CD_CARGO_PERGUNTA").is_in(["1", "3"]))).write_parquet(alvo)
            print("bweb", uf, flush=True)


def locais():
    alvo = DATA / "locais_votacao_BR.parquet"
    if not alvo.exists():
        csv_do_zip(LOCAIS).write_parquet(alvo)


def historico(ano):
    if (DATA / f"hist_{ano}_detalhe.parquet").exists():
        return
    pres = lambda df: df.filter(pl.col("CD_CARGO") == "1")
    z = zipfile.ZipFile(io.BytesIO(baixar_em_memoria(f"{ODSELE}/votacao_secao/votacao_secao_{ano}_BR.zip")))
    v = csv_do_zip(z, lambda df: pres(df).select(CHAVE + ["NR_VOTAVEL", "NM_VOTAVEL", pl.col("QT_VOTOS").cast(pl.Int64)]))
    v.group_by(CHAVE + ["NR_VOTAVEL", "NM_VOTAVEL"]).agg(pl.col("QT_VOTOS").sum()).write_parquet(DATA / f"hist_{ano}_votos.parquet")
    z = zipfile.ZipFile(io.BytesIO(baixar_em_memoria(f"{ODSELE}/detalhe_votacao_secao/detalhe_votacao_secao_{ano}.zip")))
    nomes = z.namelist()
    nome = next((n for n in nomes if n.endswith("_BR.csv")), None) or next(n for n in nomes if n.endswith("_BRASIL.csv"))
    cols = ["QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS"]
    d = csv_do_zip(z, lambda df: pres(df).select(CHAVE + [pl.col(c).cast(pl.Int64) for c in cols]), nome=nome)
    d.group_by(CHAVE).agg(pl.col(cols).sum()).write_parquet(DATA / f"hist_{ano}_detalhe.parquet")
    print("histórico", ano, flush=True)


def curva_2022():
    alvo = DATA / "curva_2022_2t.parquet"
    if alvo.exists():
        return
    urls = [r["url"] for r in baixar_json(CKAN.format(ano=2022))["result"]["resources"] if "_2t_" in r["url"] and r["url"].endswith(".zip")]
    partes = []
    for u in urls:
        partes.append(csv_do_zip(u, lambda df: df.filter(pl.col("CD_CARGO_PERGUNTA") == "1").select(
            "SG_UF", sec=pl.concat_str("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", separator="-"),
            t=pl.col("DT_BU_RECEBIDO").str.to_datetime("%d/%m/%Y %H:%M:%S", strict=False),
            n=pl.col("NR_VOTAVEL"), v=pl.col("QT_VOTOS").cast(pl.Int64))))
    d = pl.concat(partes)
    d.group_by("SG_UF", "sec").agg(pl.col("t").first(), v13=pl.col("v").filter(pl.col("n") == "13").sum(),
                                   v22=pl.col("v").filter(pl.col("n") == "22").sum()).write_parquet(alvo)


def curva_2022_1t():
    """Uma linha por seção: SG_UF, sec, t (DT_BU_RECEBIDO), aptos, v{n} dos 4 mais votados, val (todos os
    nominais), v95 e v96. Cada zip é lido em fatias, e cada fatia já sai somada por seção e número."""
    alvo = DATA / "curva_2022_1t.parquet"
    if alvo.exists():
        return
    urls = [r["url"] for r in baixar_json(CKAN.format(ano=2022))["result"]["resources"]
            if "/bweb_1t_" in r["url"] and r["url"].endswith(".zip")]
    chave = ["SG_UF", "sec", "n"]
    reduzir = lambda df: df.filter(pl.col("CD_CARGO_PERGUNTA") == "1").select(
        "SG_UF", sec=pl.concat_str("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", separator="-"),
        t=pl.col("DT_BU_RECEBIDO").str.to_datetime("%d/%m/%Y %H:%M:%S", strict=False),
        n=pl.col("NR_VOTAVEL"), v=pl.col("QT_VOTOS").cast(pl.Int64), aptos=pl.col("QT_APTOS").cast(pl.Int64)
    ).group_by(chave).agg(pl.col("t").min(), pl.col("v").sum(), pl.col("aptos").first())
    partes = []
    for u in urls:
        partes.append(csv_do_zip(u, reduzir).group_by(chave).agg(pl.col("t").min(), pl.col("v").sum(), pl.col("aptos").first()))
        print("curva 2022 1º turno", u.split("_")[-2], flush=True)
    d = pl.concat(partes)
    nominais = d.filter(~pl.col("n").is_in(["95", "96"]))
    top = nominais.group_by("n").agg(pl.col("v").sum()).sort("v", descending=True).head(4)["n"].to_list()
    d.group_by("SG_UF", "sec").agg(
        pl.col("t").min(), pl.col("aptos").first(),
        *[pl.col("v").filter(pl.col("n") == n).sum().alias(f"v{n}") for n in top + ["95", "96"]],
        val=pl.col("v").filter(~pl.col("n").is_in(["95", "96"])).sum()).write_parquet(alvo)


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    bweb_2026()
    locais()
    for ano in sys.argv[1:] or ["2014", "2018", "2022"]:
        historico(ano)
    curva_2022()
    curva_2022_1t()
