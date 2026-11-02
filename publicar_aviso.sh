#!/usr/bin/env bash
# Publica os avisos (site/dados/avisos.json) no R2, sem novo deploy do site. As páginas releem a cada 2 min.
set -euo pipefail
cd "$(dirname "$0")"
../.venv/bin/python -c "import json; json.load(open('site/dados/avisos.json'))"   # JSON válido antes de subir
npx --yes wrangler@3 r2 object put "apuracao/avisos.json" --file site/dados/avisos.json --content-type application/json >/dev/null
echo "avisos publicados"
