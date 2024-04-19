name = "kitsu"
title = "Kitsu"
version = "1.2.0"
client_dir = "ayon_kitsu"

services = {
    "processor": {"image": f"ynput/ayon-kitsu-processor:{version}"},
}
