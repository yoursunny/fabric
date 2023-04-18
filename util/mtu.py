import re
import shlex
import threading

from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager
from fabrictestbed_extensions.fablib.slice import Slice

# slice name prefix
SLICE_PREFIX = 'mtu@'
# if True, delete existing slices
WANT_DELETE = False
# if True, create new slices; otherwise, only use existing slices
WANT_CREATE = True
# if non-empty, create slices on these sites only
SITES_ONLY = []
# don't create slices on these sites
SITES_AVOID = ['GATECH', 'SRI', 'LOSA', 'NEWY']
# NIC model, 'NIC_Basic' or 'NIC_ConnectX_5' or 'NIC_ConnectX_6'
NIC_MODEL = 'NIC_Basic'
# MTUs to test
PROBE_MTUS = [256, 1280, 1420, 1500, 8900, 8948, 9000]

# no need to change anything below

fablib = fablib_manager()


def list_slices() -> dict[str, Slice]:
    slices = {}
    for slice in fablib.get_slices():
        if slice.get_name().startswith(SLICE_PREFIX):
            site = slice.get_name()[len(SLICE_PREFIX):]
            slices[site] = slice
    return slices


slices = list_slices()
if len(slices) > 0:
    print(f"Found slices for sites {' '.join(slices)}")

if WANT_DELETE:
    for site, slice in slices.items():
        print(f'Deleting slice for site {site}')
        slice.delete()
    exit()

if WANT_CREATE:
    sites = [site['name']
             for site in fablib.list_sites(output='list', quiet=True, filter_function=lambda x: x['cores_available'] > 0)]
    for site in [site for site in sites if (site not in slices) and (len(SITES_ONLY) == 0 or site in SITES_ONLY) and (site not in SITES_AVOID)]:
        slice = fablib.new_slice(name=SLICE_PREFIX+site)
        node = slice.add_node(name='node', site=site, cores=1,
                              ram=2, disk=10, image='default_ubuntu_22')
        intfs = node.add_component(
            model=NIC_MODEL, name='nic0').get_interfaces()
        if len(intfs) < 2:
            intfs += node.add_component(model=NIC_MODEL,
                                        name='nic1').get_interfaces()
        intf4, intf6 = intfs[:2]
        slice.add_l3network(name='net4', interfaces=[intf4], type='IPv4')
        slice.add_l3network(name='net6', interfaces=[intf6], type='IPv6')
        print(f'Creating slice for site {site}')
        try:
            slice.submit(wait=False)
            slices[site] = slice
        except Exception as e:
            print(e)

failed_sites = []
addrs: dict[str, dict[int, str]] = {}
for site, slice in slices.items():
    if slice.get_state() not in ['StableOK', 'ModifyOK']:
        try:
            slice.wait()
            slice.update()
        except Exception as e:
            print(f'Error in slice for site {site}')
            print(e)
            failed_sites.append(site)
            continue
    node = slice.get_node('node')
    [ip4addr] = slice.get_l3network('net4').get_available_ips(count=1)
    [ip6addr] = slice.get_l3network('net6').get_available_ips(count=1)
    addrs[site] = {4: str(ip4addr), 6: str(ip6addr)}
    print(f'{site} is ready, mgmt {node.get_management_ip()}, IPv4 {ip4addr}, IPv6 {ip6addr}')
for site in failed_sites:
    del slices[site]

print('Applying IP configs')
execute_threads = {}
for site, slice in slices.items():
    node = slice.get_node('node')
    cmds: list[str] = []
    for af in [4, 6]:
        intf = node.get_interface(network_name=f'net{af}')
        devname = intf.get_os_interface()
        addr = addrs[site][af]
        net = intf.get_network()
        cmds += [
            f'sudo ip link set {shlex.quote(devname)} up',
            f'sudo ip link set {shlex.quote(devname)} mtu 9000',
            f'sudo ip -{af} addr flush dev {shlex.quote(devname)}',
            f'sudo ip -{af} addr add {shlex.quote(addr)}/{net.get_subnet().prefixlen} dev {shlex.quote(devname)}'
        ]
        for dst in slices:
            if dst != site:
                cmds.append(
                    f'sudo ip -{af} route replace {addrs[dst][af]} via {net.get_gateway()}')
    execute_threads[site] = node.execute_thread('\n'.join(cmds))
for site, thread in execute_threads.items():
    stdout, stderr = thread.result()
    if stderr != '':
        print(f'IP config for {site} error:\n{stderr}')

re_loss = re.compile('([\d]+)% packet loss')
re_rtt = re.compile('rtt.*([.\d]+)/([.\d]+)/([.\d]+)/[.\d]+ ms')
width_mtu = 4
width_rtt = 4
width_td = width_mtu + width_rtt


def process_ping_result(thread: threading.Thread) -> str:
    try:
        stdout, stderr = thread.result()
    except:
        return 'ERR-CMD'.ljust(width_td)
    matches_loss = list(re_loss.finditer(stdout))
    if len(matches_loss) != len(PROBE_MTUS):
        return 'ERR-RE'.ljust(width_td)
    pass_mtu = 0
    for mtu, m_loss in zip(PROBE_MTUS, matches_loss):
        if m_loss[1] == '0':
            pass_mtu = mtu
    max_avg_rtt = -1
    for m_rtt in re_rtt.finditer(stdout):
        max_avg_rtt = max(max_avg_rtt, float(m_rtt[2]))
    return str(pass_mtu).ljust(width_mtu) + str(int(max_avg_rtt)).rjust(width_rtt)


for af, overhead in {4: 28, 6: 48}.items():
    print('')
    print(f'IPv{af} ping MTU and RTT')
    print('src\\dst'.ljust(width_td), end='')
    for dst in slices:
        print(' | ' + dst.center(width_td), end='')
    print('')
    print('-'*(width_td+1) + ('|'+'-'*(width_td+2))*len(slices))
    for src in slices:
        node = slices[src].get_node('node')
        execute_threads = {}
        for dst in slices:
            execute_threads[dst] = node.execute_thread('\n'.join([
                f'ping -I {shlex.quote(addrs[src][af])} -c 4 -i 0.2 -W 0.8 -M do -s {mtu-overhead} {shlex.quote(addrs[dst][af])}'
                for mtu in PROBE_MTUS
            ]))
        print(src.ljust(width_td), end='')
        for dst in slices:
            print(' | ' + process_ping_result(execute_threads[dst]), end='')
        print('')
