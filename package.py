name = "kitsu"
title = "Kitsu"
version = "1.1.1-dev.1"
client_dir = "ayon_kitsu"

services = {
    "processor": {"image": f"ynput/ayon-kitsu-processor:{version}"},
}
