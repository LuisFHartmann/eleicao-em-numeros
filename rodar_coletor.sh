#!/usr/bin/env bash
# Noite da apuração: roda o coletor, publica o snapshot no R2 a cada ciclo, grava tudo em logs/ e
# reinicia sozinho se o processo cair. Parar: Ctrl+C (duas vezes, se estiver no intervalo de reinício).
#   ./rodar_coletor.sh          # 2º turno (6258)
#   ./rodar_coletor.sh 6257     # ensaio com o 1º turno
cd "$(dirname "$0")"
ELE="${1:-6258}"
mkdir -p logs
LOG="logs/coletor_${ELE}.log"
trap 'echo "$(date -Is) parado pelo usuário" | tee -a "$LOG"; exit 0' INT TERM
echo "log em $(pwd)/$LOG"
while true; do
  echo "$(date -Is) iniciando coletor (eleição $ELE)" | tee -a "$LOG"
  ../.venv/bin/python -u pipeline/coletor.py --eleicao "$ELE" --publicar "./publicar_vivo.sh $ELE" 2>&1 | tee -a "$LOG"
  echo "$(date -Is) coletor parou (código ${PIPESTATUS[0]}); reiniciando em 15 s" | tee -a "$LOG"
  sleep 15
done
