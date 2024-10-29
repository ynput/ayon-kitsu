name = "kitsu"
title = "Kitsu"
<<<<<<< HEAD
version = "1.2.4-appstart.25"
=======
version = "1.2.4-dev.1"
>>>>>>> d887d10b4d525b36a7ed45da66e15005f89c4d76
client_dir = "ayon_kitsu"

services = {
    "processor": {"image": f"ynput/ayon-kitsu-processor:{version}"},
}

ayon_required_addons = {
    "core": ">=0.3.0",
}
ayon_compatible_addons = {}
