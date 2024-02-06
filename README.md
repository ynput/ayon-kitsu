# Testing

### Setup

You will need `ayon-docker `running locally.  You will need to mount your backend and addon code as volumes on the `server `service in `docker-compose.yml` for testing something like:

```
volumes:
      - "./addons:/addons"
      - "./storage:/storage"

      # mount ayon-backend
      - "../ayon-backend:/backend"

      # mount ayon-kitsu
      - "../ayon-kitsu/server:/addons/kitsu/1.0.2-dev1"
      - "../ayon-kitsu/version.py:/addons/kitsu/1.0.2-dev1/version.py"

```

In the ayon backend you will need to create a new bundle with the kitsu version included.


Set up poetry env

```
cd ayon-kitsu

# install dependencies
poetry install --no-root

```

### Running Tests

```
cd ayon-kitsu

# run tests
poetry run pytest
```

For any addon updates you will need to reload ayon-backend:

```
cd ayon-docker

docker compose exec server ./reload.sh
```
