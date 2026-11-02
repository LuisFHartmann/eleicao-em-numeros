"""Junta o estudo pós-resultado e gera site/dados/pos_resultado.json (página "Depois do resultado").

Entradas (rodar antes): estudo_pos.py (transferências e previsões deixando um ano de fora), fluxos_2026.py,
estudo_governadores.py e o levantamento de pesquisas em site/dados/pesquisas_historicas.json (rejeição,
aprovação do governo e última pesquisa do 2º turno de cada eleição, com fonte de cada número).

Modelos comparados (fatia do finalista de esquerda entre os dois):
  - 1º turno entre os dois; transferências dos outros anos ("base");
  - base + lado do governo; base + aprovação do governo; base + diferença de rejeição;
  - média das últimas pesquisas; teto pela rejeição; média entre base e pesquisas.
Os ajustes (um coeficiente cada) são estimados sem o ano previsto; 2026 nunca entra em ajuste algum.

Uso: python pipeline/estudo_modelos.py
"""
import json
from datetime import date

import numpy as np

from comum import DATA, SITE, gravar_json

ESTUDO = DATA / "estudo"
SIM_PUBLICADA = dict(p22=0.527, chance22=0.96)  # relatório da simulação do 2º turno (24/10/2026)
PASSADOS = [2002, 2006, 2010, 2014, 2018, 2022]


def logit(p):
    return np.log(p / (1 - p))


def sig(z):
    return 1 / (1 + np.exp(-z))


def pesquisas():
    """Por ano: rejeição (E, D), aprovação (ótimo/bom, ruim/péssimo) e fatia do E nos válidos da última pesquisa."""
    arq = SITE / "dados" / "pesquisas_historicas.json"
    if not arq.exists():
        return {}
    bruto = json.load(open(arq, encoding="utf-8"))
    return {int(a): v for a, v in bruto["anos"].items()}


def ajuste_um(xs, rs):
    """Coeficiente de r = c * x (sem intercepto), por mínimos quadrados."""
    xs, rs = np.asarray(xs, float), np.asarray(rs, float)
    return float((xs * rs).sum() / (xs * xs).sum()) if (xs * xs).sum() > 0 else 0.0


