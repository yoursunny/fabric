import json
import shlex
import time

from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager
from fabrictestbed_extensions.fablib.interface import Interface

import ndndpdk_common
import v4wg

# FABRIC site(s) for forwarder F, trafficgen A, trafficgen B; they may be same or different
SITE_F, SITE_A, SITE_B = 'STAR', 'SALT', 'CLEM'
# NIC model, 'NIC_Basic' or 'NIC_ConnectX_5' or 'NIC_ConnectX_6'
NIC_MODEL = 'NIC_ConnectX_6'
# whether trafficgen should have NVMe device to support NDN-DPDK fileserver;
# if False, benchmark only supports pingserver as producer
WANT_FILESERVER = True
# NDN-DPDK git repository
NDNDPDK_GIT = ndndpdk_common.DEFAULT_GIT_REPO
# 3x WireGuard client IPs and keys
V4WG_CLIENTS = [
    ('192.168.164.40', 'sDCCYU0r9TwugEDzTMDyfJ1eA+YwAyXf+EN3Hzj7QUo='),
    ('192.168.164.41', 'eDRM0enBsDVN+uXpVKjOeB5IAIoZsIHoGPiwdWgT81I='),
    ('192.168.164.42', 'UALczs0qEZ/KjfH2fMMIovFrK3/guRXL9GdRB+YVoFE='),
]

# no need to change anything below

fablib = fablib_manager()
slice_name = f'ndndpdk-benchmark@{int(time.time())}'
print(slice_name)

slice = fablib.new_slice(name=slice_name)
nodeF = slice.add_node(name='NF', site=SITE_F, cores=24,
                       ram=32, disk=100, image='default_ubuntu_22')
intfsF = nodeF.add_component(model=NIC_MODEL, name='nic0').get_interfaces()
if len(intfsF) < 2:
    intfsF += nodeF.add_component(model=NIC_MODEL,
                                  name='nic1').get_interfaces()
nodeA = slice.add_node(name='NA', site=SITE_A, cores=12,
                       ram=32, disk=100, image='default_ubuntu_22')
intfsA = nodeA.add_component(model=NIC_MODEL, name='nic0').get_interfaces()
nodeB = slice.add_node(name='NB', site=SITE_B, cores=12,
                       ram=32, disk=100, image='default_ubuntu_22')
intfsB = nodeB.add_component(model=NIC_MODEL, name='nic0').get_interfaces()
slice.add_l2network(name='netA', interfaces=[intfsF[0], intfsA[0]],
                    type=('L2Bridge' if SITE_F == SITE_A else 'L2STS' if NIC_MODEL == 'NIC_Basic' else 'L2PTP'))
slice.add_l2network(name='netB', interfaces=[intfsF[1], intfsB[0]],
                    type=('L2Bridge' if SITE_F == SITE_B else 'L2STS' if NIC_MODEL == 'NIC_Basic' else 'L2PTP'))
if WANT_FILESERVER:
    nodeA.add_component(model='NVME_P4510', name='disk')
    nodeB.add_component(model='NVME_P4510', name='disk')
v4wg.prepare(slice)
slice.submit()
del intfsF, intfsA, intfsB

slice = fablib.get_slice(name=slice_name)
ctrl_addrs = v4wg.enable(slice, V4WG_CLIENTS)
nodeF = slice.get_node(name='NF')
nodeA = slice.get_node(name='NA')
nodeB = slice.get_node(name='NB')
intfFA = nodeF.get_interface(network_name='netA')
intfFB = nodeF.get_interface(network_name='netB')
intfAF = nodeA.get_interface(network_name='netA')
intfBF = nodeB.get_interface(network_name='netB')

fs_path = '/srv/fileserver'
fs_nodes = []
if WANT_FILESERVER:
    fs_nodes = [nodeA, nodeB]
for node in fs_nodes:
    node.get_component('disk').configure_nvme(mount_point=fs_path)

# install necessary packages
execute_threads = {}
for node in slice.get_nodes():
    print(
        f'{node.get_name()} {ctrl_addrs[node.get_name()]} {node.get_management_ip()}')
    execute_threads[node] = node.execute_thread(f'''
        echo 'set enable-bracketed-paste off' | sudo tee -a /etc/inputrc
        sudo hostnamectl set-hostname {shlex.quote(node.get_name())}
        {ndndpdk_common.apt_install_cmd()}
        sudo loginctl enable-linger {shlex.quote(node.get_username())}
        sudo systemctl reboot
    ''')
for thread in execute_threads.values():
    thread.result()
slice.wait_ssh(progress=True)
slice.post_boot_config()

# build and install NDN-DPDK, set CPU isolation
execute_threads = {}
for node in slice.get_nodes():
    execute_threads[node] = node.execute_thread(f'''
        {ndndpdk_common.dl_build_cmd(repo=NDNDPDK_GIT)}
        {ndndpdk_common.cpuset_cmd(node, instances={f'{ctrl_addrs[node.get_name()]}:3030': node.get_cores()-4})}
        sudo systemctl reboot
    ''')
