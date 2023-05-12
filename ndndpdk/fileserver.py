import json
import shlex
import time

from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager

import ndndpdk_common
import v4pub

slice_num = int(time.time())

# FABRIC site to allocate slice; must pick a site with IPv6 management address
SITE = 'SALT'
# remote router on /ndn network, written as IPv4 address (not hostname) and UDP port
ROUTER_IP, ROUTER_PORT = '128.252.153.194', 6363
# NDN-DPDK git repository
NDNDPDK_GIT = ndndpdk_common.DEFAULT_GIT_REPO
# URI for NDNts-CA profile packet, base64-encoded; the CA must accept "nop" challenge
CA_PROFILE_B64_URI = 'https://gist.githubusercontent.com/yoursunny/54db5b27f9193859b7d1c83f0aeb8d6d/raw/ca-profile.data.base64'
# URI for list of intermediate certificates of the NDNts-CA certificate
CA_INTERMEDIATES_URI = 'https://gist.githubusercontent.com/yoursunny/54db5b27f9193859b7d1c83f0aeb8d6d/raw/cert-intermediates.txt'
# NDN name prefix for the file server
FS_PREFIX = f'/fileserver.{slice_num}'
# filesystem path for the file server
FS_PATH = '/srv/fileserver'
# segment length served by the file server
FS_SEGMENTLEN = 6*1024

# no need to change anything below

fablib = fablib_manager()
slice_name = f'fileserver@{slice_num}'
print(slice_name)

slice = fablib.new_slice(name=slice_name)
node = slice.add_node(name='fileserver', site=SITE, cores=12,
                      ram=32, disk=100, image='default_ubuntu_22')
disk = node.add_component(model='NVME_P4510', name='disk')
v4pub.prepare(slice, [node.get_name()])
slice.submit()

v4pub.modify(slice)

node = slice.get_node(name='fileserver')
disk = node.get_component('disk')
v4pub.enable(slice)

# install NFD from https://nfd-nightly.ndn.today/
node.execute(f'''
    echo 'set enable-bracketed-paste off' | sudo tee -a /etc/inputrc
    sudo hostnamectl set-hostname {node.get_name()}
    echo "deb [arch=amd64 trusted=yes] https://nfd-nightly-apt.ndn.today/ubuntu jammy main" | sudo tee /etc/apt/sources.list.d/nfd-nightly.list
    {ndndpdk_common.apt_install_cmd(extra_pkgs=['ndnpeek', 'ndnsec', 'nfd'])}
    sudo loginctl enable-linger {node.get_username()}
    sudo systemctl reboot
''')
slice.wait_ssh(progress=True)
disk.configure_nvme(mount_point=FS_PATH)

# build and install NDN-DPDK
node.execute(ndndpdk_common.dl_build_cmd(repo=NDNDPDK_GIT))

# run NDNts keychain tool to obtain a testbed-compatible certificate
node.execute(f'''
    sudo systemctl enable --now nfd
    nfdc face create udp4://{ROUTER_IP}:{ROUTER_PORT}
    nfdc route add / udp4://{ROUTER_IP}:{ROUTER_PORT}

    mkdir -p ~/keychain
    http --ignore-stdin GET {shlex.quote(CA_PROFILE_B64_URI)} | base64 -d > ~/keychain/ca-profile.data
    I=0; for INTERMEDIATE in $(http --ignore-stdin GET {shlex.quote(CA_INTERMEDIATES_URI)}); do
        while ! [[ -s ~/keychain/intermediate-$I.ndncert ]]; do
            ndnpeek -v "$INTERMEDIATE" | base64 > ~/keychain/intermediate-$I.ndncert
        done
        I=$((I+1))
    done

    sudo npm i -g https://ndnts-nightly.ndn.today/keychain-cli.tgz
    export NDNTS_UPLINK=unix:///run/nfd.sock

    CAPREFIX=$(ndnts-keychain ndncert03-show-profile --profile ~/keychain/ca-profile.data --json | tee /dev/stderr | jq -r .prefix)
    ndnsec key-gen $CAPREFIX/$(hostname -s)-{slice_num} >/dev/null
    KEYNAME=$(ndnsec get-default -k)
    for I in $(seq 60); do
      if ndnts-keychain ndncert03-client --profile ~/keychain/ca-profile.data --ndnsec --key $KEYNAME --challenge nop; then
        break
      fi
      sleep 10
    done
    ndnsec export -o ~/keychain/pvt.safebag -P 0 -k $KEYNAME

    sudo systemctl disable --now nfd
''')

