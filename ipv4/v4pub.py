import ipaddress
import shlex
import typing as T
from collections import defaultdict

import yaml
from fabrictestbed_extensions.fablib.interface import Interface
from fabrictestbed_extensions.fablib.network_service import (NetworkService,
                                                             ServiceType)
from fabrictestbed_extensions.fablib.slice import Slice

# no need to change anything below

intf_name = 'uplink4'
net_prefix = 'v4pub-net-'


def prepare(slice: Slice, node_names: T.List[str]) -> None:
    """
    Add intfs and networks to a slice.
    This should be called during initial slice creation before slice.submit().
    """
    intfs_by_site = defaultdict(list)
    for node in slice.get_nodes():
        if node.get_name() not in node_names:
            continue
        [intf] = node.add_component(
            model='NIC_Basic', name=intf_name).get_interfaces()[:1]
        intfs_by_site[node.get_site()].append(intf)
    for site, intfs in intfs_by_site.items():
        slice.add_l3network(name=net_prefix+site,
                            interfaces=intfs, type='IPv4Ext')


def modify_network(net: NetworkService) -> None:
    assert net.get_type() == ServiceType.FABNetv4Ext
    ips = net.get_available_ips(count=len(net.get_interfaces()))
    net.make_ip_publicly_routable(ipv4=[str(ip) for ip in ips])


def modify(slice: Slice, *, update=True, submit=True) -> None:
    """
    Modify slice to request public IPv4 addresses.
    This should be called after initial slice creation.
    """
    if update:
        slice.update()
    for net in slice.get_networks():
        if net.get_name().startswith(net_prefix):
            modify_network(net)
    if submit:
        slice.submit(wait=True, progress=False, post_boot_config=False)
        slice.update()


def build_netplan_conf(intf: Interface, intf_ip: ipaddress.IPv4Address, net: NetworkService) -> str:
    return yaml.dump({
        'network': {
            'version': 2,
            'ethernets': {
                intf_name: {
                    'match': {'macaddress': intf.get_mac()},
                    'set-name': intf_name,
                    'mtu': 1500,
                    'addresses': [f'{intf_ip}/{net.get_subnet().prefixlen}'],
                    'routes': [{
                        'to': '0.0.0.0/1',
                        'via': str(net.get_gateway())
                    }, {
                        'to': '128.0.0.0/1',
                        'via': str(net.get_gateway())
                    }]
                }
            }
        }
    })


def enable_on_network(net: NetworkService, assoc: T.Dict[str, str]) -> None:
    assert net.get_type() == ServiceType.FABNetv4Ext
    ips = net.get_public_ips()
    assert len(ips) >= len(net.get_interfaces())
    execute_threads = {}
    for i, intf in enumerate(net.get_interfaces()):
        node = intf.get_node()
        intf_ip = ips[i]
        assoc[node.get_name()] = f'{intf_ip}'
        netplan_conf = build_netplan_conf(intf, intf_ip, net)
        execute_threads[node] = node.execute_thread(f'''
            echo {shlex.quote(netplan_conf)} | sudo tee /etc/netplan/64-v4pub.yaml
            sudo netplan apply
        ''')
    for thread in execute_threads.values():
        thread.result()


def enable(slice: Slice, *, update=True) -> T.Dict[str, str]:
    """
    Enable IPv4 Internet access.
    This should be called after slice is created and modified.
    Its result is persisted and can survive node reboots.
    Returns a dict where each key is a node name and the value is node IP address.
    """
    if update:
        slice.update()
    assoc = {}
    for net in slice.get_networks():
        if net.get_name().startswith(net_prefix):
            enable_on_network(net, assoc)
    return assoc
