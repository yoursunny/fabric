#!/bin/bash
set -euo pipefail

# enter the parameters below, then run:
#   bash v4gateway-wg0.sh > v4gateway-wg0.conf
# you may need 'wireguard-tools' package for this script to work

# first three octets of client IPv4 addresses
# pick a RFC1918 subnet that does not conflict with your experiments
IPPREFIX=192.168.164

# https://dns.he.net dynamic DNS hostname and password for the WireGuard server
HEDYN_HOSTNAME=wg-fabric.example.com
HEDYN_PASSWORD=fGx9pTE4T3baoUXg

# no need to change anything below

PVTKEY=$(wg genkey)
PUBKEY=$(echo $PVTKEY | wg pubkey)
echo [Interface]
echo Address = $IPPREFIX.1/24
echo PrivateKey = $PVTKEY
echo '#' PublicKey = $PUBKEY
echo ListenPort = 51820
echo MTU = 1500
echo
echo PostUp = sysctl -w net.ipv4.ip_forward=1
echo PostUp = iptables -I FORWARD -i wg0 -j ACCEPT
echo PostUp = iptables -I FORWARD -o wg0 -j ACCEPT
echo PostUp = iptables -t nat -I POSTROUTING -s $IPPREFIX.0/24 -o uplink4 -j SNAT --to IP-WAN
echo PostUp = http --ignore-stdin -f POST https://dyn.dns.he.net/nic/update hostname=$HEDYN_HOSTNAME password=$HEDYN_PASSWORD myip=IP-LAN
echo
echo PreDown = iptables -D FORWARD -i wg0 -j ACCEPT
echo PreDown = iptables -D FORWARD -o wg0 -j ACCEPT
echo PreDown = iptables -t nat -D POSTROUTING -s $IPPREFIX.0/24 -o uplink4 -j SNAT --to IP-WAN

for I in $(seq 40 89); do
  PVTKEY=$(wg genkey)
  PUBKEY=$(echo $PVTKEY | wg pubkey)
  echo
  echo [Peer]
  echo '#' PrivateKey = $PVTKEY
  echo PublicKey = $PUBKEY
  echo AllowedIPs = $IPPREFIX.$I/32
done