# set CPU isolation
node.execute(f"""
    {ndndpdk_common.cpuset_cmd(node, instances={
        '127.0.0.1:3030': 6,
        '127.0.0.1:3031': 4,
    })}
    sudo systemctl reboot
""")
slice.wait_ssh(progress=True)

FW_ACTIVATE = {
    'eal': {
        'memPerNuma': {'0': 12*1024},
        'filePrefix': 'fw',
        'disablePCI': True,
    },
    'mempool': {
        'DIRECT': {'capacity': 2**20-1, 'dataroom': 9200},
        'INDIRECT': {'capacity': 2**21-1},
    },
}
FW_UDP = {
    'scheme': 'udp',
    'remote': f'{ROUTER_IP}:{ROUTER_PORT}',
    'mtu': 1420,
}
MEMIF_SOCKET, MEMIF_ID = '/run/ndn/fileserver.sock', 1
FW_MEMIF = {
    'scheme': 'memif',
    'socketName': MEMIF_SOCKET,
    'id': MEMIF_ID,
    'dataroom': 9000,
    'role': 'server',
}
FS_ACTIVATE = {
    'eal': {
        'memPerNuma': {'0': 6*1024},
        'filePrefix': 'fs',
        'disablePCI': True,
    },
    'mempool': {
        'DIRECT': {'capacity': 2**16-1, 'dataroom': 9200},
        'INDIRECT': {'capacity': 2**16-1},
        'PAYLOAD': {'capacity': 2**16-1, 'dataroom': 9200},
    },
    'face': {
        'scheme': 'memif',
        'socketName': MEMIF_SOCKET,
        'id': MEMIF_ID,
        'dataroom': 9000,
        'role': 'client',
    },
    'fileServer': {
        'mounts': [
            {'prefix': FS_PREFIX, 'path': FS_PATH}
        ],
        'segmentLen': FS_SEGMENTLEN,
    },
}

nfdregCmd = 'ndndpdk-godemo --gqlserver http://127.0.0.1:3030/ nfdreg'
nfdregCmd += ' --signer ~/keychain/pvt.safebag --signer-pass 0 '
nfdregCmd += ' $(find ~/keychain/intermediate-*.ndncert -exec echo --serve-cert {} "" ";")'
nfdregCmd += f' --origin 65 --register {shlex.quote(FS_PREFIX)} --repeat 20s'

# start NDN-DPDK forwarder, prefix registration service, and fileserver
node.execute(f'''
    sudo mkdir -p {shlex.quote(FS_PATH)}
    sudo mount /dev/nvme0n1p1 {shlex.quote(FS_PATH)}
    sudo chown {node.get_username()} {shlex.quote(FS_PATH)}
    truncate -s 1G {shlex.quote(f'{FS_PATH}/1G.bin')}

    CTRL_FW='ndndpdk-ctrl --gqlserver http://127.0.0.1:3030/'
    CTRL_FS='ndndpdk-ctrl --gqlserver http://127.0.0.1:3031/'
    systemctl --user stop nfdreg || true
    sudo $CTRL_FW systemd stop || true
    sudo $CTRL_FS systemd stop || true

    {ndndpdk_common.hugepages_cmd(size=18)}

    sudo $CTRL_FW systemd start
    echo {shlex.quote(json.dumps(FW_ACTIVATE))} | $CTRL_FW activate-forwarder

    FW_UDP_FACE=$(echo {shlex.quote(json.dumps(FW_UDP))} | $CTRL_FW create-face)
    echo $FW_UDP_FACE
    $CTRL_FW insert-fib --name /localhop/nfd --nh $(echo $FW_UDP_FACE | jq -r .id)
    
    systemd-run --user --collect --unit=nfdreg -- {nfdregCmd}

    FW_MEMIF_FACE=$(echo {shlex.quote(json.dumps(FW_MEMIF))} | $CTRL_FW create-face)
    echo $FW_MEMIF_FACE
    $CTRL_FW insert-fib --name {shlex.quote(FS_PREFIX)} --nh $(echo $FW_MEMIF_FACE | jq -r .id)

    sudo $CTRL_FS systemd start
    echo {shlex.quote(json.dumps(FS_ACTIVATE))} | $CTRL_FS activate-fileserver
    
    $CTRL_FW list-faces
    $CTRL_FW list-fib
''')

print(node.get_ssh_command())
print(f'''
----------------------------------------------------------------
NDN-DPDK fileserver is ready on the global NDN testbed.
List directory or retrieve file from this fileserver:
ndncatchunks -q {FS_PREFIX}/32=ls | tr '\\0' '\\n'
ndncatchunks -v {FS_PREFIX}/1G.bin >/dev/null 2>catchunks.log
''')