for thread in execute_threads.values():
    thread.result()
slice.wait_ssh(progress=True)
slice.post_boot_config()

# mount NVMe device and populate files for fileserver benchmark
for node in fs_nodes:
    node.execute(f'''
        echo {node.get_name()}
        sudo mkdir -p {shlex.quote(fs_path)}
        sudo mount /dev/nvme0n1p1 {shlex.quote(fs_path)}
        sudo chown {node.get_username()} {shlex.quote(fs_path)}
        cd ~/ndn-dpdk/sample/benchmark
        bash ./prepare-fileserver.sh {shlex.quote(fs_path)}
    ''')

# start NDN-DPDK services
for node in slice.get_nodes():
    node.execute(f'''
        echo {node.get_name()}
        sudo mkdir -p /run/ndn
        {ndndpdk_common.hugepages_cmd(size=20)}
        sudo ndndpdk-ctrl --gqlserver=http://{ctrl_addrs[node.get_name()]}:3030 systemd start
    ''')

benchmark_env = {}
for node in slice.get_nodes():
    id = node.get_name()[1]
    benchmark_env[f'{id}_GQLSERVER'] = f'http://{ctrl_addrs[node.get_name()]}:3030'
    benchmark_env[f'{id}_NUMA_PRIMARY'] = 0
    benchmark_env[f'{id}_CORES_PRIMARY'] = ','.join(
        [str(x) for x in range(6, node.get_cores())])
    benchmark_env[f'{id}_CORES_SECONDARY'] = '4,5'
    if id != 'F':
        benchmark_env[f'{id}_FILESERVER_PATH'] = fs_path


iplinks = {}
for node in slice.get_nodes():
    iplinks[node.get_name()] = json.loads(
        node.execute('ip -j -d link', quiet=True)[0])


def extract_pci_vlan(node: str, ifname: str) -> tuple[str, int, str]:
    link = [link for link in iplinks[node]
            if link['ifname'] == ifname]
    if len(link) != 1:
        raise f'netif {intf} not found on {node} `ip link` output'
    link = link[0]
    try:
        if link['linkinfo']['info_kind'] == 'vlan' and link['linkinfo']['info_data']['protocol'] == '802.1Q':
            pci, vlan, addr = extract_pci_vlan(node, link['link'])
            return pci, link['linkinfo']['info_data']['id'], link['address']
    except KeyError:
        pass
    return link['parentdev'].replace('0000:', ''), 0, link['address']


def get_pci_vlan(intf: Interface) -> tuple[str, int, str]:
    return extract_pci_vlan(intf.get_node().get_name(), intf.get_device_name())


benchmark_env['F_PORT_A'], benchmark_env['F_VLAN_A'], benchmark_env['F_HWADDR_A'] = get_pci_vlan(
    intfFA)
benchmark_env['F_PORT_B'], benchmark_env['F_VLAN_B'], benchmark_env['F_HWADDR_B'] = get_pci_vlan(
    intfFB)
benchmark_env['A_PORT_F'], benchmark_env['A_VLAN_F'], benchmark_env['A_HWADDR_F'] = get_pci_vlan(
    intfAF)
benchmark_env['B_PORT_F'], benchmark_env['B_VLAN_F'], benchmark_env['B_HWADDR_F'] = get_pci_vlan(
    intfBF)

# upload .env and start webapps
benchmark_dotenv = '\n'.join(
    [f'{key}={value}' for key, value in benchmark_env.items()])
nodeF.execute(f'''
    cd ~/ndn-dpdk/sample/benchmark
    corepack pnpm -s install
    echo {shlex.quote(benchmark_dotenv)} | tee .env
    systemd-run --user --collect --unit=ndndpdk-benchmark --same-dir -- corepack pnpm serve

    cd ~/ndn-dpdk/sample/status
    corepack pnpm -s install
    systemd-run --user --collect --unit=ndndpdk-status-F --same-dir -- corepack pnpm start --listen 127.0.0.1:8006 --gqlserver http://{ctrl_addrs[nodeF.get_name()]}:3030
    systemd-run --user --collect --unit=ndndpdk-status-A --same-dir -- corepack pnpm start --listen 127.0.0.1:8001 --gqlserver http://{ctrl_addrs[nodeA.get_name()]}:3030
    systemd-run --user --collect --unit=ndndpdk-status-B --same-dir -- corepack pnpm start --listen 127.0.0.1:8002 --gqlserver http://{ctrl_addrs[nodeB.get_name()]}:3030
''')

print(f'''
----------------------------------------------------------------
NDN-DPDK benchmark is ready.
Open an SSH tunnel:
{nodeF.get_ssh_command().replace('ssh ', 'ssh -L3333:127.0.0.1:3333 -L8006:127.0.0.1:8006 -L8001:127.0.0.1:8001 -L8002:127.0.0.1:8002 ')}
Access in browser:
http://localhost:3333 - benchmark webapp
http://localhost:8006 - forwarder F status
http://localhost:8001 - trafficgen A status
http://localhost:8002 - trafficgen B status
''')
