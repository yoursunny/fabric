import shlex
import time

import yaml
from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager

import v4pub

# FABRIC site to allocate slice; must pick a site with IPv6 management address
SITE = 'STAR'

# no need to change anything below

wg0_conf_template = 'v4gateway-wg0.conf'

fablib = fablib_manager()
slice_name = f'v4gateway@{int(time.time())}'
print(slice_name)

slice = fablib.new_slice(name=slice_name)
node = slice.add_node(name='gateway', site=SITE, cores=1,
                      ram=2, disk=10, image='default_ubuntu_24')
[intf_lan] = node.add_component(
    model='NIC_Basic', name='lan').get_interfaces()[:1]
slice.add_l3network(name='LAN', interfaces=[intf_lan], type='IPv4')
v4pub.prepare(slice, ['gateway'])
slice.submit()

v4pub.modify(slice)
ip_wan = v4pub.enable(slice)['gateway']

node = slice.get_node(name='gateway')
net_lan = slice.get_network(name='LAN')
[ip_lan] = net_lan.get_available_ips(count=1)
[intf_lan] = net_lan.get_interfaces()

netplan_conf = yaml.dump({
    'network': {
        'version': 2,
        'ethernets': {
            'v4wgnet': {
                'match': {'macaddress': intf_lan.get_mac()},
                'set-name': 'v4wgnet',
                'mtu': 9000,
                'addresses': [f'{ip_lan}/{net_lan.get_subnet().prefixlen}'],
                'routes': [{
                    'to': '10.0.0.0/8',
                    'via': str(net_lan.get_gateway())
                }]
            }
        }
    }
})
node.upload_file(local_file_path=wg0_conf_template,
                 remote_file_path='wg0.conf')

node.execute(f'''
    echo 'set enable-bracketed-paste off' | sudo tee -a /etc/inputrc
    sudo hostnamectl set-hostname v4gateway
    sudo DEBIAN_FRONTEND=noninteractive apt update
    sudo DEBIAN_FRONTEND=noninteractive apt full-upgrade -y -qq
    sudo DEBIAN_FRONTEND=noninteractive apt install -y -qq httpie iperf3 jq mtr-tiny traceroute wireguard
    sudo DEBIAN_FRONTEND=noninteractive apt purge -y nano
    sudo ufw allow to {node.get_management_ip()} port 22 proto tcp
    yes | sudo ufw enable
    echo {shlex.quote(netplan_conf)} | sudo tee /etc/netplan/64-v4gateway.yaml >/dev/null
    sed -e 's/IP-WAN/{ip_wan}/g' -e 's/IP-LAN/{ip_lan}/g' wg0.conf | sudo tee /etc/wireguard/wg0.conf >/dev/null
    sudo ufw allow to {ip_lan} port 51820 proto udp
    sudo systemctl enable wg-quick@wg0.service
    sudo reboot
''')

print(node.get_ssh_command())
print(f'WAN IP {ip_wan}')
print(f'LAN IP {ip_lan}')
