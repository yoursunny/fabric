import json
import shlex
import time

from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager

import v4pub
import v4wg

fablib = fablib_manager()
sliceNum = int(time.time())
sliceName = f'fileserver@{sliceNum}'
print(sliceName)

# FABRIC site to allocate slice; its management IP must be IPv6
SITE = 'WASH'
# set to True to request dedicated IPv4 address
WANT_V4PUB = True
# v4wg server endpoint
V4WG_SERVER_ENDPOINT = 'wg-fabric.d.yoursunny.dev:51820'
# v4wg server public key
V4WG_SERVER_PUBKEY = 'FNih7YL6b5UnwZVPvcOZ7MjAEUmSLuKcIuMf5eWQ6SE='
# v4wg clients IP and private key
V4WG_CLIENTS = [
    ('192.168.164.254', 'GJozi8oJft/ergL+m0K5QPhve1hGp4hxBny55xhlzkI=')]
# remote router on /ndn network, written as IPv4 address (not hostname) and UDP port
ROUTER_IP, ROUTER_PORT = '128.252.153.194', 6363
# URI for NDNts-CA profile packet, base64-encoded; the CA must accept "nop" challenge
CA_PROFILE_B64_URI = 'https://gist.githubusercontent.com/yoursunny/54db5b27f9193859b7d1c83f0aeb8d6d/raw/ca-profile.data.base64'
# URI for list of intermediate certificates of the NDNts-CA certificate
CA_INTERMEDIATES_URI = 'https://gist.githubusercontent.com/yoursunny/54db5b27f9193859b7d1c83f0aeb8d6d/raw/cert-intermediates.txt'
# NDN name prefix for the file server
FS_PREFIX = f'/fileserver.{sliceNum}'
# filesystem path for the file server
FS_PATH = '/srv/fileserver'
# segment length served by the file server
FS_SEGMENTLEN = 6*1024

slice = fablib.new_slice(name=sliceName)
node = slice.add_node(name='fileserver', site=SITE, cores=12,
                      ram=32, disk=100, image='default_ubuntu_22')
disk = node.add_component(model='NVME_P4510', name='disk')
if WANT_V4PUB:
    v4pub.prepare(slice, [node.get_name()])
else:
    v4wg.prepare(slice)
slice.submit()

if WANT_V4PUB:
    slice = fablib.get_slice(name=sliceName)
    v4pub.modify(slice)
    slice.submit()

slice = fablib.get_slice(name=sliceName)
node = slice.get_node(name='fileserver')
disk = node.get_component('disk')
print(node.get_ssh_command())
if WANT_V4PUB:
    v4pub.enable(slice)
else:
    v4wg.enable(slice, V4WG_SERVER_ENDPOINT, V4WG_SERVER_PUBKEY, V4WG_CLIENTS)

node.execute(f'''
    sudo hostnamectl set-hostname {node.get_name()}
    echo "deb [arch=amd64 trusted=yes] https://nfd-nightly-apt.ndn.today/ubuntu jammy main" | sudo tee /etc/apt/sources.list.d/nfd-nightly.list
    sudo apt update
    sudo DEBIAN_FRONTEND=noninteractive apt full-upgrade -y
    sudo DEBIAN_FRONTEND=noninteractive apt install -y --no-install-recommends jq libibverbs-dev linux-image-generic ndnsec ndnpeek nfd
    sudo loginctl enable-linger {node.get_username()}
    sudo reboot
''')
slice.wait_ssh(progress=True)
disk.configure_nvme(mount_point=FS_PATH)

node.execute('''
    git clone https://github.com/yoursunny/ndn-dpdk.git
    cd ndn-dpdk
    docs/ndndpdk-depends.sh -y

    corepack pnpm install
    NDNDPDK_MK_RELEASE=1 make
    sudo make install
''')

node.execute(f'''
    sudo systemctl enable --now nfd
    nfdc face create udp4://{ROUTER_IP}:{ROUTER_PORT}
    nfdc route add / udp4://{ROUTER_IP}:{ROUTER_PORT}

    mkdir -p ~/keychain
    curl -fsLS {shlex.quote(CA_PROFILE_B64_URI)} | base64 -d > ~/keychain/ca-profile.data
    I=0; for INTERMEDIATE in $(curl -fsLS {shlex.quote(CA_INTERMEDIATES_URI)}); do
        while ! [[ -s ~/keychain/intermediate-$I.ndncert ]]; do
            ndnpeek -v "$INTERMEDIATE" | base64 > ~/keychain/intermediate-$I.ndncert
        done
        I=$((I+1))
    done

    sudo npm i -g https://ndnts-nightly.ndn.today/keychain-cli.tgz
    export NDNTS_UPLINK=unix:///run/nfd.sock

    CAPREFIX=$(ndnts-keychain ndncert03-show-profile --profile ~/keychain/ca-profile.data --json | tee /dev/stderr | jq -r .prefix)
    ndnsec key-gen $CAPREFIX/$(hostname -s)-{sliceNum} >/dev/null
    KEYNAME=$(ndnsec get-default -k)
    for I in $(seq 60); do
      if ndnts-keychain ndncert03-client --profile ~/keychain/ca-profile.data --ndnsec --key $KEYNAME --challenge nop; then
        break
      fi
      sleep 10
    done
    ndnsec export -o ~/keychain/pvt.safebag -P 0 -k $KEYNAME

    sudo systemctl disable --now nfd
    
    to_file() {{
        sudo mkdir -p "$(dirname $1)"
        sudo tee "$1"
    }}
    echo -e '[Manager]\nCPUAffinity=0-1' | to_file /etc/systemd/system.conf.d/cpuset.conf
    echo -e '[Service]\nCPUAffinity=2-7' | to_file /etc/systemd/system/ndndpdk-svc@$(systemd-escape 127.0.0.1:3030).service.d/override.conf
    echo -e '[Service]\nCPUAffinity=8-11' | to_file /etc/systemd/system/ndndpdk-svc@$(systemd-escape 127.0.0.1:3031).service.d/override.conf
    sudo reboot
''')
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

    sudo dpdk-hugepages.py --clear
    sudo dpdk-hugepages.py --pagesize 1G --setup 18G

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

print(f'''
ndncatchunks -q {FS_PREFIX}/32=ls | tr '\\0' '\\n'
ndncatchunks -v {FS_PREFIX}/1G.bin >/dev/null 2>catchunks.log
''')
