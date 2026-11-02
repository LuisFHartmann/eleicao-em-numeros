"""Leitura mínima do boletim de urna binário (bu.dat, ASN.1/DER) publicado pelo TSE por seção.

Sem biblioteca de ASN.1: um leitor DER genérico monta a árvore e os campos são achados pela posição,
conferida contra o 1º turno (aptos da seção batem com o BWeb). O bu.dat é um envelope cujo conteúdo
(OCTET STRING) é o boletim propriamente dito.
"""

UNIVERSAL_INT, UNIVERSAL_OCTET, UNIVERSAL_STR = 2, 4, 27


def _tlv(b, i):
    t = b[i]
    i += 1
    tag = t & 0x1F
    if tag == 0x1F:
        tag = 0
        while True:
            x = b[i]
            i += 1
            tag = tag << 7 | (x & 0x7F)
            if not x & 0x80:
                break
    n = b[i]
    i += 1
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(b[i:i + k], "big")
        i += k
    return t >> 6, bool(t & 0x20), tag, i, n


class No:
    __slots__ = ("cls", "tag", "filhos", "v")

    def __init__(self, cls, tag, filhos=None, v=None):
        self.cls, self.tag, self.filhos, self.v = cls, tag, filhos, v

    def int(self):
        return int.from_bytes(self.v, "big", signed=True)

    def str(self):
        return self.v.decode("latin1")

    def e(self, cls, tag):
        return self.cls == cls and self.tag == tag


def arvore(b, i=0, fim=None):
    fim = len(b) if fim is None else fim
    nos = []
    while i < fim:
        cls, cons, tag, j, n = _tlv(b, i)
        nos.append(No(cls, tag, arvore(b, j, j + n)) if cons else No(cls, tag, v=bytes(b[j:j + n])))
        i = j + n
    return nos


def _ints(no):
    return [f.int() for f in no.filhos if f.e(0, UNIVERSAL_INT) or f.cls == 2 and f.filhos is None]


def _busca(no, pred):
    if pred(no):
        yield no
    for f in no.filhos or []:
        yield from _busca(f, pred)


def ler_bu(dados: bytes, eleicao: int = 6258) -> dict:
    env = arvore(dados)[0]
    conteudo = next(f for f in env.filhos if f.e(0, UNIVERSAL_OCTET))
    bu = arvore(conteudo.v)[0]
    f = bu.filhos
    r = dict(emissao=f[4].str())
    ab = next(x for x in f if x.e(2, 0) and x.filhos)
    r["abertura"], r["encerramento"] = (x.str() for x in ab.filhos[:2])
    # depois dos horários: um inteiro (total de eleitores habilitados) e [1] com três contagens de habilitação
    k = f.index(ab)
    r["qtd_hab"] = f[k + 1].int() if f[k + 1].e(0, UNIVERSAL_INT) else None
    hab = next((x for x in f[k + 1:] if x.e(2, 1) and x.filhos), None)
    r["hab_1"], r["hab_2"], r["hab_3"] = (_ints(hab) + [None] * 3)[:3] if hab else (None, None, None)
    urna = f[2]
    # carga da urna: SEQUENCE {número interno, código, ..., data da carga, código da carga}
    carga = next((n for n in _busca(urna, lambda n: n.filhos and n.filhos[0].e(0, UNIVERSAL_INT)
                                    and any(x.e(0, UNIVERSAL_STR) and x.v[:4].isdigit() and b"T" in x.v for x in n.filhos))), None)
    r["urna_interno"] = carga.filhos[0].int() if carga else None
    r["urna_carga"] = next((x.str() for x in carga.filhos if x.e(0, UNIVERSAL_STR) and x.v[:4].isdigit()), None) if carga else None
    el = next(_busca(bu, lambda n: n.filhos and len(n.filhos) > 2 and n.filhos[0].e(0, UNIVERSAL_INT)
                     and n.filhos[0].int() == eleicao), None)
    if el is None:
        return r
    r["aptos"] = el.filhos[1].int()
    cargo = next(_busca(el, lambda n: n.filhos and len(n.filhos) >= 3 and n.filhos[0].e(0, 10) and n.filhos[1].e(0, UNIVERSAL_INT)))
    r["comparecimento"] = cargo.filhos[1].int()
    r.update(v13=0, v22=0, v_outros=0, branco=0, nulo=0, v_tipo_outro=0)
    for v in _busca(cargo, lambda n: n.filhos and n.filhos[0].e(2, 1) and len(n.filhos) >= 3 and n.filhos[1].e(2, 2)):
        tipo, qtd = v.filhos[0].int(), v.filhos[1].int()
        if tipo == 1:
            cod = _ints(next(x for x in v.filhos if x.e(2, 3)))[-1]
            r["v13" if cod == 13 else "v22" if cod == 22 else "v_outros"] += qtd
        elif tipo == 2:
            r["branco"] += qtd
        elif tipo == 3:
            r["nulo"] += qtd
        else:
            r["v_tipo_outro"] += qtd
    return r


if __name__ == "__main__":
    import sys
    print(ler_bu(open(sys.argv[1], "rb").read()))
