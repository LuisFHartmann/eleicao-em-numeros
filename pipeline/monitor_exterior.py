"""Verifica se o TSE já registrou boletins de urna do exterior no 2º turno (pleito 3221) e se os arquivos
de cada seção já estão acessíveis. Só leitura; não grava nada.

No 1º turno, o boletim de Tóquio chegou ao TSE às 6h33 de Brasília, mas o índice que dá o endereço do
arquivo só o registrou às 17h08, e a totalização do exterior começou às 17h20. Este script mostra se isso se
repete. Mesmo que algo apareça cedo, o exterior é pequeno (~330 mil votos válidos) e vota diferente do país.

Uso: python pipeline/monitor_exterior.py
"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221"


def get(url):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    cs = get(f"{BASE}/config/zz/zz-p003221-cs.json")
    secoes = [(m["cd"], m["nm"], z["cd"], s) for u in cs.get("abr", []) for m in u.get("mu", [])
              for z in m.get("zon", []) for s in z.get("sec", [])]
    recebidas = [x for x in secoes if "ha" in x[3]]
    print(f"índice gerado {cs.get('dg')} {cs.get('hg')} · {len(secoes)} seções no exterior · {len(recebidas)} com hora de recebimento")
    if not recebidas:
        return
    for cd, nm, z, s in sorted(recebidas, key=lambda x: x[3]["ha"])[:10]:
        print(f"  {nm:<28} seção {s['ns']}  recebida {s.get('da')} {s['ha']}")

    def aux(x):
        cd, nm, z, s = x
        try:
            d = get(f"{BASE}/dados/zz/{cd}/{z}/{s['ns']}/p003221-zz-m{cd}-z{z}-s{s['ns']}-aux.json")
            return d["hashes"][-1]["st"]
        except Exception:
            return None

    with ThreadPoolExecutor(8) as ex:
        st = list(ex.map(aux, recebidas[:40]))
    print(f"arquivos acessíveis (aux.json) em {sum(1 for v in st if v)} de {len(st)} seções testadas: {sorted(set(filter(None, st)))}")


if __name__ == "__main__":
    main()
