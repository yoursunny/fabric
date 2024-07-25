import sys

from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager

fablib = fablib_manager()

slice_name = sys.argv[1]
fablib.delete_slice(slice_name)
