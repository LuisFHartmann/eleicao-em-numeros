#!/usr/bin/env bash
# Sobe o snapshot ao vivo para o R2 (usado pelo coletor a cada ciclo). Uso: ./publicar_vivo.sh 6258
set -euo pipefail
cd "$(dirname "$0")"
ELE="${1:-6258}"
npx --yes wrangler@3 r2 object put "apuracao/vivo_${ELE}.json" --file "site/ao-vivo/dados/vivo_${ELE}.json" --content-type application/json >/dev/null
