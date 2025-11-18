import itertools
import random
import shlex
import time
from collections.abc import Iterable

from fabrictestbed_extensions.fablib.node import Node


def _parse_cpuset(input: str) -> list[int]:
    result = list[int]()
    for cpuset_range in input.split(","):
        tokens = [int(token) for token in cpuset_range.split("-")]
        if len(tokens) == 1:
            result.append(tokens[0])
        else:
            result.extend(range(tokens[0], tokens[1]+1))
    return result


def _save_chcpu(online: Iterable[int], offline: Iterable[int]) -> Iterable[str]:
    content = "\n".join([
        "[Unit]",
        "Description=Set VCPU online or offline",
        "",
        "[Service]",
        "Type=oneshot",
        "RemainAfterExit=true",
    ] + [
        f"ExecStartPre=chcpu -e {vcpu}" for vcpu in online
    ] + [
        f"ExecStartPre=chcpu -d {vcpu}" for vcpu in offline
    ] + [
        "ExecStart=true",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
    ])
    yield f"echo {shlex.quote(content)} >/etc/systemd/system/chcpu.service"
    yield "systemctl daemon-reload"
    yield "systemctl enable --now chcpu.service"


def _save_unit_cpuset(unit: str, cpuset: Iterable[int]) -> Iterable[str]:
    vcpuset = ",".join([str(vcpu) for vcpu in cpuset])
    section = unit.split('.')[-1].capitalize()
    content = f'[{section}]\nAllowedCPUs={vcpuset}'
    yield f'mkdir -p /etc/systemd/system/{unit}.d'
    yield f'echo {shlex.quote(content)} >/etc/systemd/system/{unit}.d/cpuset.conf'


def pin_vcpu_to_socket(node: Node, online: dict[int, int], offline: list[int], *, quiet=False):
    """
    Assign VCPUs to physical cores on specific NUMA sockets.

    Args:
        node: existing Node instance.
        online: mapping from online VCPU to NUMA socket.
                Key is VCPU ID.
                Value is NUMA socket ID, or -1 for any.
        offline: list of VCPUs to set offline.
        quiet: if False, suppress console output.
    """

    # Retrieve cpuinfo document.
    cpu_info = node.get_cpu_info()
    cpu_info_host = cpu_info[node.get_host()]
    cpu_info_instance = cpu_info[node.get_instance_name()]

    if not quiet:
        print(f"---- cpuinfo for host {node.get_host()} ----")
        print(f"{cpu_info_host}\n")
        print(f"---- cpuinfo for instance {node.get_instance_name()} ----")
        print(f"{cpu_info_instance}\n")

    # Determine how many physical cores are present on the host machine.
    # Since hyperthreading is enabled, this would be half of the reported logical cores.
    host_lcore_count = int(cpu_info_host["CPU(s):"])
    assert host_lcore_count % 2 == 0
    host_pcore_count = host_lcore_count // 2

    # Gather a list of pinned / used logical cores.
    host_lcore_pinned = set([int(lcore)
                            for lcore in cpu_info_host["pinned_cpus"]])
    vcpu_unreserved = set[int]()
    for row in cpu_info_instance:
        vcpu_affinity = _parse_cpuset(row["CPU Affinity"])
        if len(vcpu_affinity) == 1:
            host_lcore_pinned.add(vcpu_affinity[0])
        vcpu_unreserved.add(int(row["VCPU"]))

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
        socket_lcore = _parse_cpuset(socket_lcore_cpuset)
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

    if not quiet:
        print(f"---- unused physical cores by NUMA socket ----")
        print(f"{host_pcore_by_numa}\n")

    # Validate user input.
    assert len(online) <= len(offline)
    assert max([socket for socket in online.values()]) < host_socket_count

    # Prepare POA.
    if not quiet:
        print("---- CPU assignments ----")
    vcpu_offline = offline[:]
    vcpu_cpu_map: list[dict[str, str]] = []
    for vcpu0, socket in online.items():
        # When desired socket is any, pick the least utilized NUMA socket.
        if socket < 0:
            socket = max(host_pcore_by_numa.items(),
                         key=lambda item: len(item[1]))[0]

        # Pick a physical core and pair with an offline VCPU.
        pcore = random.choice(host_pcore_by_numa[socket])
        host_pcore_by_numa[socket].remove(pcore)
        lcore0, lcore1 = pcore, pcore + host_pcore_count
        vcpu1 = vcpu_offline.pop(0)
        if not quiet:
            print(
                f"physical={pcore}, VCPU-online={vcpu0}, VCPU-offline={vcpu1}")

        # Map VCPUs as reserved.
        vcpu_unreserved.remove(vcpu0)
        vcpu_unreserved.remove(vcpu1)

        # Map its two logical cores to one online VCPU and one offline VCPU.
        vcpu_cpu_map.append({"vcpu": f"{vcpu0}", "cpu": f"{lcore0}"})
        vcpu_cpu_map.append({"vcpu": f"{vcpu1}", "cpu": f"{lcore1}"})

    if not quiet:
        print("")
        print(f"---- cpupin POA ----")
        print(f"{vcpu_cpu_map}\n")

    # Issue POA.
    poa_reply = node.poa(operation="cpupin", vcpu_cpu_map=vcpu_cpu_map)
    assert poa_reply == "Success"

    # Install systemd service to enable/disable VCPUs and set CPU isolation.
    sudo_commands = "\n".join(itertools.chain(
        _save_chcpu(online, offline),
        _save_unit_cpuset("init.scope", vcpu_unreserved),
        _save_unit_cpuset("user.slice", vcpu_unreserved),
        _save_unit_cpuset("service", vcpu_unreserved),
        _save_unit_cpuset("docker-.scope", online),
    ))
    node.execute(
        f"sudo bash -c {shlex.quote(sudo_commands)}", display=not quiet)

    # Refresh slice information and display instance cpuinfo.
    if not quiet:
        time.sleep(4)
        node.get_slice().update()
        cpu_info = node.get_cpu_info()
        cpu_info_instance = cpu_info[node.get_instance_name()]
        print(
            f"---- final cpuinfo for instance {node.get_instance_name()} ----\n{cpu_info_instance}\n")
