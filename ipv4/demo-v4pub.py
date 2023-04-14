import time

from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager

import v4pub

fablib = fablib_manager()
slice_name = f'demo@{int(time.time())}'
print(slice_name)

slice = fablib.new_slice(name=slice_name)
nodeA = slice.add_node(name='NA', site='WASH', cores=1,
                       ram=2, disk=10, image='default_ubuntu_22')
nodeB = slice.add_node(name='NB', site='WASH', cores=1,
                       ram=2, disk=10, image='default_ubuntu_22')
nodeC = slice.add_node(name='NC', site='STAR', cores=1,
                       ram=2, disk=10, image='default_ubuntu_22')
# Call v4pub.prepare() on the newly created slice, before the initial slice.submit().
# Pass a list of node names that need public IPv4 addresses; other nodes would not have IPv4 Internet access.
v4pub.prepare(slice, ['NA', 'NC'])
slice.submit()

slice = fablib.get_slice(name=slice_name)
nodeA = slice.get_node(name='NA')
nodeB = slice.get_node(name='NB')
nodeC = slice.get_node(name='NC')

# At this moment, public IPv4 addresses are not yet assigned, so that pings will not work.
print("Before v4pub.modify():")
print(f"NodeA {'can' if nodeA.ping_test('1.1.1.1') else 'cannot'} ping IPv4 site")
print(f"NodeB {'can' if nodeB.ping_test('1.1.1.1') else 'cannot'} ping IPv4 site")
print(f"NodeC {'can' if nodeC.ping_test('1.1.1.1') else 'cannot'} ping IPv4 site")

slice = fablib.get_slice(name=slice_name)
# Call v4pub.modify() on a created slice to request IPv4 addresses.
# Another slice.submit() is needed to submit the modification.
v4pub.modify(slice)
slice.submit()

slice = fablib.get_slice(name=slice_name)
# Call v4pub.enable() to configure each node with its IPv4 address.
# Changes are persisted and can survive node reboots.
assoc = v4pub.enable(slice)
print("v4pub.enable() return value:")
print(assoc)

# Public IPv4 address is assigned and configured on nodeA and nodeC only,
# so that ping should work from nodeA and nodeC but not nodeB.
print("After v4pub.enable():")
print(f"NodeA {'can' if nodeA.ping_test('1.1.1.1') else 'cannot'} ping IPv4 site")
print(f"NodeB {'can' if nodeB.ping_test('1.1.1.1') else 'cannot'} ping IPv4 site")
print(f"NodeC {'can' if nodeC.ping_test('1.1.1.1') else 'cannot'} ping IPv4 site")

slice.delete()
