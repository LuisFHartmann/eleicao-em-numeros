"""Saúde do coletor durante a noite: última linha de cada tipo no log, idade do último ciclo e o que o site
está servindo em /vivo/. Uso: python pipeline/checar_coletor.py [6258]"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ELE = sys.argv[1] if len(sys.argv) > 1 else "6258"
LOG = Path(__file__).resolve().parents[1] / "logs" / f"coletor_{ELE}.log"
agora = datetime.now(timezone.utc)
idade = lambda iso: (agora - datetime.fromisoformat(iso)).total_seconds() / 60

linhas = LOG.read_text(encoding="utf-8", errors="replace").splitlines() if LOG.exists() else []
ciclos = [l for l in linhas if " TSE " in l and "apurado" in l]
erros = [l for l in linhas if "ERRO" in l]
print(f"log: {LOG} ({len(linhas)} linhas, {len(ciclos)} ciclos, {len(erros)} erros)")
if ciclos:
    print(f"último ciclo há {idade(ciclos[-1].split()[0]):.1f} min: {ciclos[-1]}")
if erros:
    print("último erro:", erros[-1][:300])
reinicios = [l for l in linhas if "iniciando coletor" in l]
print(f"inícios do coletor: {len(reinicios)}")
try:
    with urllib.request.urlopen(urllib.request.Request(f"https://eleicaoemnumeros.pages.dev/vivo/{ELE}.json",
                                                       headers={"Cache-Control": "no-cache", "User-Agent": "Mozilla/5.0 (checar_coletor)"}), timeout=30) as r:
        d = json.loads(r.read())
    print(f"site (/vivo/{ELE}.json): atualizado há {idade(d['atualizado']):.1f} min · TSE {d.get('horaTSE') or '—'} · "
          f"apurado {d.get('apurado', 0) * 100:.2f}% · intervalo {d.get('intervalo')} s · histórico {len(d.get('hist', []))} pontos")
except Exception as e:
    print(f"site (/vivo/{ELE}.json): indisponível ({e})")
