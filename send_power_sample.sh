#!/usr/bin/env bash

while true; do
POWER_SAMPLE=$(sudo python3 axpert.py -b)
TRIMMED=$(echo $POWER_SAMPLE | tr -d \")

RES="{ \"channel\": \"m33ra2eb3WHwMhe7v\", \"text\": \"$TRIMMED\" }"
curl -H "X-Auth-Token: zWbA3w-c7QS0X84TCGdeKZZFe2MUDADyW3OqEqwgrFq" -H "X-User-Id: 3sPnwjfskge5i3pXm" -H "Content-type:application/json" https://d-mars.tk/api/v1/chat.postMessage -k -d "$RES"
sleep 9m
done

exit 0
