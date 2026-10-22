# Eleição em Números

Eleição presidencial de 2026 contada com dados públicos do TSE: mapa de votos do 1º turno, a curva da apuração (e o que acontece com a "virada" quando todos os estados apuram no mesmo ritmo), uma simulação do 2º turno pela migração de votos de 2014, 2018 e 2022 e um painel que projeta, durante a apuração do 2º turno, o resultado final.

Projeto independente e apartidário. O resultado oficial é sempre o do TSE.

## Páginas (`site/`)

| Página | O que mostra |
|---|---|
| `votos/` | Votação para Presidente por região, estado e município; distribuição das seções em 2026 e 2022 |
| `apuracao/` | Curva da apuração reconstruída pela hora de chegada de cada boletim; versão "mesmo ritmo em todos os estados" |
| `segundo-turno/` | Monte Carlo do 2º turno (20 mil sorteios) com pesos e classificação de candidatos ajustáveis |
| `ao-vivo/` | Contagem e projeção do resultado final na noite de 25/10/2026; ensaio com a noite real de 2022 e com uma noite simulada |
| `metodologia/` | Dados, premissas, testes e limitações |

O site é estático. Na noite da apuração o navegador consulta a API de divulgação do TSE diretamente (o TSE libera CORS) e baixa só os municípios que mudaram desde a última consulta.

## Reproduzir

Requer Python 3.11+ (`polars`, `numpy`) e Node 18+ (só para o teste do modelo ao vivo).

```sh
python pipeline/baixar.py          # dados abertos do TSE, lidos em memória; grava só tabelas reduzidas em data/
python pipeline/votos.py           # site/dados/votos.json e votos_hist.json
python pipeline/curva_apuracao.py  # site/apuracao/dados/curva.json
python pipeline/transferencia.py   # site/dados/transferencia.json (migração de votos; alguns minutos)
python pipeline/ao_vivo.py         # site/ao-vivo/dados: esperado por município, noite de 2022, noite simulada
node   pipeline/teste_ao_vivo.js replay_2022   # testa a projeção na noite real de 2022
python -m http.server -d site 8000
```

Os scripts rodam de dentro de `pipeline/` ou da raiz do repositório (os caminhos são resolvidos a partir de `pipeline/comum.py`).

## No ar (Cloudflare Pages + R2)

```
PC do autor: pipeline/coletor.py --(a cada 60 s)--> R2 "apuracao" (vivo_6258.json)
Cloudflare Pages: site/ estático + Function /vivo/6258.json (lê o R2, mesma origem, sem CORS)
Navegador: lê /vivo/6258.json; se faltar ou tiver mais de 10 min, consulta o TSE direto
```

Sem servidor próprio nem banco de dados: o snapshot é um arquivo só, e o plano gratuito da Cloudflare cobre as gravações e leituras de uma noite com folga.

Uma vez (requer Node 18+; o `wrangler@3` roda no Node 18):

```sh
npx --yes wrangler@3 login                       # abre o navegador para autorizar a conta Cloudflare
npx --yes wrangler@3 r2 bucket create apuracao
./deploy.sh                                      # cria o projeto na 1ª vez e publica em https://eleicaoemnumeros.pages.dev
```

Depois do 1º deploy, ligue o bucket à Function: painel da Cloudflare → Workers & Pages → eleicaoemnumeros → Settings → Bindings → R2 bucket, nome `VIVO`, bucket `apuracao` (o `wrangler.toml` já declara isso; confira que aparece) e publique de novo com `./deploy.sh`.

Na noite da apuração, deixe rodando no computador, de dentro de `publico/`:

```sh
cd pipeline && ../../.venv/bin/python coletor.py --publicar "../publicar_vivo.sh 6258"
```

Ensaio com o 1º turno (já apurado): `coletor.py --eleicao 6257 --uma-vez --publicar "../publicar_vivo.sh 6257"` e abrir `https://eleicaoemnumeros.pages.dev/ao-vivo/?fonte=vivo&eleicao=6257` (o status deve dizer "coletor").

Sem o coletor o site continua funcionando: cada navegador consulta o TSE direto (o TSE libera CORS).

## Licença

Código, textos e páginas: todos os direitos reservados. O repositório é público para conferência e reprodução dos resultados, não para reuso. Os dados derivados (pastas `dados/` do site) são abertos sob CC BY 4.0. Detalhes em [LICENSE.md](LICENSE.md).

## Fontes

- Boletins de urna e resultados por seção: [dados abertos do TSE](https://dadosabertos.tse.jus.br/)
- Resultados em tempo real: [resultados.tse.jus.br](https://resultados.tse.jus.br/oficial/app/index.html)
- Malhas municipais: [IBGE](https://servicodados.ibge.gov.br/api/docs/malhas)
- d3.js 7.9.0 (licença ISC), em `site/vendor/`
