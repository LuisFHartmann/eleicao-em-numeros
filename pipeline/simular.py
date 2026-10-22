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

Grupos para --classif: E (esquerda principal), D (direita principal), OE, OC, OD (outros de esquerda,
centro e direita). Números de candidato em site/dados/votos.json ("candidatos").
"""
import argparse
import sys

import numpy as np

import relatorio_simulacao as rs


def main():
    ap = argparse.ArgumentParser(description="Monte Carlo do 2º turno de 2026 (mesmo algoritmo do site).")
    ap.add_argument("--pesos", default="2014=15,2018=35,2022=50", help="peso de cada eleição passada, ex.: 2018=50,2022=50")
    ap.add_argument("--erro", type=float, default=None, help="erro nacional somado, em pontos (padrão: o dos testes, ~1,2)")
    ap.add_argument("--n", type=int, default=rs.N, help="número de simulações (padrão 20000)")
    ap.add_argument("--semente", type=int, default=rs.SEMENTE, help="semente do gerador (padrão: a do site)")
    ap.add_argument("--classif", default="", help="reclassificação, ex.: 70=OD,14=OC")
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
