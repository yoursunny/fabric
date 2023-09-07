# FABRIC IPv4 Internet Access

This directory contains scripts for obtaining IPv4 Internet access without relying on the management network interface.
It makes use of [FABNetv4Ext network service](https://learn.fabric-testbed.net/knowledge-base/network-services-in-fabric/#layer-3-services).

Unlike [FABRIC's NAT64 solution](https://learn.fabric-testbed.net/forums/topic/fabric-nat64-solution-obviates-the-need-for-custom-dns-in-ipv6-sites/), these scripts allow you to access IPv4 addresses, in addition to IPv4-only hostnames.
DNS servers are changed to Cloudflare and Google public DNS, which disables FABRIC's NAT64 solution, so that traffic to IPv4-only sites goes over IPv4 instead of the NAT64 gateway.

## v4wg: IPv4 Internet access via WireGuard VPN

This setup creates a WireGuard VPN server with public IPv4 address and allows other slices to access the IPv4 Internet through this VPN server.

* WireGuard VPN server is running in **v4gateway** slice.
  It routes client traffic through NAT gateway to the Internet via FABNetv4Ext network service.
* WireGuard VPN client is installed onto each node that needs IPv4 Internet access.
  They can reach the VPN server via FABNetv4 network service.

This method is suitable for *light* use of IPv4 Internet access, such as cloning from GitHub that still doesn't support IPv6.
It can deliver up to 500 Mbps speeds.

Usage steps:

1. Generate a `v4gateway-wg0.conf` file with `v4gateway-wg0.sh` (see notes within).
2. Create a **v4gateway** slice with `v4gateway.py` script.
   If this slice is dead for any reason, just re-deploy without changing `v4gateway-wg0.conf`, and service will resume.
3. Modify `v4wg.py` (see notes within) and copy it beside each experiment.
4. In each experiment, insert `v4wg.prepare()` and `v4wg.enable()` calls (see example in `demo-v4wg.py`).

It is safe to use this script on nodes that already have IPv4 management address.
In this case, the node would be able to reach other VPN clients via the VPN server, but its Internet connection still goes over the management interface.

## v4pub: IPv4 Internet access via FABNetv4Ext on every node

This setup requests a public IPv4 address on each selected node in a slice.
It is suitable for high-bandwidth IPv4 Internet access, such as communicating with the global NDN testbed.
FABRIC has a limited quantity of public IPv4 addresses in each site, so that you should not use this method for light usage such as downloading from GitHub.

Usage steps:

1. In each experiment, insert `v4pub.prepare()`, `v4pub.modify()`, and `v4pub.enable()` calls (see example in `demo-v4pub.py`).

You should not use this script on nodes that already have IPv4 management address.
Doing so would cause the node to lose management connectivity.

This script will expose the node to the Internet, with the potential of receiving network attacks.
You should perform security hardening, such as enabling the firewall, as soon as possible.
