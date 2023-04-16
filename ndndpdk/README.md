# FABRIC NDN-DPDK Experiments

This directory contains scripts for running [NDN-DPDK](https://github.com/usnistgov/ndn-dpdk) related experiments.

## fileserver: File Server on the global NDN testbed

This experiment runs an [NDN-DPDK file server](https://github.com/usnistgov/ndn-dpdk/blob/main/docs/fileserver.md) that connects to the [global NDN testbed](https://named-data.net/ndn-testbed/).
The script can automatically obtain an NDN certificate that allows prefix registration on the testbed, and then connect to a specified testbed router and register a randomly generated prefix.

Deployment steps:

1. Upload `fileserver.py` and [`v4pub.py`](../ipv4) to the same directory on JupyterLab.
2. Modify parameters in `fileserver.py` (see notes within) as desired.
3. Run `fileserver.py`.

When the script completes, it will print the file server's NDN name prefix and `ndncatchunks` command for content retrieval.
After that, you can:

* See the file server's prefix registration on [NLSR status](https://nlsr-status.ndn.today/#network=ndn) webpage.
* Run content retrieval command on any end host connected to the [global NDN testbed](https://named-data.net/ndn-testbed/).
* ssh into the node and place additional content in `FS_PATH` path.

## benchmark: NDN-DPDK Benchmark Webapp

This experiment deploys the [NDN-DPDK benchmark webapp](https://github.com/usnistgov/ndn-dpdk/tree/main/sample/benchmark) with three nodes.
Node location and NIC type can be customized.
[NDN-DPDK status page](https://github.com/usnistgov/ndn-dpdk/tree/main/sample/status) is also installed for inspecting forwarder or traffic generator status.

Deployment steps:

1. Deploy a WireGuard VPN server with [`v4gateway.py`](../ipv4).
2. Upload `benchmark.py` and [`v4wg.py`](../ipv4) to the same directory on JupyterLab.
3. Modify parameters in `benchmark.py` (see notes within) as desired.
4. Run `benchmark.py`.

When the script completes, it will print access instructions.
