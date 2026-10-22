import json, re, os
from PIL import Image
DIR = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(DIR, "..", "..", "site", "ao-vivo", "como-ler")
M = json.load(open(os.path.join(DIR, "marcadores.json")))
t = open(os.path.join(DIR, "como-ler.tpl.html")).read()
def dim(nome):
    return Image.open(os.path.join(SITE, nome)).size
def pic(m):
    fig, alt = m.group(1), m.group(2)
    out = []
    for tema in ("claro", "escuro"):
        d, ta, mo = f"painel-{fig}-1280-{tema}.webp", f"painel-{fig}-768-{tema}.webp", f"painel-{fig}-390-{tema}.webp"
        (wd, hd), (wt, ht), (wm, hm) = dim(d), dim(ta), dim(mo)
        out.append(f'<picture class="so-{tema}"><source media="(max-width: 640px)" srcset="{mo}" width="{wm}" height="{hm}"><source media="(max-width: 1100px)" srcset="{ta}" width="{wt}" height="{ht}"><img src="{d}" width="{wd}" height="{hd}" alt="{alt}"{" loading=\"lazy\"" if tema == "escuro" or fig != "placar" else ""} decoding="async"></picture>')
    return "".join(out)
def mk(m):
    fig, k, n = m.group(1), m.group(2), m.group(3)
    v = M[fig][k]
    return f'<span class="mk" style="--x:{v["1280"][0]}%;--y:{v["1280"][1]}%;--xt:{v["768"][0]}%;--yt:{v["768"][1]}%;--xm:{v["390"][0]}%;--ym:{v["390"][1]}%" aria-hidden="true">{n}</span>'
t = re.sub(r"\{\{pic (\w+) ([^}]+)\}\}", pic, t)
t = re.sub(r"\{\{mk (\w+) (\w+) (\d+)\}\}", mk, t)
t = t.replace("{{seta}}", '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
assert "{{" not in t
open(os.path.join(SITE, "index.html"), "w").write(t)
print("ok", len(t))
