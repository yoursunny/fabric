# FABRIC Utility Scripts

This directory contains miscellaneous utility scripts for use on FABRIC JupyterLab.

## renew: Renew Slices

This script renews each experiment for 12 days.

Usage steps:

1. Upload the script to JupyterLab.
2. Enter slice names that you want to keep renewed in the script (see notes within).
3. Run `python renew.py`.

I usually keep this script updated with slice names that I care about.
At end of each day, I execute this script to renew my slices.
This ensures my slices are still there on the next workday.

## delete: Delete a Slice

This script deletes a slice specified on the command line.

Usage steps:

1. Upload the script to JupyterLab.
2. Run `python delete.py SLICE-NAME`.

Most experiment scripts in this repository deploy new slices but do not automatically delete them, as the slice may be providing a service used by other slices or remote nodes.
When a slice is no longer needed, this script may be used to delete the slice and release FABRIC resources.

## cpupin: Pin VM to Physical CPU Core

This script sets CPU affinity of VCPUs so that both logical cores of a physical core are assigned to the VM.

Usage steps:

1. Upload the script to JupyterLab.
2. Edit variables in the script (see notes within).
3. Run `python cpupin.py`.

FABLib `Node.pin_cpu()` API can set CPU affinity to match a hardware NIC, but this doesn't work on a compute-only node.
Moreover, FABRIC now has hyper-threading enabled so that someone else can place workloads on other logical core, which affects the precision of compute-intensive benchmarks.

This script allows assigning VCPUs to physical cores on specific NUMA sockets.
For each physical core, it assigns both logical cores to two VCPUs of the VM.
Subsequently, one of these VCPUs is placed into offline mode, so that no other VM can pin to the logical core.
Unfortunately, currently [the hypervisor can still place workloads onto pinned logical cores](https://learn.fabric-testbed.net/forums/topic/pin_cpu-poaoperationcpupin/#post-9126), just that they cannot be pinned elsewhere.

## mtu: Test MTU and RTT between Sites

This script creates a slice in every available site and performs ping test among them via FABNetv4 and FABNetv6.
Maximum passable MTU and average RTT between every pair of sites are presented in a table.
This is useful for diagnosing MTU-related connectivity issues.

Usage steps:

1. Upload the script to JupyterLab.
2. Set `WANT_DELETE = False` and `WANT_CREATE = True`, run `python mtu.py`.
3. To delete slices created by this script: set `WANT_DELETE = True`, run `python mtu.py`.
