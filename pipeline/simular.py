"""Roda a simulação de Monte Carlo do 2º turno de 2026 na linha de comando.

É o mesmo algoritmo do simulador da página (site/segundo-turno/), com o mesmo gerador e a mesma semente:
com as opções padrão, dá os mesmos números do site. Só precisa dos arquivos que já estão no repositório
(site/dados/transferencia.json e site/dados/votos.json) e do numpy; não baixa nada.

Exemplos:
  python pipeline/simular.py                              # escolhas-padrão (pesos 15/35/50, erro histórico)
  python pipeline/simular.py --erro 3                     # erro nacional de ±3 pontos
  python pipeline/simular.py --pesos 2022=100             # só a migração de votos de 2022
  python pipeline/simular.py --classif 70=OD,14=OC        # reclassifica candidatos do 1º turno
  python pipeline/simular.py --n 100000 --semente 7 --csv sorteios.csv
  python pipeline/simular.py --abstencao PR=5,SP=3,RJ=3 --vies-abstencao 10   # cenário de chuva

Cenário de abstenção (--abstencao): pontos percentuais do eleitorado de cada estado que deixam de votar no
2º turno além do esperado (por exemplo, por chuva forte). --vies-abstencao diz quanto esses faltosos votariam
no 22 acima (+) ou abaixo (−) da média do estado, em pontos; 0 = faltam igualmente dos dois lados. O efeito é
calculado sobre o cenário médio de cada ano e somado a cada simulação (aproximação: a incerteza do resto do
modelo não muda).

Grupos para --classif: E (esquerda principal), D (direita principal), OE, OC, OD (outros de esquerda,
centro e direita). Números de candidato em site/dados/votos.json ("candidatos").
"""
import argparse
import sys

import numpy as np

import relatorio_simulacao as rs


def efeito_abstencao(T, C, UF, classif, pesos, extra, vies):
    """Quanto a fatia nacional do 22 muda se, em cada estado de `extra`, extra[uf] pontos do eleitorado deixam de
    votar e esses faltosos votariam no 22 `vies` acima da média do estado. Calculado no cenário médio
    (matrizes médias de cada ano, com os pesos), estado a estado."""
    from comum import REGIAO
    tot = sum(pesos.values())
    B = {r: sum(np.array(T["anos"][a]["regioes"][r]["media"]) * w for a, w in pesos.items()) / tot for r in T["regioes"]}
    Y = {u: np.array(rs.grupos_uf(T, C, UF[u], classif), float) @ B[REGIAO[u]] for u in UF}
    fatia = lambda Y: sum(y[1] for y in Y.values()) / sum(y[0] + y[1] for y in Y.values())
    base = fatia(Y)
    for u, dp in extra.items():
        if u not in Y:
            sys.exit(f"estado desconhecido: {u}")
        y = Y[u]
        perda = dp / 100 * UF[u]["aptos"]
        s = min(1.0, max(0.0, y[1] / (y[0] + y[1]) + vies))
        y[1] -= perda * s
        y[0] -= perda * (1 - s)
    return fatia(Y) - base


def main():
    ap = argparse.ArgumentParser(description="Monte Carlo do 2º turno de 2026 (mesmo algoritmo do site).")
    ap.add_argument("--pesos", default="2014=15,2018=35,2022=50", help="peso de cada eleição passada, ex.: 2018=50,2022=50")
    ap.add_argument("--erro", type=float, default=None, help="erro nacional somado, em pontos (padrão: o dos testes, ~1,2)")
    ap.add_argument("--n", type=int, default=rs.N, help="número de simulações (padrão 20000)")
    ap.add_argument("--semente", type=int, default=rs.SEMENTE, help="semente do gerador (padrão: a do site)")
    ap.add_argument("--classif", default="", help="reclassificação, ex.: 70=OD,14=OC")
    ap.add_argument("--abstencao", default="", help="abstenção extra por estado, em pontos do eleitorado, ex.: PR=5,SP=3")
    ap.add_argument("--vies-abstencao", type=float, default=0.0, help="fatia do 22 entre os faltosos menos a do estado, em pontos")
    ap.add_argument("--csv", help="grava a fatia do 22 em cada simulação (ordenada), para histogramas e outras análises")
    a = ap.parse_args()

    T, C, UF, _ = rs.carregar()
    classif = rs.classif_padrao(T, C)
    for par in filter(None, a.classif.split(",")):
        n, g = par.split("=")
        if g not in ("E", "D", "OE", "OC", "OD"):
            sys.exit(f"grupo inválido: {g}")
        classif[n] = g
    pesos = {k: float(v) for k, v in (p.split("=") for p in a.pesos.split(","))}
    sigma = rs.sigma_hist(T) if a.erro is None else a.erro / 100
    rs.SEMENTE = a.semente
    R = rs.rodar(T, C, UF, {"pesos": pesos, "sigma": sigma, "classif": classif, "N": a.n})
    extra = {u.upper(): float(v) for u, v in (p.split("=") for p in filter(None, a.abstencao.split(",")))}
    if extra:
        desvio = efeito_abstencao(T, C, UF, classif, pesos, extra, a.vies_abstencao / 100)
        R["nac"] = np.sort(R["nac"] + desvio)
        R.update(mediana=rs.quantil(R["nac"], 0.5), q05=rs.quantil(R["nac"], 0.05), q95=rs.quantil(R["nac"], 0.95),
                 p22=float((R["nac"] > 0.5).mean()))
        lista = ", ".join(f"{u} +{v:g}" for u, v in extra.items())
        print(f"cenário de abstenção extra ({lista} pontos do eleitorado), viés dos faltosos {a.vies_abstencao:+g} pontos: "
              + f"o 22 muda {desvio * 100:+.2f} pontos".replace(".", ","))

    pct = lambda x: f"{x * 100:.1f}%".replace(".", ",")
    txt_pesos = ", ".join(f"{k}={v:g}" for k, v in pesos.items())
    print(f"{a.n:,} simulações".replace(",", ".") + f" · pesos {txt_pesos} · erro nacional ±{sigma * 100:.2f} pontos".replace(".", ",") + f" · semente {a.semente}")
    print(f"  13 (Lula):             mediana {pct(1 - R['mediana'])}   90% entre {pct(1 - R['q95'])} e {pct(1 - R['q05'])}   passa de 50% em {pct(1 - R['p22'])}")
    print(f"  22 (Flávio Bolsonaro): mediana {pct(R['mediana'])}   90% entre {pct(R['q05'])} e {pct(R['q95'])}   passa de 50% em {pct(R['p22'])}")
    print("  (fatias dos votos válidos; a chance é a fração das simulações em que cada um passa de 50%)")
    if a.csv:
        with open(a.csv, "w", encoding="utf-8") as f:
            f.write("fatia_22\n")
            f.writelines(f"{v:.6f}\n" for v in R["nac"])
        print(f"  sorteios gravados em {a.csv}")


if __name__ == "__main__":
    main()
