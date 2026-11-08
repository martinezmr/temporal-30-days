#!/usr/bin/env bash
# Reach the cEOS lab through a jump host when its management IPs aren't routable from your laptop.
#
# Opens SSH local port forwards for each device (eAPI 443 and SSH 22) and prints the
# DEVICE_HOSTS line to put in .env. Leave it running in its own terminal; Ctrl-C closes the tunnels.
#
#   JUMP_HOST=containerlab lab/tunnels.sh
#   JUMP_HOST=me@10.0.0.5 DEVICE_IPS="bos-rtr-01=172.17.0.3,bos-acc-01=172.17.0.5,..." lab/tunnels.sh
#
# JUMP_HOST is anything `ssh` accepts (an alias from ~/.ssh/config works).
# DEVICE_IPS defaults to the static management IPs in lab/ceos-clab.clab.yml.
set -euo pipefail
JUMP_HOST="${JUMP_HOST:?set JUMP_HOST to your jump host, e.g. JUMP_HOST=containerlab}"
DEVICE_IPS="${DEVICE_IPS:-bos-rtr-01=172.20.20.2,bos-acc-01=172.20.20.3,nyc-rtr-01=172.20.20.4,nyc-acc-01=172.20.20.5}"

forwards=()
hosts=()
n=1
IFS=',' read -ra pairs <<< "$DEVICE_IPS"
for pair in "${pairs[@]}"; do
  name="${pair%%=*}"
  ip="${pair#*=}"
  eapi_port=$((8440 + n))
  ssh_port=$((2200 + n))
  forwards+=(-L "127.0.0.1:${eapi_port}:${ip}:443" -L "127.0.0.1:${ssh_port}:${ip}:22")
  hosts+=("${name}=127.0.0.1:${eapi_port}:${ssh_port}")
  n=$((n + 1))
done

echo "Put this in .env:"
echo
echo "DEVICE_HOSTS=$(IFS=','; echo "${hosts[*]}")"
echo
echo "Tunnels open via ${JUMP_HOST}. Ctrl-C to close."
exec ssh -N -o ExitOnForwardFailure=yes "${forwards[@]}" "$JUMP_HOST"
