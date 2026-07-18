#!/bin/bash
# Generates realistic traffic against brewlog: mostly valid orders, some menu
# browsing, occasional bogus drinks (400s). Brew failures (5xx) happen on
# their own inside the app.
set -u
DRINKS=(espresso americano latte cappuccino pour_over)
N="${1:-200}"

for i in $(seq 1 "$N"); do
  r=$((RANDOM % 10))
  if [ "$r" -lt 2 ]; then
    curl -s -o /dev/null http://127.0.0.1:8001/menu
  elif [ "$r" -lt 9 ]; then
    drink="${DRINKS[$((RANDOM % ${#DRINKS[@]}))]}"
    curl -s -o /dev/null -X POST http://127.0.0.1:8001/order \
      -H 'Content-Type: application/json' -d "{\"drink\": \"$drink\"}"
  else
    curl -s -o /dev/null -X POST http://127.0.0.1:8001/order \
      -H 'Content-Type: application/json' -d '{"drink": "matcha"}'
  fi
  sleep "0.$((RANDOM % 5))"
done
echo "sent $N requests"
