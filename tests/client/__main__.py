import json
from .api import get_ayon_headers

if __name__ == "__main__":

    h = get_ayon_headers()
    print(json.dumps(h, indent=2))
