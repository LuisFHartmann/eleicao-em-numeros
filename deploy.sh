#!/usr/bin/env bash
# Publica o site no Cloudflare Pages (rodar uma vez, e de novo só quando o site mudar).
# O snapshot ao vivo NÃO vai junto: ele é servido do R2 pela Function em /vivo/. Por isso os
# vivo_*.json locais saem da pasta durante o upload e voltam depois.
# SEM_R2=1 ./deploy.sh  publica sem o vínculo com o R2 (antes de o R2 estar ativado na conta);
#                       nesse caso cada navegador lê o TSE direto.
set -euo pipefail
cd "$(dirname "$0")"
GUARDA=$(mktemp -d)
restaura() {
  mv "$GUARDA"/vivo_*.json site/ao-vivo/dados/ 2>/dev/null || true
  [ -f "$GUARDA/wrangler.toml" ] && mv "$GUARDA/wrangler.toml" wrangler.toml
  rm -rf "$GUARDA"
}
trap restaura EXIT
mv site/ao-vivo/dados/vivo_*.json "$GUARDA"/ 2>/dev/null || true
if [ "${SEM_R2:-0}" = "1" ]; then
  cp wrangler.toml "$GUARDA/wrangler.toml"
  sed -i '/^\[\[r2_buckets\]\]/,$d' wrangler.toml
fi
npx --yes wrangler@3 pages deploy site --project-name eleicaoemnumeros --branch main --commit-dirty=true
