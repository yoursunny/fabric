import random
import shlex
import time
from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager

fablib = fablib_manager()

# existing slice name
SLICE_NAME = "demo"
# node name within slice
NODE_NAME = "vm"
# mapping from online VCPU to NUMA socket (-1 for any)
VCPU_SOCKET_MAP: dict[int, int] = {
    2: 1,
}
# list of VCPUs to set offline
VCPU_OFFLINE = [3]

# no need to change anything below

# Retrieve cpuinfo document.
slice = fablib.get_slice(SLICE_NAME)
node = slice.get_node(NODE_NAME)
cpu_info = node.get_cpu_info()
cpu_info_host = cpu_info[node.get_host()]
cpu_info_instance = cpu_info[node.get_instance_name()]

print(f"---- cpuinfo for host {node.get_host()} ----")
print(f"{cpu_info_host}\n")
print(f"---- cpuinfo for instance {node.get_instance_name()} ----")
print(f"{cpu_info_instance}\n")


def parse_cpuset(input: str) -> list[int]:
    result = list[int]()
    for cpuset_range in input.split(","):
        tokens = [int(token) for token in cpuset_range.split("-")]
        if len(tokens) == 1:
            result.append(tokens[0])
        else:
            result.extend(range(tokens[0], tokens[1]+1))
    return result


# Determine how many physical cores are present on the host machine.
# Since hyperthreading is enabled, this would be half of the reported logical cores.
host_lcore_count = int(cpu_info_host["CPU(s):"])
assert host_lcore_count % 2 == 0
host_pcore_count = host_lcore_count // 2

# Gather a list of pinned / used logical cores.
host_lcore_pinned = set([int(lcore) for lcore in cpu_info_host["pinned_cpus"]])
for row in cpu_info_instance:
    vcpu_affinity = parse_cpuset(row["CPU Affinity"])
    if len(vcpu_affinity) == 1:
        host_lcore_pinned.add(vcpu_affinity[0])

# Determine how many NUMA sockets are present on the host machine.
# Gather a list of unused physical cores, grouped by NUMA socket.
host_socket_count = 0
host_pcore_by_numa = dict[int, list[int]]()
for socket in range(0, 32):
    host_socket_count = socket
    try:
        socket_lcore_cpuset = cpu_info_host[f"NUMA node{socket} CPU(s):"]
    except KeyError:
        break

    # Logical cores within a NUMA socket typically show up as two disjoint ranges, in which
    # each physical core has one logical core in the lower range and another in the upper range.
    # We assert this assumption holds.
    socket_lcore = parse_cpuset(socket_lcore_cpuset)
    assert len(socket_lcore) % 2 == 0
    socket_pcore_count = len(socket_lcore) // 2
    socket_pcore = socket_lcore[:socket_pcore_count]
    assert socket_pcore == [
        lc-host_pcore_count for lc in socket_lcore[socket_pcore_count:]]

    # Determine unused physical cores on this NUMA socket.
    # If either logical core is used, the physical cores is considered used.
    # The first physical core is considered as being used by the kernel.
    socket_pcore = set(socket_pcore[1:])
    for lcore in host_lcore_pinned:
        socket_pcore.discard(lcore)
        socket_pcore.discard(lcore - host_pcore_count)
    host_pcore_by_numa[socket] = list(socket_pcore)

print(f"---- unused physical cores by NUMA socket ----")
print(f"{host_pcore_by_numa}\n")

# Validate user input.
assert len(VCPU_SOCKET_MAP) <= len(VCPU_OFFLINE)
assert max([socket for socket in VCPU_SOCKET_MAP.values()]) < host_socket_count

# Prepare POA.
print("---- CPU assignments ----")
vcpu_offline = VCPU_OFFLINE[:]
vcpu_cpu_map: list[dict[str, str]] = []
for vcpu0, socket in VCPU_SOCKET_MAP.items():
    # When desired socket is ANY, pick the least utilized NUMA socket.
    if socket < 0:
        socket = max(host_pcore_by_numa.items(),
                     key=lambda item: len(item[1]))[0]

    # Pick a physical core.
    pcore = random.choice(host_pcore_by_numa[socket])
    host_pcore_by_numa[socket].remove(pcore)
    lcore0, lcore1 = pcore, pcore + host_pcore_count
    vcpu1 = vcpu_offline.pop(0)
    print(f"physical={pcore}, VCPU-online={vcpu0}, VCPU-offline={vcpu1}")

    # Map its two logical cores to one online VCPU and one offline VCPU.
    vcpu_cpu_map.append({"vcpu": f"{vcpu0}", "cpu": f"{lcore0}"})
    vcpu_cpu_map.append({"vcpu": f"{vcpu1}", "cpu": f"{lcore1}"})

print("")
print(f"---- cpupin POA ----")
print(f"{vcpu_cpu_map}\n")

# Issue POA.
poa_reply = node.poa(operation="cpupin", vcpu_cpu_map=vcpu_cpu_map)
assert poa_reply == "Success"

# Set cores as online or offline.
online_commands = "\n".join([
    f"echo 1 >/sys/devices/system/cpu/cpu{vcpu}/online" for vcpu in VCPU_SOCKET_MAP
] + [
    f"echo 0 >/sys/devices/system/cpu/cpu{vcpu}/online" for vcpu in VCPU_OFFLINE
])
node.execute(f"sudo bash -c {shlex.quote(online_commands)}")

# Refresh slice information and display instance cpuinfo.
time.sleep(4)
slice.update()
node = slice.get_node(NODE_NAME)
cpu_info = node.get_cpu_info()
cpu_info_instance = cpu_info[node.get_instance_name()]
print(
    f"---- final cpuinfo for instance {node.get_instance_name()} ----\n{cpu_info_instance}\n")
