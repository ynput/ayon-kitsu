name = "kitsu"
title = "Kitsu"
version = "1.1.0"
client_dir = "ayon_kitsu"

services = {
    "processor": {"image": f"ynput/ayon-kitsu-processor:{version}"},
}