def main():
    tr = json.load(open(ESTUDO / "transferencias.json", encoding="utf-8"))
    anos = {a["ano"]: a for a in tr["anos"]}
    pq = pesquisas()
    for ano, a in anos.items():
        p = pq.get(ano, {})
        a["rej"] = p.get("rejeicao")              # {"E": .., "D": .., "fonte": ..}
        a["aprov"] = p.get("aprovacao")           # {"ob": .., "rp": .., "fonte": ..}
        a["pesq_E"] = p.get("pesquisa_validos_E")  # fatia do E nos válidos (0–1), média das últimas pesquisas
        a["gov"] = a["governo"]
        a["rejdif"] = (a["rej"]["D"] - a["rej"]["E"]) if a["rej"] else None
        a["aprovgov"] = (a["governo"] * (a["aprov"]["ob"] - a["aprov"]["rp"])) if a["aprov"] and a["governo"] else (0 if a["aprov"] else None)

    # cada modelo: função (ano, anos de treino) -> previsão da fatia do E
    def base(ano, treino):
        return anos[ano]["base"]

    def com_ajuste(chave, escala):
        def f(ano, treino):
            if anos[ano][chave] is None:
                return None
            t = [y for y in treino if anos[y][chave] is not None]
            c = ajuste_um([anos[y][chave] / escala for y in t], [anos[y]["res_logit"] for y in t])
            return float(sig(logit(anos[ano]["base"]) + c * anos[ano][chave] / escala))
        return f

    def pesquisa(ano, treino):
        return anos[ano]["pesq_E"]

    def teto(ano, treino):
        r = anos[ano]["rej"]
        return None if not r else (100 - r["E"]) / ((100 - r["E"]) + (100 - r["D"]))

    def media_base_pesq(ano, treino):
        p = anos[ano]["pesq_E"]
        return None if p is None else (anos[ano]["base"] + p) / 2

    modelos = [
        ("1º turno, só entre os dois", "fatia de cada finalista entre os dois no 1º turno, sem transferência", lambda a, t: anos[a]["h2h"]),
        ("Transferências das outras eleições", "o método do site, com as matrizes médias das outras eleições (base)", base),
        ("Base + lado do governo", "base com um ajuste fixo a favor (ou contra) quem é do governo", com_ajuste("gov", 1)),
        ("Base + aprovação do governo", "ajuste proporcional a ótimo/bom − ruim/péssimo, a favor do lado do governo", com_ajuste("aprovgov", 100)),
        ("Base + rejeição", "ajuste proporcional à diferença de rejeição entre os dois finalistas", com_ajuste("rejdif", 100)),
        ("Teto pela rejeição", "fatia = (100 − rejeição) de cada um, dividida pela soma dos dois", teto),
        ("Últimas pesquisas", "média das últimas pesquisas do 2º turno, em votos válidos", pesquisa),
        ("Média entre base e pesquisas", "metade transferências, metade pesquisas", media_base_pesq),
    ]
    saida_modelos = []
    for nome, desc, f in modelos:
        loo, erros = {}, []
        for ano in PASSADOS:
            p = f(ano, [y for y in PASSADOS if y != ano])
            if p is not None:
                loo[ano] = p
                erros.append(abs(p - anos[ano]["real"]) * 100)
        p26 = f(2026, PASSADOS)
        saida_modelos.append(dict(nome=nome, descricao=desc, loo=loo, n=len(erros),
                                  mae=float(np.mean(erros)) if erros else None, max=float(np.max(erros)) if erros else None,
                                  p2026=p26))
        print(f"{nome:<36} erro médio {np.mean(erros) if erros else float('nan'):5.2f} (n={len(erros)}) · 2026: "
              f"{'—' if p26 is None else f'{p26 * 100:.2f}'} (real {anos[2026]['real'] * 100:.2f})")
    (ESTUDO / "modelos.json").write_text(json.dumps(dict(modelos=saida_modelos, anos=anos), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return anos, saida_modelos


def br(x, d=1, sinal=False):
    """Número no padrão brasileiro (vírgula decimal); com sinal, usa + e o sinal de menos tipográfico."""
    t = f"{abs(x):.{d}f}".replace(".", ",") if sinal else f"{x:.{d}f}".replace(".", ",")
    return (("+" if x > 0 else "−" if x < 0 else "") + t) if sinal else t


def mil(n):
    return f"{n:,}".replace(",", ".")


def no_momento(hist, alvo):
    """Primeiro ponto da projeção ao vivo com pelo menos `alvo` das seções apuradas."""
    return next(h for h in hist if h["apurado"] >= alvo)


def montar_pagina(anos, modelos):
    fl = json.load(open(ESTUDO / "fluxos_2026.json", encoding="utf-8"))
    gv = json.load(open(ESTUDO / "governadores.json", encoding="utf-8"))
    viv = json.load(open(SITE / "ao-vivo" / "dados" / "vivo_6258.json", encoding="utf-8"))
    pq26 = json.load(open(SITE / "dados" / "pesquisas.json", encoding="utf-8"))["segundoTurno2026"]
    of = viv["oficial"]
    p13 = of["a"] / (of["a"] + of["b"])
    hist = viv["hist"]
    ini = hist[0]
    ult = [x for x in pq26 if x["fim"] >= "2026-10-18"]
    v22 = [x["v22"] / 100 for x in ult]
    # simulação publicada no relatório de 24/10 (página Simulação do 2º turno): 22 com 52,7% e 96% de chance
    prev = [dict(rotulo="Simulação do 2º turno (relatório de 24/10)", p22=SIM_PUBLICADA["p22"], lo=None, hi=None,
                 nota=f"Monte Carlo a partir do 1º turno e das transferências de 2014, 2018 e 2022; chance do 22: {br(SIM_PUBLICADA['chance22'] * 100, 0)}%"),
            dict(rotulo="Painel ao vivo antes da apuração", p22=ini["mediana"], lo=ini["q05"], hi=ini["q95"],
                 nota="a mesma simulação, com a faixa de 90% usada pelo painel"),
            dict(rotulo=f"Média de {len(ult)} pesquisas (18 a 24/10)", p22=float(np.mean(v22)), lo=min(v22), hi=max(v22),
                 nota="a faixa vai da menor à maior pesquisa, não é margem de erro")]
    for alvo in (.02, .10, .25, .50, .80):
        h = no_momento(hist, alvo)
        prev.append(dict(rotulo=f"Projeção ao vivo com {br(alvo * 100, 0)}% apurado", p22=h["mediana"], lo=h["q05"], hi=h["q95"],
                         nota=f"contagem naquele momento: 22 com {br(h['atual'] * 100, 1)}%"))
    aovivo = [dict(a=h["apurado"], m=h["mediana"], lo=h["q05"], hi=h["q95"], c=h["atual"]) for h in hist if h["atual"] is not None]

    # erro da simulação por grupo, na margem 13 - 22
    G = fl["grupos"]
    erro_m = {g: ((fl["estimado"][i][0] - fl["estimado"][i][1]) - (fl["esperado"][i][0] - fl["esperado"][i][1])) for i, g in enumerate(G)}
    tot_err = sum(erro_m.values())
    nomes = dict(E="votou 13 no 1º turno", D="votou 22 no 1º turno", OE="outros de esquerda", OC="centro (Cury e outros)",
                 OD="outros de direita", BN="branco ou nulo", AB="não foi votar")

    # variáveis do gráfico de resíduos (ponto de vista indicado em cada uma)
    for a in anos.values():
        a["res_pts"] = (a["real"] - a["base"]) * 100
    m = {x["nome"]: x for x in modelos}
    base_loo = m["Transferências das outras eleições"]
    rmse_base = float(np.sqrt(np.mean([(base_loo["loo"][y] - anos[y]["real"]) ** 2 for y in PASSADOS]))) * 100
    from math import erf, sqrt
    chance = lambda centro, dp: 0.5 * (1 + erf((centro - 50) / (dp * sqrt(2))))  # noqa: E731  P(fatia > 50)
    p22_site = SIM_PUBLICADA["p22"] * 100
    vira = max(h["apurado"] for h in hist if h["atual"] is not None and h["apurado"] >= .01 and h["atual"] >= .5)  # último momento com o 22 à frente na contagem
    variaveis = [
        dict(rotulo="Lado do governo", chave="gov", lado=False, eixo="lado do governo no 2º turno", ticks=[-1, 0, 1],
             fmt={"-1": "direita", "0": "nenhum", "1": "esquerda"}, jitter=True, dominio=[-1.3, 1.3],
             legenda="Erro da previsão por transferências (resultado menos previsão, do ponto de vista do finalista de esquerda) contra o lado que estava no governo. Um bônus de continuidade faria os pontos subirem da esquerda para a direita, como na reta tracejada (ajustada de 2002 a 2022). A inclinação existe, mas a dispersão é grande: 2006 ficou 7 pontos acima e 2014 quase 3 abaixo, com o mesmo lado no governo."),
        dict(rotulo="Aprovação do governo", chave="aprovgov", lado=False, eixo="aprovação líquida, do ponto de vista da esquerda",
             legenda="Aprovação líquida do governo (ótimo/bom − ruim/péssimo, Datafolha), com sinal: positiva quando favorece o finalista de esquerda (governo de esquerda bem avaliado, ou de direita mal avaliado). 2010 fica de fora: a aprovação não foi encontrada com fonte."),
        dict(rotulo="Rejeição", chave="rejdif", lado=False, eixo="rejeição da direita − rejeição da esquerda (pontos)",
             legenda="Diferença de rejeição no Datafolha da última semana. Só há dado com fonte a partir de 2014: três anos para estimar e 2026 para conferir."),
    ]
    for v in variaveis:
        t = [y for y in PASSADOS if anos[y][v["chave"]] is not None]
        if len(t) >= 2:
            b, a0 = np.polyfit([anos[y][v["chave"]] for y in t], [anos[y]["res_pts"] for y in t], 1)
            v["reta"] = [float(a0), float(b)]
    hist_anos = [dict(ano=y, nomes=anos[y]["nomes"], governo=anos[y]["governo"], h2h=anos[y]["h2h"], base=anos[y]["base"],
                      real=anos[y]["real"], gov=anos[y]["gov"], aprovgov=anos[y]["aprovgov"], rejdif=anos[y]["rejdif"],
                      aprov=anos[y]["aprov"] and {k: anos[y]["aprov"][k] for k in ("ob", "rp")},
                      rej=anos[y]["rej"] and {k: anos[y]["rej"][k] for k in ("E", "D")}) for y in sorted(anos)]
    for x in modelos:
        x["destaque"] = x["nome"] in ("Teto pela rejeição", "Últimas pesquisas")
    # erro da base do ponto de vista do candidato do governo, nos anos em que houve um
    res_gov = [anos[y]["res_pts"] * anos[y]["governo"] for y in PASSADOS if anos[y]["governo"]]
    pos_gov, n_gov, media_gov = sum(r > 0 for r in res_gov), len(res_gov), float(np.mean(res_gov))
    min_gov, max_gov = min(res_gov), max(res_gov)
    res_gov26 = anos[2026]["res_pts"] * anos[2026]["governo"]
    pesq = m["Últimas pesquisas"]
    teto = m["Teto pela rejeição"]
    textos = dict(
        aovivo=f"A projeção começou em {br(ini['mediana'] * 100, 1)}% para o 22 e, com {br(no_momento(hist, .02)['apurado'] * 100, 0)}% das seções apuradas, já indicava {br(no_momento(hist, .02)['mediana'] * 100, 1)}% (faixa de {br(no_momento(hist, .02)['q05'] * 100, 1)}% a {br(no_momento(hist, .02)['q95'] * 100, 1)}%). Daí em diante, o resultado oficial ficou sempre dentro da faixa (no fim, quando a faixa encolhe a centésimos de ponto, a menos de 0,05 ponto dela). A contagem, que depende da ordem de chegada dos boletins, mostrou o 22 à frente até {br(vira * 100, 0)}% das seções apuradas.",
        erro_margem=f"Quanto cada grupo deu a mais (ou a menos) para a margem do 13 sobre o 22, comparado com o que a simulação supunha, em milhões de votos. Somando os grupos: {br(tot_err / 1e6, 1, True)} milhões. Linha fina: faixa de 90% da estimativa ({mil(fl['nSecoes'])} seções com os dois turnos).",
        erro_taxas="Para cada grupo do 1º turno, a divisão entre 13, 22, branco/nulo e abstenção no 2º turno: a barra clara é o que a simulação supunha; a escura, o que os boletins indicam.",
        nota_historia="Todas as fatias são do finalista de esquerda, entre os dois finalistas. <b>1º turno</b>: a fatia dele entre os dois no 1º turno. <b>Previsão</b>: o método do site sem o próprio ano, com as matrizes de transferência médias das outras eleições (2026 nunca entra na média). <b>Erro</b>: resultado menos previsão, em pontos. <b>Aprovação</b>: ótimo/bom menos ruim/péssimo do governo (os dois entre parênteses). <b>Rejeição</b>: esquerda / direita, em %. Rejeição e aprovação: Datafolha, com fonte de cada número em <a href=\"../dados/pesquisas_historicas.json\">pesquisas_historicas.json</a>. A rejeição de 2002, 2006 e 2010 não foi encontrada com fonte.",
        nota_modelos=f"Erro médio em pontos percentuais da fatia de cada finalista. Modelos com rejeição só podem ser avaliados em 2014, 2018 e 2022 (três anos), e o de aprovação em cinco. Com tão poucos anos, diferenças de menos de 1 ponto entre linhas não querem dizer muito.",
        governadores=f"Cada ponto é um 2º turno para governador de 2002 a 2022 ({gv['n_disputas']} disputas). Em dourado, as {gv['n_com_reeleicao']} em que um dos finalistas era o governador tentando a reeleição, sempre do ponto de vista dele. Acima da diagonal, terminou melhor do que no 1º turno. Descontado o 1º turno, o efeito estimado de concorrer à reeleição é de {br(gv['efeito_pontos'], 1, True)} ponto (faixa de 90%: {br(gv['efeito_q05'], 1, True)} a {br(gv['efeito_q95'], 1, True)}).",
    )
    resumo = [
        f"<b>O resultado:</b> 13 com {br(p13 * 100, 2)}%, 22 com {br((1 - p13) * 100, 2)}%. A simulação dava {br(p22_site, 1)}% ao 22 e as pesquisas da última semana, {br(np.mean(v22) * 100, 1)}% em média. As duas erraram para o mesmo lado.",
        f"<b>A projeção ao vivo</b> passou a indicar o 13 com 2% das seções apuradas e manteve o resultado dentro da faixa até o fim, enquanto a contagem ainda mostrava o 22 à frente até {br(vira * 100, 0)}% apurado.",
        f"<b>Onde a simulação errou:</b> três grupos explicam quase tudo. Quem votou 13 no 1º turno repetiu o voto mais do que o modelo supunha ({br(erro_m['E'] / 1e6, 1, True)} milhões na margem), e quem votou branco, nulo ou não foi votar no 1º turno foi muito mais para o 13 ({br((erro_m['BN'] + erro_m['AB']) / 1e6, 1, True)} milhões). O eleitor de centro também ({br(erro_m['OC'] / 1e6, 1, True)}).",
        f"<b>Rejeição:</b> o \"teto\" pela rejeição (quem não rejeita cada candidato) teria dado {br(teto['p2026'] * 100, 1)}% ao 13, mais perto do resultado que a simulação e as pesquisas, e acertou bem os três anos anteriores com dado. Mas são só três anos.",
        f"<b>Continuidade de governo:</b> há um sinal fraco. Em {pos_gov} das {n_gov} eleições passadas com candidato do governo, ele foi melhor do que o previsto (média de {br(media_gov, 1, True)} ponto, puxada por 2006), e em 2026 também ({br(res_gov26, 1, True)}). Mas, usado como ajuste fixo, piora a previsão do passado; a aprovação do governo piora mais; e nos {gv['n_com_reeleicao']} 2º turnos estaduais com governador tentando a reeleição o efeito foi de {br(gv['efeito_pontos'], 1, True)} ponto.",
        f"<b>A lição principal é sobre a incerteza:</b> prevendo cada eleição sem ela, o método de transferências erra {br(base_loo['mae'], 1)} pontos em média. A simulação usou erro de ±1,2 ponto; com o erro histórico ({br(rmse_base, 1)} pontos), a chance do 22 teria sido de cerca de {br(chance(p22_site, rmse_base) * 100, 0)}%, não 96%.",
    ]
    licoes = [
        f"<b>1. Usar a incerteza que a história mostra.</b> O erro de ±1,2 ponto da simulação vinha só da variação entre 2014, 2018 e 2022. Prevendo cada uma das seis eleições sem ela, o erro típico (raiz do erro quadrático médio) é de {br(rmse_base, 1)} pontos. Com esse erro, a mesma simulação daria ao 22 cerca de {br(chance(p22_site, rmse_base) * 100, 0)}% de chance: favorito, mas longe de certo.",
        f"<b>2. Combinar com as pesquisas.</b> De 2002 a 2022, a média das últimas pesquisas errou {br(pesq['mae'], 1)} ponto em média, menos que as transferências ({br(base_loo['mae'], 1)}). Em 2026 as pesquisas também erraram ({br((pesq['p2026'] - p13) * 100, 1, True)} pontos para o 13), mas menos que a simulação ({br((tr_var('site_2014_2022') - p13) * 100, 1, True)}). A simulação deste site ignorava as pesquisas de propósito, para ser uma referência independente; o histórico mostra que essa independência custa precisão. Uma próxima versão deveria partir do nível nacional das pesquisas e usar as transferências para distribuir o voto pelo território e para a projeção da noite.",
        f"<b>3. Rejeição vale ser acompanhada, com cautela.</b> O teto pela rejeição é simples (cada candidato fica com quem não o rejeita) e acertou 2014, 2018 e 2022 com erro médio de {br(teto['mae'], 1)} ponto; para 2026, dava {br(teto['p2026'] * 100, 1)}% ao 13. É um bom sinal, mas três anos não bastam para virar regra, e as pesquisas medem rejeição de formas diferentes.",
        f"<b>4. Continuidade de governo: acompanhar, mas não como peso fixo.</b> O candidato do governo superou a previsão em {pos_gov} de {n_gov} eleições passadas e em 2026, mas o tamanho varia muito (de {br(min_gov, 1, True)} a {br(max_gov, 1, True)} pontos), um ajuste fixo piora a previsão do passado e a aprovação do governo não ajuda a dizer quando o efeito aparece. Nos governadores, quem tenta a reeleição não ganha mais do que o 1º turno indica. Nos dados de 2026, o que mais pesou foi o comportamento de quem não tinha escolhido candidato no 1º turno.",
        f"<b>5. Usar mais do que três eleições.</b> Com as matrizes das seis eleições em vez de três, a mesma simulação daria {br(tr_var('seis_iguais') * 100, 1)}% ao 13, em vez de {br(tr_var('site_2014_2022') * 100, 1)}%. Ainda erraria o lado, mas por menos.",
    ]
    out = dict(atualizado=date.today().strftime("%d/%m/%Y"), resultado=dict(p13=p13, p22=1 - p13, v13=of["a"], v22=of["b"]),
               inicial=dict(p22=ini["mediana"], lo=ini["q05"], hi=ini["q95"], chance22=ini["pB"]), previsoes=prev, aovivo=aovivo,
               fluxos=dict(grupos=G, nomes=nomes, tamanho=fl["tamanho"], estimado=fl["estimado"], esperado=fl["esperado"],
                           q05=fl["q05"], q95=fl["q95"], nSecoes=fl["nSecoes"]),
               historia=dict(anos=hist_anos, variaveis=variaveis), modelos=modelos,
               governadores={k: gv[k] for k in gv if k != "disputas"} | dict(disputas=[{k: d[k] for k in ("ano", "uf", "a", "a_partido", "b", "b_partido", "h2h1", "fatia2", "reel_a", "reel_b")} for d in gv["disputas"]]),
               textos=textos, resumo=resumo, licoes=licoes)
    gravar_json(out, SITE / "dados" / "pos_resultado.json")


def tr_var(nome):
    return json.load(open(ESTUDO / "transferencias.json", encoding="utf-8"))["variantes_2026"][nome]


if __name__ == "__main__":
    montar_pagina(*main())
