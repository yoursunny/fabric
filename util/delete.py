import sys

from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager

fablib = fablib_manager()

slice_name = sys.argv[1]
slice = fablib.get_slice(name=slice_name)
slice.delete()
