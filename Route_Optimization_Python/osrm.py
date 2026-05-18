import osrm

# From file
engine = osrm.OSRM("path/to/data.osrm")

# With keyword arguments
engine = osrm.OSRM(
    storage_config="D:/data/data.osrm",
    algorithm="CH",                      # or "MLD"
    use_shared_memory=False,
    max_locations_trip=3,
    max_locations_viaroute=3,
    max_locations_distance_table=3,
    max_locations_map_matching=3,
    max_results_nearest=1,
    max_alternatives=1,
    default_radius="unlimited",
)

# Using shared memory (requires osrm-datastore)
engine = osrm.OSRM(use_shared_memory=True)