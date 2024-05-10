name = "kitsu"
title = "Kitsu"
version = "1.2.1"
client_dir = "ayon_kitsu"

services = {
    "processor": {"image": f"ynput/ayon-kitsu-processor:{version}"},
}

ayon_required_addons = {
    "core": ">=0.3.0",
}
ayon_compatible_addons = {}
