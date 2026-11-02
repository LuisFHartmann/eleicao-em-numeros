"""Coletor opcional da noite da apuração: consulta o TSE e publica um snapshot único para o painel ao vivo.

Sem o coletor, cada navegador consulta o TSE direto (o TSE libera CORS). Com muitos visitantes, rode este
script num servidor ou numa máquina ligada à noite e publique site/ao-vivo/dados/vivo_6258.json junto do site
(por exemplo, com git push para o GitHub Pages a cada ciclo). O painel usa o snapshot quando ele tem menos
de 10 minutos e, se não, volta a consultar o TSE.

Uso: python pipeline/coletor.py [--eleicao 6258] [--intervalo 60] [--intervalo-antes 600] [--uma-vez] [--publicar "..."]

Antes da apuração começar (nada apurado e antes de --inicio, 25/10 às 16h55 de Brasília) consulta a cada --intervalo-antes
segundos; depois, a cada --intervalo. O snapshot leva o intervalo, para a página saber quando ele está velho.
"""
import argparse
import json
import subprocess
import time
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from comum import SITE

SAIDA = SITE / "ao-vivo" / "dados"


# O TSE limita requisições por IP (HTTP 429). O coletor faz no máximo TAXA requisições por segundo, somando
# todas as threads, e, se receber 429/503, espera o Retry-After (ou 5, 10, 20... s) antes de tentar de novo.
TAXA = 8.0
_trava, _proxima = threading.Lock(), [0.0]


def _aguardar_vez():
    with _trava:
        agora = time.monotonic()
        vez = max(agora, _proxima[0])
        _proxima[0] = vez + 1 / TAXA
    time.sleep(max(0.0, vez - time.monotonic()))


def get(url, tentativas=8):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "Mozilla/5.0 (eleicaoemnumeros coletor)"})
    for t in range(tentativas):
        _aguardar_vez()
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if t == tentativas - 1 or e.code not in (429, 500, 502, 503, 504):
                raise
            espera = float(e.headers.get("Retry-After") or 0) or min(120, 5 * 2 ** t)
            if e.code == 429:
                with _trava:  # freia todas as threads, não só esta
                    _proxima[0] = max(_proxima[0], time.monotonic() + espera)
            time.sleep(espera)
        except Exception:
            if t == tentativas - 1:
                raise
            time.sleep(2 + 2 * t)


num = lambda s: float(str(s or "0").replace(".", "").replace(",", ".") or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eleicao", default="6258")
    ap.add_argument("--intervalo", type=int, default=60, help="segundos entre consultas durante a apuração")
    ap.add_argument("--intervalo-antes", type=int, default=600, help="segundos entre consultas antes da apuração")
    ap.add_argument("--inicio", default="2026-10-25T16:55", help="a partir de quando (Brasília) usar --intervalo")
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--paralelo", type=int, default=6, help="downloads simultâneos (o total fica limitado a --taxa por segundo)")
    ap.add_argument("--taxa", type=float, default=15.0, help="máximo de requisições por segundo ao TSE")
    ap.add_argument("--max-por-ciclo", type=int, default=900, help="municípios baixados por ciclo, os maiores primeiro")
    ap.add_argument("--publicar", help="comando executado depois de gravar o snapshot (ex.: script de git push)")
    a = ap.parse_args()
    global TAXA
    TAXA = a.taxa
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
    def ciclo():
        nonlocal hist
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

        # maiores primeiro, com teto por ciclo: o que ficar de fora continua "mudado" e entra no próximo ciclo
        pend.sort(key=lambda x: -prior["te"][idx[x[2]]])
        faltam = max(0, len(pend) - a.max_por_ciclo)
        pend = pend[:a.max_por_ciclo]
        with ThreadPoolExecutor(a.paralelo) as ex:
            list(ex.map(ler, pend))
        tot = next((x for x in br["abr"] if x.get("cdabr") == "br"), {})
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        apurado = num(tot.get("s", {}).get("pst")) / 100
        # antes das 16h55 (Brasília) do dia da eleição, e enquanto nada foi apurado, consulta com menos frequência
        inicio = datetime.fromisoformat(a.inicio).replace(tzinfo=timezone(timedelta(hours=-3)))
        espera = a.intervalo_antes if apurado == 0 and datetime.now(timezone.utc) < inicio else a.intervalo
        if faltam:  # ficou fila de municípios: próximo ciclo logo, sem a pausa normal
            espera = 5
        # total nacional oficial (o TSE pode publicar o total antes do detalhe por estado e município)
        try:
            u = get(f"{base}/br/br-c0001-{e6}-u.json")
            cs = {c["n"]: num(c["vap"]) for g in u["carg"][0]["agr"] for p in g["par"] for c in p["cand"]}
            oficial = dict(a=cs.get(prior["rotulos"]["a"], 0), b=cs.get(prior["rotulos"]["b"], 0), st=num(u["s"]["st"]),
                           ts=num(u["s"]["ts"]), apurado=num(u["s"]["pst"]) / 100, hora=f'{u.get("dg")} {u.get("hg")}')
        except Exception as err:
            oficial = None
            print(agora, "ERRO ao ler o total nacional:", repr(err)[:200], flush=True)
        snap = dict(atualizado=agora, horaTSE=tot.get("ht"), apurado=apurado, intervalo=espera, obs=obs, hist=hist, oficial=oficial)
        tmp = alvo.with_suffix(".tmp")
        json.dump(snap, open(tmp, "w", encoding="utf-8"), separators=(",", ":"))
        tmp.replace(alvo)
        # projeção do momento, com o mesmo modelo do navegador, guardada no histórico do snapshot
        subprocess.run(["node", str(SITE.parent / "pipeline" / "projetar_snapshot.js"), str(alvo)], check=False)
        hist = json.load(open(alvo, encoding="utf-8")).get("hist", hist)
        print(agora, "TSE", tot.get("ht"), "apurado", snap["apurado"], "municípios atualizados:", len(pend), f"(faltam {faltam})" if faltam else "", f"próxima consulta em {espera} s", flush=True)
        if a.publicar:
            r = subprocess.run(a.publicar, shell=True, capture_output=True, text=True)
            if r.returncode != 0:
                print(agora, "ERRO ao publicar no R2:", (r.stdout + r.stderr).strip()[-400:], flush=True)
            else:
                print(agora, "publicado", flush=True)
        return espera

    while True:
        try:
            espera = ciclo()
        except Exception as err:  # rede do TSE, JSON incompleto etc.: registra e tenta de novo, sem parar
            print(datetime.now(timezone.utc).isoformat(timespec="seconds"), "ERRO no ciclo:", repr(err)[:400],
                  "· nova tentativa em 30 s", flush=True)
            espera = 30
        if a.uma_vez:
            break
        time.sleep(espera)

if __name__ == "__main__":
    main()
