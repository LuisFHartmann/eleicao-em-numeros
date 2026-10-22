"""Coletor opcional da noite da apuração: consulta o TSE e publica um snapshot único para o painel ao vivo.

Sem o coletor, cada navegador consulta o TSE direto (o TSE libera CORS). Com muitos visitantes, rode este
script num servidor ou numa máquina ligada à noite e publique site/ao-vivo/dados/vivo_6258.json junto do site
(por exemplo, com git push para o GitHub Pages a cada ciclo). O painel usa o snapshot quando ele tem menos
de 10 minutos e, se não, volta a consultar o TSE.

Uso: python pipeline/coletor.py [--eleicao 6258] [--intervalo 60] [--uma-vez] [--publicar "git ..."]
"""
import argparse
import json
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from comum import SITE

SAIDA = SITE / "ao-vivo" / "dados"


def get(url):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    for t in range(4):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception:
            if t == 3:
                raise
            time.sleep(1 + t)


num = lambda s: float(str(s or "0").replace(".", "").replace(",", ".") or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eleicao", default="6258")
    ap.add_argument("--intervalo", type=int, default=60)
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--publicar", help="comando executado depois de gravar o snapshot (ex.: script de git push)")
    a = ap.parse_args()
    ele, e6 = a.eleicao, f"e00{a.eleicao}"
    base = f"https://resultados.tse.jus.br/oficial/ele2026/{ele}/dados"
    prior = json.load(open(SAIDA / "prior_2026.json", encoding="utf-8"))
    idx = {f"{u.lower()}{c}": i for i, (u, c) in enumerate(zip(prior["uf"], prior["cod"]))}
    M = len(idx)
    obs = {k: [0.0] * M for k in ("st", "est", "a", "b")}
    visto, hist = {}, []
    alvo = SAIDA / f"vivo_{ele}.json"
    if alvo.exists():
        hist = json.load(open(alvo, encoding="utf-8")).get("hist", [])
    while True:
        br = get(f"{base}/br/br-{e6}-ab.json")
        pend = []
        for u in (x for x in br["abr"] if x.get("tpabr") == "uf" and num(x.get("s", {}).get("st")) > 0):
            uf = u["cdabr"].lower()
            for m in get(f"{base}/{uf}/{uf}-{e6}-ab.json")["abr"]:
                chave = uf + m["cdabr"]
                marca = f"{m['s']['st']}|{m.get('dt')}|{m.get('ht')}" if m.get("tpabr") == "mun" else None
                if marca and num(m["s"]["st"]) > 0 and chave in idx and visto.get(chave) != marca:
                    pend.append((uf, m["cdabr"], chave, marca))
            if uf == "zz" and "zzZZ" in idx:
                pend.append(("zz", None, "zzZZ", f"{u['s']['st']}|{u.get('ht')}"))

        def ler(item):
            uf, cod, chave, marca = item
            d = get(f"{base}/{uf}/{uf}{cod}-c0001-{e6}-u.json" if cod else f"{base}/zz/zz-c0001-{e6}-u.json")
            cands = [c for g in d["carg"][0]["agr"] for p in g["par"] for c in p["cand"]]
            v = lambda n: next((num(c["vap"]) for c in cands if c["n"] == n), 0)
            i = idx[chave]
            obs["a"][i], obs["b"][i] = v(prior["rotulos"]["a"]), v(prior["rotulos"]["b"])
            obs["st"][i] = num(d["s"]["st"])
            obs["est"][i] = num(d["e"].get("est")) or prior["te"][i] * obs["st"][i] / max(1, num(d["s"]["ts"]) or prior["ts"][i])
            visto[chave] = marca

        with ThreadPoolExecutor(24) as ex:
            list(ex.map(ler, pend))
        tot = next((x for x in br["abr"] if x.get("cdabr") == "br"), {})
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        snap = dict(atualizado=agora, horaTSE=tot.get("ht"), apurado=num(tot.get("s", {}).get("pst")) / 100, obs=obs, hist=hist)
        tmp = alvo.with_suffix(".tmp")
        json.dump(snap, open(tmp, "w", encoding="utf-8"), separators=(",", ":"))
        tmp.replace(alvo)
        # projeção do momento, com o mesmo modelo do navegador, guardada no histórico do snapshot
        subprocess.run(["node", str(SITE.parent / "pipeline" / "projetar_snapshot.js"), str(alvo)], check=False)
        hist = json.load(open(alvo, encoding="utf-8")).get("hist", hist)
        print(agora, "TSE", tot.get("ht"), "apurado", snap["apurado"], "municípios atualizados:", len(pend), flush=True)
        if a.publicar:
            subprocess.run(a.publicar, shell=True, check=False)
        if a.uma_vez:
            break
        time.sleep(a.intervalo)


if __name__ == "__main__":
    main()
