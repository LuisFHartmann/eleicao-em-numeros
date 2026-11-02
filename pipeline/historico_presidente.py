"""Resultado para presidente por município, 1º e 2º turno, de 2002 a 2022 (TSE, dados abertos).

Lê dois arquivos por ano, sem gravar o bruto: votação por candidato e detalhe da votação (aptos, comparecimento,
brancos e nulos), ambos por município e zona. Grava data/historico_presidente.parquet: uma linha por
ano, turno, UF, município e "votável" (número do candidato, 'BRANCO', 'NULO' ou 'ABSTENCAO'), com o total de
aptos do município na mesma linha.

Uso: python pipeline/historico_presidente.py
"""
import polars as pl

from comum import DATA, csv_do_zip

ODSELE = "https://cdn.tse.jus.br/estatistica/sead/odsele"

ANOS = [2002, 2006, 2010, 2014, 2018, 2022]


def numero(c):
    return pl.col(c).str.replace_all(r"\D", "").cast(pl.Int64)


def candidatos(ano):
    def reduzir(df):
        q = "QT_VOTOS_NOMINAIS_VALIDOS" if "QT_VOTOS_NOMINAIS_VALIDOS" in df.columns else "QT_VOTOS_NOMINAIS"
        return (df.filter(pl.col("CD_CARGO") == "1")
                .group_by("NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_CANDIDATO")
                .agg(nome=pl.col("NM_URNA_CANDIDATO").first(), partido=pl.col("SG_PARTIDO").first(), votos=numero(q).sum()))
    df = csv_do_zip(f"{ODSELE}/votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip", reduzir,
                    nome=f"votacao_candidato_munzona_{ano}_{'BR' if ano < 2014 else 'BRASIL'}.csv")
    return (df.group_by("NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_CANDIDATO")
            .agg(pl.col("nome").first(), pl.col("partido").first(), pl.col("votos").sum())
            .rename({"NR_CANDIDATO": "votavel"}))


def detalhe(ano):
    def reduzir(df):
        cols = {"QT_APTOS": "aptos", "QT_COMPARECIMENTO": "comparecimento", "QT_VOTOS_BRANCOS": "BRANCO"}
        nulo = "QT_TOTAL_VOTOS_NULOS" if "QT_TOTAL_VOTOS_NULOS" in df.columns else "QT_VOTOS_NULOS"
        return (df.filter(pl.col("CD_CARGO") == "1")
                .group_by("NR_TURNO", "SG_UF", "CD_MUNICIPIO")
                .agg(*[numero(c).sum().alias(a) for c, a in cols.items()], numero(nulo).sum().alias("NULO")))
    df = csv_do_zip(f"{ODSELE}/detalhe_votacao_munzona/detalhe_votacao_munzona_{ano}.zip", reduzir,
                    nome=f"detalhe_votacao_munzona_{ano}_{'BR' if ano < 2014 else 'BRASIL'}.csv")
    return df.group_by("NR_TURNO", "SG_UF", "CD_MUNICIPIO").agg(pl.all().sum())


def main():
    partes = []
    for ano in ANOS:
        c, d = candidatos(ano), detalhe(ano)
        d = d.with_columns(ABSTENCAO=pl.col("aptos") - pl.col("comparecimento"))
        extra = d.unpivot(index=["NR_TURNO", "SG_UF", "CD_MUNICIPIO"], on=["BRANCO", "NULO", "ABSTENCAO"],
                          variable_name="votavel", value_name="votos")
        x = pl.concat([c.select("NR_TURNO", "SG_UF", "CD_MUNICIPIO", "votavel", "nome", "partido", "votos"),
                       extra.with_columns(nome=pl.col("votavel"), partido=pl.lit(None, pl.String))], how="diagonal_relaxed")
        x = x.join(d.select("NR_TURNO", "SG_UF", "CD_MUNICIPIO", "aptos"), on=["NR_TURNO", "SG_UF", "CD_MUNICIPIO"], how="left")
        partes.append(x.with_columns(ano=pl.lit(ano), turno=pl.col("NR_TURNO").cast(pl.Int8)).drop("NR_TURNO"))
        nac = x.filter(~pl.col("votavel").is_in(["BRANCO", "NULO", "ABSTENCAO"])).group_by("NR_TURNO", "nome").agg(pl.col("votos").sum())
        nac = nac.with_columns(pct=pl.col("votos") / pl.col("votos").sum().over("NR_TURNO") * 100).sort("NR_TURNO", "votos", descending=[False, True])
        print(ano, [(r[0], r[1], round(r[3], 2)) for r in nac.iter_rows() if r[3] > 1])
    out = pl.concat(partes, how="diagonal_relaxed").rename({"SG_UF": "uf", "CD_MUNICIPIO": "mun"})
    out.write_parquet(DATA / "historico_presidente.parquet")
    print("gravado", DATA / "historico_presidente.parquet", out.height)


if __name__ == "__main__":
    main()
