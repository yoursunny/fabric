import ipaddress
import json
import shlex
import typing as T
from collections import defaultdict

import yaml
from fabrictestbed_extensions.fablib.interface import Interface
from fabrictestbed_extensions.fablib.network_service import NetworkService
from fabrictestbed_extensions.fablib.node import Node
from fabrictestbed_extensions.fablib.slice import Slice

intf_name = 'v4wg-intf'
net_name = 'v4wg-net-'


def add_networks(slice: Slice):
    intfs_by_site = defaultdict(list)
    for node in slice.get_nodes():
        [intf] = node.add_component(
            model='NIC_Basic', name=intf_name).get_interfaces()[:1]
        intfs_by_site[node.get_site()].append(intf)
    for site, intfs in intfs_by_site.items():
        slice.add_l3network(name=net_name+site, interfaces=intfs, type='IPv4')


def build_netplan_conf(node: Node, intf: Interface, intf_ip: ipaddress.IPv4Address, net: NetworkService, server_endpoint: str, server_pubkey: str, client_ip: str, client_pvtkey: str) -> str:
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
                        'endpoint': server_endpoint,
                        'allowed-ips': ['0.0.0.0/0'],
                        'keys': {
                            'public': server_pubkey
                        }
                    }],
                    'mtu': 1500,
                    'addresses': [f'{client_ip}/32'],
                    'routes': [{
                        'to': '0.0.0.0/1',
                        'via': '255.255.255.64',
                        'on-link': True
                    }, {
                        'to': '128.0.0.0/1',
                        'via': '255.255.255.64',
                        'on-link': True
                    }]
                }
            }
        }
    })


def enable_on_network(net: NetworkService, server_endpoint: str, server_pubkey: str, clients: T.List[T.Tuple[str, str]]) -> None:
    ip_alloc = net.get_available_ips()
    subnet = net.get_subnet()
    gateway = net.get_gateway()
    execute_threads = {}
    for intf in net.get_interfaces():
        node = intf.get_node()
        client_ip, client_pvtkey = clients.pop()
        netplan_conf = build_netplan_conf(node, intf, ip_alloc.pop(
            0), net, server_endpoint, server_pubkey, client_ip, client_pvtkey)
        execute_threads[node] = node.execute_thread(f'''
            echo {shlex.quote(netplan_conf)} | sudo tee /etc/netplan/64-v4wg.yaml
            sudo netplan apply
        ''')
    for thread in execute_threads.values():
        thread.result()


def enable(slice: Slice, server_endpoint: str, server_pubkey: str, clients: T.List[T.Tuple[str, str]]) -> None:
    for net in slice.get_networks():
        if net.get_name().startswith(net_name):
            enable_on_network(net, server_endpoint, server_pubkey, clients)
