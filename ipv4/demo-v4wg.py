import itertools
import time

from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager

import v4wg

fablib = fablib_manager()
slice_name = f'demo@{int(time.time())}'
print(slice_name)

slice = fablib.new_slice(name=slice_name)
nodeA = slice.add_node(name='NA', site='SALT', cores=1,
                       ram=2, disk=10, image='default_ubuntu_22')
nodeB = slice.add_node(name='NB', site='SALT', cores=1,
                       ram=2, disk=10, image='default_ubuntu_22')
nodeC = slice.add_node(name='NC', site='STAR', cores=1,
                       ram=2, disk=10, image='default_ubuntu_22')
# Call v4wg.prepare() on the newly created slice, before calling slice.submit().
v4wg.prepare(slice)
slice.submit()

nodeA = slice.get_node(name='NA')
nodeB = slice.get_node(name='NB')
nodeC = slice.get_node(name='NC')

# At this moment, WireGuard clients are not yet installed, so that pings will not work.
print("Before v4wg.enable():")
print(
    f"NodeA {'can' if nodeA.ping_test('1.1.1.1') else 'cannot'} ping IPv4 Internet")
print(
    f"NodeB {'can' if nodeB.ping_test('1.1.1.1') else 'cannot'} ping IPv4 Internet")
print(
    f"NodeC {'can' if nodeC.ping_test('1.1.1.1') else 'cannot'} ping IPv4 Internet")

# Define client IP and private key tuples, one per node.
# These can be copied from v4gateway-wg0.conf [Peer] sections.
# If you have multiple experiments running, each node should have a distinct client IP and key.
v4wg_clients = [
    ('192.168.164.40', 'sDCCYU0r9TwugEDzTMDyfJ1eA+YwAyXf+EN3Hzj7QUo='),
    ('192.168.164.41', 'eDRM0enBsDVN+uXpVKjOeB5IAIoZsIHoGPiwdWgT81I='),
    ('192.168.164.42', 'UALczs0qEZ/KjfH2fMMIovFrK3/guRXL9GdRB+YVoFE='),
]

# Call v4pub.enable() to install WireGuard client to each node and configure its key.
# Changes are persisted and can survive node reboots.
assoc = v4wg.enable(slice, v4wg_clients)
print("v4wg.enable() return value:")
print(assoc)

# WireGuard clients are installed, so that pings should work.
print("After v4wg.enable():")
for src, dst in itertools.product(['A', 'B', 'C'], ['-', 'A', 'B', 'C']):
    src_node = slice.get_node(name=f'N{src}')
    try:
        dst_addr, dst_desc = assoc[f'N{dst}'], f'Node{dst}'
    except KeyError:
        dst_addr, dst_desc = '1.1.1.1', 'IPv4 Internet'
    print(
        f"Node{src} {'can' if src_node.ping_test(dst_addr) else 'cannot'} ping {dst_desc}")

slice.delete()
