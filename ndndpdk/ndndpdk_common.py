import shlex

from fabrictestbed_extensions.fablib.node import Node

DEFAULT_GIT_REPO = 'https://github.com/usnistgov/ndn-dpdk.git'
"""URI of NDN-DPDK main git repository."""


def apt_install_cmd(*, extra_pkgs=[]) -> str:
    """
    Construct commands to install NDN-DPDK dependencies via APT.

    :param extra_pkgs: extra APT packages to install.
    """
    cmds: list[str] = []
    pkgs = sorted(set(['httpie', 'iperf3', 'jq',
                  'libibverbs-dev', 'linux-image-generic'] + extra_pkgs))
    cmds += [
        'sudo apt update',
        'sudo DEBIAN_FRONTEND=noninteractive apt full-upgrade -y',
        f"sudo DEBIAN_FRONTEND=noninteractive apt install -y --no-install-recommends {' '.join(pkgs)}",
        'sudo DEBIAN_FRONTEND=noninteractive apt purge -y nano',
    ]
    return '\n'.join(cmds)


def dl_build_cmd(*, repo=DEFAULT_GIT_REPO, depends_env: list[str] = [], depends_args: list[str] = [], make_env: list[str] = ['NDNDPDK_MK_RELEASE=1']) -> str:
    """
    Construct commands to download and install NDN-DPDK.

    :param repo: NDN-DPDK git repository.
    :param depends_env: environment variables passed to ndndpdk-depends.sh script.
    :param depends_args: arguments passed to ndndpdk-depends.sh script.
    :param make_env: environment variables passed to Makefile.
    """
    return '\n'.join([
        f'git clone {shlex.quote(repo)} ~/ndn-dpdk',
        'cd ~/ndn-dpdk',
        f"env {' '.join(depends_env)} ./docs/ndndpdk-depends.sh -y {' '.join(depends_args)}",
        'corepack pnpm -s install',
        f"env {' '.join(make_env)} make",
        'sudo make install',
    ])


def cpuset_cmd(node: Node, *, instances: dict[str, int]) -> str:
    """
    Construct commands to configure CPU isolation.

    :param node: fablib Node instance.
    :param instances: a dict where each key is a systemd instance name and each value is number of cores reserved for this instance.
    """
    demand_count = sum(instances.values())
    total_count = node.get_cores()
    assert demand_count < total_count
    allocated = 0
    cmds = []

    def put_alloc(dir: str, section: str, n: int) -> None:
        nonlocal allocated, cmds
        cpu_first = allocated
        allocated += n
        cpu_last = allocated - 1
        content = f'[{section}]\nCPUAffinity={cpu_first}-{cpu_last}'
        cmds += [
            f'sudo mkdir -p {dir}',
            f'echo {shlex.quote(content)} | sudo tee {dir}/cpuset.conf',
        ]
    put_alloc('/etc/systemd/system.conf.d',
              'Manager', total_count - demand_count)
    for a, n in instances.items():
        put_alloc(
            f'/etc/systemd/system/ndndpdk-svc@$(systemd-escape {shlex.quote(a)}).service.d', 'Service', n)
    assert allocated == total_count
    return '\n'.join(cmds)


def hugepages_cmd(*, size: int) -> str:
    """
    Construct commands to configure hugepages.

    :param size: hugepages size in GiB.
    """
    return '\n'.join([
        'sudo dpdk-hugepages.py --clear',
        f'while ! sudo dpdk-hugepages.py --pagesize 1G --setup {size}G; do sleep 1; done',
        'dpdk-hugepages.py --show',
    ])
