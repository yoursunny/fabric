import ipaddress
import shlex
import typing as T
from collections import defaultdict

import yaml
from fabrictestbed.slice_editor import Labels
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
    assert net.fim_network_service.type == ServiceType.FABNetv4Ext
    ips = net.get_available_ips(count=len(net.get_interfaces()))

    labels = net.fim_network_service.labels
    if labels is None:
        labels = Labels()
    labels = Labels.update(labels, ipv4=[str(ip) for ip in ips])

    net.fim_network_service.set_properties(labels=labels)


def modify(slice: Slice) -> None:
    """
    Modify slice to request public IPv4 addresses.
    This should be called on a retrieved slice after initial slice creation.
    """
    for net in slice.get_networks():
        if net.get_name().startswith(net_prefix):
            modify_network(net)


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
    assert net.fim_network_service.type == ServiceType.FABNetv4Ext
    ips = net.fim_network_service.labels.ipv4
    assert len(ips) >= len(net.get_interfaces())
    execute_threads = {}
    for i, intf in enumerate(net.get_interfaces()):
        node = intf.get_node()
        intf_ip = ips[i]
        assoc[node.get_name()] = intf_ip
        netplan_conf = build_netplan_conf(intf, intf_ip, net)
        execute_threads[node] = node.execute_thread(f'''
            echo {shlex.quote(netplan_conf)} | sudo tee /etc/netplan/64-v4pub.yaml
            sudo netplan apply
        ''')
    for thread in execute_threads.values():
        thread.result()


def enable(slice: Slice) -> T.Dict[str, str]:
    """
    Enable IPv4 Internet access.
    This should be called after slice is created and modified.
    Its result is persisted and can survive node reboots.
    Returns a dict where each key is a node name and the value is node IP address.
    """
    assoc = {}
    for net in slice.get_networks():
        if net.get_name().startswith(net_prefix):
            enable_on_network(net, assoc)
    return assoc
