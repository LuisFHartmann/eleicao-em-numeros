"""Caminhos, listas e utilitários de download compartilhados pelo pipeline público.

Todos os downloads são feitos em memória: só as tabelas reduzidas vão para data/.
"""
import io
import json
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import polars as pl

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
SITE = RAIZ / "site"
DADOS = SITE / "dados"

UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
       "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
REGIAO = {**dict.fromkeys(["AC", "AM", "AP", "PA", "RO", "RR", "TO"], "Norte"),
          **dict.fromkeys(["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"], "Nordeste"),
          **dict.fromkeys(["DF", "GO", "MS", "MT"], "Centro-Oeste"),
          **dict.fromkeys(["ES", "MG", "RJ", "SP"], "Sudeste"),
          **dict.fromkeys(["PR", "RS", "SC"], "Sul")}
UF_IBGE = {"RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17, "MA": 21, "PI": 22, "CE": 23,
           "RN": 24, "PB": 25, "PE": 26, "AL": 27, "SE": 28, "BA": 29, "MG": 31, "ES": 32, "RJ": 33, "SP": 35,
           "PR": 41, "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53}
BLOCO = 64 << 20


def get(url, tentativas=6, cabecalhos=None):
    req = urllib.request.Request(url, headers=cabecalhos or {})
    for t in range(tentativas):
        try:
            return urllib.request.urlopen(req, timeout=300).read()
        except Exception:
            if t == tentativas - 1:
                raise
            time.sleep(2 ** t)


def baixar_json(url):
    return json.loads(get(url))


def get_range(url, a, b):
    dados = get(url, cabecalhos={"Range": f"bytes={a}-{b - 1}"})
    if len(dados) != b - a:
        raise IOError(f"faixa incompleta {len(dados)} de {b - a}")
    return dados


def baixar_em_memoria(url):
    """Arquivo inteiro para a RAM, em blocos paralelos."""
    tam = int(urllib.request.urlopen(urllib.request.Request(url, method="HEAD")).headers["Content-Length"])
    faixas = [(a, min(a + BLOCO, tam)) for a in range(0, tam, BLOCO)]
    buf = bytearray(tam)
    with ThreadPoolExecutor(8) as ex:
        for (a, b), dados in zip(faixas, ex.map(lambda f: get_range(url, *f), faixas)):
            buf[a:b] = dados
    return buf


def csv_do_zip(url_ou_zip, reduzir=None, nome=None, fatia=256 << 20):
    """Lê um CSV (latin-1, ';') de dentro de um zip em fatias, aplicando `reduzir` em cada uma.
    Um CSV de vários GB nunca fica inteiro na memória como tabela."""
    z = url_ou_zip if isinstance(url_ou_zip, zipfile.ZipFile) else zipfile.ZipFile(io.BytesIO(baixar_em_memoria(url_ou_zip)))
    nome = nome or next(n for n in z.namelist() if n.lower().endswith(".csv"))
    partes = []
    with z.open(nome) as f:
        cab, resto = f.readline(), b""
        while True:
            bloco = f.read(fatia)
            fim = not bloco
            bloco = resto + bloco
            if fim:
                resto = b""
            else:
                corte = bloco.rfind(b"\n") + 1
                resto, bloco = bloco[corte:], bloco[:corte]
            if bloco.strip():
                df = pl.read_csv(cab + bloco, separator=";", encoding="latin1", infer_schema_length=0)
                partes.append(reduzir(df) if reduzir else df)
            if fim:
                break
    return pl.concat(partes, how="diagonal_relaxed")


def gravar_json(obj, caminho):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    print(f"{caminho.relative_to(RAIZ)}: {caminho.stat().st_size // 1024} KB")
