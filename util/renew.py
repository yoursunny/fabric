from datetime import datetime, timedelta, timezone

from fabrictestbed_extensions.fablib.fablib import \
    FablibManager as fablib_manager

# list of slice names
SLICE_NAMES = [
    'demo@299792458',
    'demo@602214076',
]

# no need to change anything below

fablib = fablib_manager()
end_date = (datetime.now(timezone.utc) + timedelta(days=12)
            ).strftime('%Y-%m-%d %H:%M:%S %z')

for slice_name in SLICE_NAMES:
    try:
        slice = fablib.get_slice(name=slice_name)
        end0 = slice.get_lease_end()
        slice.renew(end_date)
        slice.update()
        end1 = slice.get_lease_end()
        print(f"{slice_name} RENEW {end0} {end1}")
    except Exception as e:
        print(f"{slice_name} ERROR {e}")
