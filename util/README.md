# FABRIC Utility Scripts

This directory contains miscellaneous utility scripts for use on FABRIC JupyterLab.

## renew: Renew Slices

This script renews each experiment for 12 days.

Usage steps:

1. Upload the script to JupyterLab.
2. Enter slice names that you want to keep renewed in the script (see notes within).
3. Run `python renew.py`.

In my workflow, I keep this script updated with slice names that I care about, and I execute this script at the end of each day.
This ensures my slices are still there on the next workday.

## delete: Delete a Slice

This script deletes a slice specified on the command line.

Usage steps:

1. Upload the script to JupyterLab.
2. Run `python delete.py SLICE-NAME`.

Most experiment scripts in this repository deploy the slice but do not automatically delete them, as the slice may be providing a service used by other slices or remote nodes.
When the slice is no longer needed, this script may be used to delete the slice and release FABRIC resources.
