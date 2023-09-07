import ipaddress
import shlex
import typing as T
from collections import defaultdict

import yaml
from fabrictestbed_extensions.fablib.interface import Interface
from fabrictestbed_extensions.fablib.network_service import NetworkService
from fabrictestbed_extensions.fablib.slice import Slice

# WireGuard VPN server dynamic DNS hostname
server_hostname = 'wg-fabric.example.com'
# WireGuard VPN server public key, see v4gateway-wg0.conf [Interface] section
server_pubkey = '0YpMUckXCLDbwlKsMQv2MRyZhOhV4Xvd9VBoaJZEoAA='

# no need to change anything below

intf_name = 'v4wg-intf'
net_name = 'v4wg-net-'
resolved_conf = '''
[Resolve]
DNS=2606:4700:4700::1111 8.8.8.8
Domains=~.
'''


def prepare(slice: Slice):
    """
    Add intfs and networks to a slice.
    This should be called before slice.submit().
    """
    intfs_by_site = defaultdict(list)
    for node in slice.get_nodes():
        [intf] = node.add_component(
            model='NIC_Basic', name=intf_name).get_interfaces()[:1]
        intfs_by_site[node.get_site()].append(intf)
    for site, intfs in intfs_by_site.items():
        slice.add_l3network(name=net_name+site, interfaces=intfs, type='IPv4')


def build_netplan_conf(intf: Interface, intf_ip: ipaddress.IPv4Address, net: NetworkService, client_ip: str, client_pvtkey: str) -> str:
    node = intf.get_node()
    routes = ['0.0.0.0/1', '128.0.0.0/1']
    if ipaddress.ip_address(node.get_management_ip()).version == 4:
        routes = []
    return yaml.dump({
        'network': {
            'version': 2,
            'ethernets': {
                'v4wgnet': {
                    'match': {'macaddress': intf.get_mac()},
                    'set-name': 'v4wgnet',
                    'mtu': 9000,
                    'addresses': [f'{intf_ip}/{net.get_subnet().prefixlen}'],
                    'routes': [{
                        'to': '10.0.0.0/8',
                        'via': str(net.get_gateway())
                    }]
                }
            },
            'tunnels': {
                'v4wg': {
                    'mode': 'wireguard',
                    'key': client_pvtkey,
                    'port': 51820,
                    'peers': [{
                        'endpoint': f'{server_hostname}:51820',
                        'allowed-ips': ['0.0.0.0/0'],
                        'keepalive': 25,
                        'keys': {
                            'public': server_pubkey
                        }
                    }],
                    'mtu': 1500,
                    'addresses': [f'{client_ip}/24'],
                    'routes': [{
                        'to': dst,
                        'via': '255.255.255.64',
                        'on-link': True
                    } for dst in routes]
                }
            }
        }
    })


def enable_on_network(net: NetworkService, clients: T.List[T.Tuple[str, str]], assoc: T.Dict[str, str]) -> None:
    ip_alloc = net.get_available_ips()
    execute_threads = {}
    for intf in net.get_interfaces():
        node = intf.get_node()
        intf_ip = ip_alloc.pop(0)
        client_ip, client_pvtkey = clients.pop()
        assoc[node.get_name()] = client_ip
        netplan_conf = build_netplan_conf(
            intf, intf_ip, net, client_ip, client_pvtkey)
        execute_threads[node] = node.execute_thread(f'''
            echo {shlex.quote(netplan_conf)} | sudo tee /etc/netplan/64-v4wg.yaml
            sudo mkdir -p /etc/systemd/resolved.conf.d
            echo {shlex.quote(resolved_conf)} | sudo tee /etc/systemd/resolved.conf.d/dns.conf
            sudo netplan apply
            sudo systemctl restart systemd-resolved
        ''')
    for thread in execute_threads.values():
        thread.result()


def enable(slice: Slice, clients: T.List[T.Tuple[str, str]], *, update=True) -> T.Dict[str, str]:
    """
    Enable IPv4 Internet access.
    This should be called after slice.submit().
    Its result is persisted and can survive node reboots.
    """
    if update:
        slice.update()
    assoc = {}
    for net in slice.get_networks():
        if net.get_name().startswith(net_name):
            enable_on_network(net, clients, assoc)
    return assoc
