"""Resultado do 2º turno de 2026 por seção, lido dos boletins de urna (bu.dat) publicados pelo TSE.

O TSE publica, por UF, um zip com os arquivos de todas as urnas (boletim, registro digital do voto, log...).
Aqui só o boletim interessa: o zip é lido por HTTP Range em janelas, que vão para a memória e são descartadas,
e de cada janela só os *-bu.dat são decodificados (bu.py). Nada bruto é gravado em disco.

Saída: data/2t_nacional/bu_{UF}.parquet (uma linha por seção: aptos, comparecimento, votos no 13 e no 22,
brancos, nulos, horários e número da urna). Usado por estudo_pos.py e fluxos_2026.py.

Uso: python pipeline/boletins_2t.py [UF ...]     (sem argumentos: todas as UFs e o exterior)
"""
import io
import re
import struct
import sys
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor

import polars as pl

from bu import ler_bu
from comum import DATA, UFS, get_range

URL = "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_2t_{uf}.zip"
RE_BU = re.compile(r"o\d{5}([a-z]{2})(\d{5})(\d{4})(\d{4})-(bu|busa)\.dat$")
JANELA = 256 << 20
EM_VOO = 6


class _HTTPArquivo(io.RawIOBase):
    """Arquivo somente-leitura sobre HTTP Range, só para o zipfile ler o diretório central."""

    def __init__(self, url):
        import urllib.request
        self.url, self.pos = url, 0
        self.tam = int(urllib.request.urlopen(urllib.request.Request(url, method="HEAD")).headers["Content-Length"])

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, off, wh=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.tam + off}[wh]
        return self.pos

    def readinto(self, b):
        n = min(len(b), self.tam - self.pos)
        if n <= 0:
            return 0
        b[:n] = get_range(self.url, self.pos, self.pos + n)
        self.pos += n
        return n


def janelas(url):
    """O zip em blocos contíguos de ~256 MB: (início, fim, [membros bu.dat do bloco])."""
    z = zipfile.ZipFile(io.BufferedReader(_HTTPArquivo(url), 4 << 20))
    membros = sorted(z.infolist(), key=lambda i: i.header_offset)
    out, ini, bus = [], None, []
    for k, m in enumerate(membros):
        ini = m.header_offset if ini is None else ini
        if RE_BU.search(m.filename):
            bus.append(m)
        prox = membros[k + 1].header_offset if k + 1 < len(membros) else z.start_dir
        if prox - ini >= JANELA or k + 1 == len(membros):
            out.append((ini, prox, bus))
            ini, bus = None, []
    return out


def extrair(buf, ini, m):
    o = m.header_offset - ini
    n, e = struct.unpack("<HH", buf[o + 26:o + 30])
    d = o + 30 + n + e
    dados = buf[d:d + m.compress_size]
    return zlib.decompress(dados, -15) if m.compress_type == zipfile.ZIP_DEFLATED else bytes(dados)


def uf_inteira(uf):
    url = URL.format(uf=uf)
    js = janelas(url)
    linhas = []
    with ThreadPoolExecutor(EM_VOO) as rede:
        # no máximo EM_VOO janelas na memória ao mesmo tempo
        fila = [rede.submit(get_range, url, a, b) for a, b, _ in js[:EM_VOO]]
        for k, (a, _, bus) in enumerate(js):
            buf = memoryview(fila[k].result())
            fila[k] = None
            if k + EM_VOO < len(js):
                na, nb, _ = js[k + EM_VOO]
                fila.append(rede.submit(get_range, url, na, nb))
            for m in bus:
                u, mun, zona, secao, tipo = RE_BU.search(m.filename).groups()
                try:
                    r = ler_bu(extrair(buf, a, m))
                    r.update(erro=None)
                except Exception as ex:  # boletim do Sistema de Apuração (busa) tem outro formato
                    r = dict(erro=str(ex)[:200])
                r.update(uf=u, mun=mun, zona=zona, secao=secao, tipo_bu=f"{tipo}.dat")
                linhas.append(r)
            del buf
    df = pl.DataFrame(linhas, infer_schema_length=None)
    df.write_parquet(DATA / "2t_nacional" / f"bu_{uf}.parquet")
    print(f"{uf}: {df.height} boletins, 13 = {df['v13'].sum():,}, 22 = {df['v22'].sum():,}", flush=True)


if __name__ == "__main__":
    (DATA / "2t_nacional").mkdir(parents=True, exist_ok=True)
    for uf in sys.argv[1:] or UFS + (["ZZ"] if "ZZ" not in UFS else []):
        uf_inteira(uf)
