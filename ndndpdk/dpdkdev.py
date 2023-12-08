import json
import shlex
import time

from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager
from fabrictestbed_extensions.fablib.interface import Interface

import ndndpdk_common
import v4wg

# how many nodes to create
NODE_COUNT = 2
# FABRIC sites for nodes, will be used successively for each node
SITES = ['SEAT', 'LOSA']
# CPU core isolation for NDN-DPDK systemd service on port 3030 and 3031
CORES3030, CORES3031 = 10, 6
# NIC model, 'NIC_Basic' or 'NIC_ConnectX_5' or 'NIC_ConnectX_6'
NIC_MODEL = 'NIC_Basic'
# whether to create NVMe device for fileserver development
WANT_NVME = False
# WireGuard client IPs and keys
V4WG_CLIENTS = [
    ('192.168.164.40', 'sDCCYU0r9TwugEDzTMDyfJ1eA+YwAyXf+EN3Hzj7QUo='),
    ('192.168.164.41', 'eDRM0enBsDVN+uXpVKjOeB5IAIoZsIHoGPiwdWgT81I='),
]
assert len(V4WG_CLIENTS) >= NODE_COUNT

# no need to change anything below

fablib = fablib_manager()
slice_name = f'dpdkdev@{int(time.time())}'
print(slice_name)

slice = fablib.new_slice(name=slice_name)
intfs = []
for i in range(NODE_COUNT):
    node = slice.add_node(name=f'n{i}', site=SITES[i % len(SITES)],
                          cores=6+CORES3030+CORES3031, ram=32, disk=100, image='default_ubuntu_22')
    intfs += node.add_component(model=NIC_MODEL, name='nic').get_interfaces()
    if WANT_NVME:
        node.add_component(model='NVME_P4510', name='disk')
    del node
slice.add_l2network(name='net', interfaces=intfs)
del intfs
v4wg.prepare(slice)
slice.submit()

v4wg.enable(slice, V4WG_CLIENTS)

execute_threads = {}
for node in slice.get_nodes():
    execute_threads[node] = node.execute_thread(f'''
        echo 'set enable-bracketed-paste off' | sudo tee -a /etc/inputrc
        sudo hostnamectl set-hostname {shlex.quote(node.get_name())}
        {ndndpdk_common.apt_install_cmd()}
        {ndndpdk_common.cpuset_cmd(node, instances={'127.0.0.1:3030': CORES3030, '127.0.0.1:3031': CORES3031})}
        sudo systemctl reboot
    ''')
for thread in execute_threads.values():
    thread.result()
slice.wait_ssh(progress=True)
slice.post_boot_config()

for node in slice.get_nodes():
    node.execute(ndndpdk_common.dl_build_cmd(make_env=[]))

for node in slice.get_nodes():
    print(f'{node.get_name()} {node.get_management_ip()}')
