"""Gera os recortes do painel (replay 2022, k=45) para o guia 'Como ler' e as posições dos marcadores, em %.
Saída: PNG temporário aqui e WebP em site/ao-vivo/como-ler/; marcadores em marcadores.json."""
import io, json, os
from PIL import Image
from cdp import Navegador, DIR

SAIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "site", "ao-vivo", "como-ler")
URL = "ao-vivo/?fonte=replay_2022&k=45"

# âncoras calculadas no navegador, em coordenadas da página
JS = r"""
(() => {
  const pg = r => ({ x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height });
  const fimTexto = el => { const rg = document.createRange(); rg.selectNodeContents(el); const rs = [...rg.getClientRects()]; const r = rs[rs.length - 1]; return { x: r.right + scrollX, y: r.top + r.height / 2 + scrollY }; };
  const noPath = (p, frac) => { const L = p.getTotalLength(), pt = p.getPointAtLength(Math.max(0, Math.min(L, frac * L))), m = p.getScreenCTM(); return { x: m.a * pt.x + m.c * pt.y + m.e + scrollX, y: m.b * pt.x + m.d * pt.y + m.f + scrollY }; };
  const cel = [...document.querySelectorAll("#placar > div")];
  const proj = document.querySelector("#ch-proj svg");
  const paths = [...proj.querySelectorAll("path")];
  const grossas = paths.filter(p => p.getAttribute("stroke-width") === "3");
  const pont = paths.filter(p => p.getAttribute("stroke-dasharray") === "1 3");
  const areas = paths.filter(p => p.getAttribute("fill") && p.getAttribute("fill") !== "none");
  const tracej = [...proj.querySelectorAll("line")].filter(l => l.getAttribute("stroke-dasharray") === "5 4");
  const curva = document.querySelector("#ch-curva svg"), cg = [...curva.querySelectorAll("path")].filter(p => p.getAttribute("stroke-width") === "3");
  const barras = [...document.querySelectorAll("#ch-dist svg rect")].filter(r => +r.getAttribute("height") > 0);
  const alta = barras.reduce((a, b) => +b.getAttribute("height") > +a.getAttribute("height") ? b : a);
  const lt = tracej[0].getBoundingClientRect();
  return {
    rec: { placar: pg(document.getElementById("placar").getBoundingClientRect()), proj: pg(document.getElementById("ch-proj").closest(".panel").getBoundingClientRect()), dois: pg(document.querySelector(".dois").getBoundingClientRect()) },
    a: {
      apurado: fimTexto(cel[0].querySelector(".rot")), contagem: fimTexto(cel[1].querySelector(".rot")), projecao: fimTexto(cel[2].querySelector(".rot")),
      inicial: fimTexto(cel[2].querySelector(".ini > span")), chance: fimTexto(cel[3].querySelector(".rot")),
      grossa: noPath(grossas[1], 0.12), faixa: (() => { const r = areas[1].getBoundingClientRect(); return { x: r.left + scrollX, y: r.bottom + scrollY }; })(), tracejada: { x: lt.left + lt.width * 0.8 + scrollX, y: lt.top + scrollY },
      pontilhada: noPath(pont[1], 0.0), curva: noPath(cg[1], 0.3),
      dist: (() => { const r = barras.reduce((a, b) => +b.getAttribute("x") < +a.getAttribute("x") ? b : a).getBoundingClientRect(); return { x: r.left + scrollX, y: r.bottom + scrollY }; })(),
    },
  };
})()
"""

# deslocamento de cada marcador em relação à âncora (px de layout), por largura
DESL = {
    1280: {"apurado": (20, 0), "contagem": (20, 0), "projecao": (20, 0), "inicial": (22, 0), "chance": (20, 0),
           "grossa": (18, -12), "faixa": (20, -16), "tracejada": (0, -14), "pontilhada": (-16, 6), "curva": (16, -14), "dist": (-18, -26)},
    390: {"apurado": (18, 0), "contagem": (18, 0), "projecao": (16, 0), "inicial": (19, 0), "chance": (18, 0),
          "grossa": (16, -10), "faixa": (4, -10), "tracejada": (0, -12), "pontilhada": (-14, 6), "curva": (14, -12), "dist": (-16, -24)},
}
FIG = {"placar": ["apurado", "contagem", "projecao", "inicial", "chance"], "proj": ["grossa", "faixa", "tracejada", "pontilhada"], "dois": ["curva", "dist"]}
ESCALA = {1280: 1.5, 768: 2, 390: 2}
DESL[768] = dict(DESL[1280])

marc = {}
with Navegador() as n:
    for w in (1280, 768, 390):
        for tema in ("claro", "escuro"):
            n.abrir(URL, w, 900, escuro=tema == "escuro", escala=ESCALA[w], espera=3.5)
            d = n.js(JS)
            for fig, chaves in FIG.items():
                r = d["rec"][fig]
                pad = 1
                clip = {"x": r["x"] - pad, "y": r["y"] - pad, "width": r["w"] + 2 * pad, "height": r["h"] + 2 * pad}
                png = n.foto(f"guia_{fig}_{w}_{tema}.png", clip=clip)
                im = Image.open(png).convert("RGB")
                nome = f"painel-{fig}-{w}-{tema}.webp"
                im.save(os.path.join(SAIDA, nome), "WEBP", quality=80, method=6)
                tam = os.path.getsize(os.path.join(SAIDA, nome))
                print(nome, im.size, f"{tam/1024:.0f} KB")
                if tema == "claro":
                    for k in chaves:
                        a = d["a"][k]; dx, dy = DESL[w][k]
                        px = (a["x"] + dx - clip["x"]) / clip["width"] * 100
                        py = (a["y"] + dy - clip["y"]) / clip["height"] * 100
                        marc.setdefault(fig, {}).setdefault(k, {})[w] = [round(px, 2), round(py, 2)]
                    marc.setdefault("_dim", {})[f"{fig}-{w}"] = [round(clip["width"]), round(clip["height"])]
json.dump(marc, open(os.path.join(DIR, "marcadores.json"), "w"), indent=1)
print(json.dumps(marc))
