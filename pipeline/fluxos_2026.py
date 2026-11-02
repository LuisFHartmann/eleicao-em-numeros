"""Para onde foi cada grupo de eleitores do 1º turno de 2026, com todas as seções do país, contra o que o modelo supunha.

1º turno: BWeb por seção. 2º turno: boletim de cada seção (run_uf_2t.py, lido do pacote de urnas do TSE).
Inferência ecológica por região (cada linha da matriz no simplex, mínimos quadrados ponderados pelos aptos),
aplicada aos totais do 1º turno da região; faixa de 90% por bootstrap de seções.
"Esperado" = matrizes do modelo do site (2014, 2018 e 2022 com pesos 15/35/50), aplicadas aos mesmos totais.

Saída: data/estudo/fluxos_2026.json
"""
import json

import numpy as np
import polars as pl

from ao_vivo import matrizes as matrizes_modelo
from comum import DATA, REGIAO, SITE, UFS
from estudo_pos import G1, REGIOES, ajusta

CHAVE = ["uf", "mun", "zona", "secao"]


def secoes():
    cl = json.load(open(SITE / "dados" / "transferencia.json", encoding="utf-8"))["classif2026"]
    b = pl.concat([pl.read_parquet(DATA / f"bweb_{u}.parquet", columns=[
        "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO_PERGUNTA", "NR_VOTAVEL", "QT_VOTOS", "QT_APTOS",
        "QT_COMPARECIMENTO"]) for u in UFS if u != "ZZ"]).filter(pl.col("CD_CARGO_PERGUNTA") == "1")
    b = b.with_columns(pl.col("QT_VOTOS", "QT_APTOS", "QT_COMPARECIMENTO").cast(pl.Int64),
                       g=pl.when(pl.col("NR_VOTAVEL").is_in(["95", "96"])).then(pl.lit("BN"))
                       .otherwise(pl.col("NR_VOTAVEL").replace_strict(cl, default="OD")))
    s1 = b.group_by("SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO").agg(
        ap=pl.col("QT_APTOS").first(), co=pl.col("QT_COMPARECIMENTO").first(),
        **{g: pl.col("QT_VOTOS").filter(pl.col("g") == g).sum() for g in G1 if g != "AB"})
    s1 = s1.select(uf=pl.col("SG_UF"), mun=pl.col("CD_MUNICIPIO").str.zfill(5), zona=pl.col("NR_ZONA").str.zfill(4),
                   secao=pl.col("NR_SECAO").str.zfill(4), ap=pl.col("ap"), AB=pl.col("ap") - pl.col("co"),
                   **{g: pl.col(g) for g in G1 if g != "AB"})
    bu = pl.concat([pl.read_parquet(p) for p in sorted((DATA / "2t_nacional").glob("bu_*.parquet"))], how="diagonal_relaxed")
    bu = (bu.filter(pl.col("erro").is_null() & pl.col("aptos").is_not_null())
          .with_columns(pl.col("uf").str.to_uppercase()).unique(CHAVE, keep="last"))
    d = s1.join(bu, on=CHAVE).filter(pl.col("aptos") == pl.col("ap"))
    return s1, d.with_columns(reg=pl.col("uf").replace_strict(REGIAO))


def main():
    s1, d = secoes()
    s1 = s1.with_columns(reg=pl.col("uf").replace_strict(REGIAO))
    print(f"seções com os dois turnos e mesmos aptos: {d.height} de {s1.height} do 1º turno")
    ap = d["ap"].to_numpy().astype(float)
    X = d.select(G1).to_numpy() / ap[:, None]
    Y = np.c_[d["v13"], d["v22"], d["branco"] + d["nulo"], d["aptos"] - d["comparecimento"]].astype(float) / ap[:, None]
    reg = d["reg"].to_numpy()
    tot = {r: s1.filter(pl.col("reg") == r).select(G1).sum().to_numpy()[0].astype(float) for r in REGIOES}
    Bm, _ = matrizes_modelo({"2014": 15, "2018": 35, "2022": 50})
    B, boots = {}, []
    for r in REGIOES:
        i = reg == r
        B[r] = ajusta(X[i], Y[i], ap[i], Bm[r], ridge=0.0, iters=3000)
        print(r, "ok", flush=True)
    rng = np.random.default_rng(20261025)
    for k in range(20):
        bb = {}
        for r in REGIOES:
            idx = rng.choice(np.where(reg == r)[0], (reg == r).sum())
            bb[r] = ajusta(X[idx], Y[idx], ap[idx], B[r], ridge=0.0, iters=800)
        boots.append(bb)
        print("bootstrap", k + 1, flush=True)
    fl = lambda M: sum(tot[r][:, None] * M[r] for r in REGIOES)  # noqa: E731
    F, Fe, Fb = fl(B), fl(Bm), np.array([fl(bb) for bb in boots])
    # conferência: totais do 2º turno estimados x boletins somados (seções com os dois turnos)
    real = dict(E=int(d["v13"].sum()), D=int(d["v22"].sum()))
    out = dict(grupos=G1, destinos=["13", "22", "BN", "AB"], tamanho=[float(v) for v in sum(tot.values())],
               estimado=F.round().tolist(), esperado=Fe.round().tolist(),
               q05=np.percentile(Fb, 5, axis=0).round().tolist(), q95=np.percentile(Fb, 95, axis=0).round().tolist(),
               porRegiao={r: (tot[r][:, None] * B[r]).round().tolist() for r in REGIOES},
               esperadoRegiao={r: (tot[r][:, None] * Bm[r]).round().tolist() for r in REGIOES},
               nSecoes=d.height, conferencia=dict(soma_boletins_13=real["E"], soma_boletins_22=real["D"]))
    (DATA / "estudo" / "fluxos_2026.json").write_text(json.dumps(out), encoding="utf-8")
    nomes = dict(E="13 no 1º", D="22 no 1º", OE="outros esq.", OC="centro", OD="outros dir.", BN="branco/nulo", AB="abstenção")
    print("\nlinha: estimado (esperado pelo modelo) em % do grupo -> 13 | 22 | BN | AB")
    for i, g in enumerate(G1):
        p, q = F[i] / F[i].sum() * 100, Fe[i] / Fe[i].sum() * 100
        print(f"  {nomes[g]:<13} " + " | ".join(f"{p[k]:5.1f} ({q[k]:5.1f})" for k in range(4)))
    print(f"margem 13-22 estimada {(F[:, 0] - F[:, 1]).sum() / 1e6:+.2f} mi · esperada {(Fe[:, 0] - Fe[:, 1]).sum() / 1e6:+.2f} mi")


if __name__ == "__main__":
    main()
