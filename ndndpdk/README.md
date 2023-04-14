# FABRIC NDN-DPDK Experiments

This directory contains scripts for running [NDN-DPDK](https://github.com/usnistgov/ndn-dpdk) related experiments.

## fileserver: File Server on the global NDN testbed

Deployment steps:

1. Upload `fileserver.py` and [`v4pub.py`](../ipv4) to JupyterLab in the same directory.
2. Modify parameters in `fileserver.py` (see notes within) as desired.
3. Run `fileserver.py`.

When the script completes, it will print the file server's NDN name prefix and `ndncatchunks` command for content retrieval.
After that, you can:

* See the file server's prefix registration on [NLSR status](https://nlsr-status.ndn.today/#network=ndn) webpage.
* Run content retrieval command on any end host connected to the [global NDN testbed](https://named-data.net/ndn-testbed/).
* ssh into the node and place additional content in `FS_PATH` path.
