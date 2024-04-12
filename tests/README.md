# Testing

## Setup

You can ether use an already existing AYON instance by duplicating the `example_env`, rename it to `.env` and fill out the needed variables inside.
Or you can run AYON locally. You will need `ayon-docker`. You will need to mount your backend and addon code as volumes on the `server` service in `docker-compose.yml` for testing something like:

```docker
volumes:
      - "./addons:/addons"
      - "./storage:/storage"

      # mount ayon-backend
      - "../ayon-backend:/backend"

      # mount ayon-kitsu
      - "../ayon-kitsu:/addons/kitsu/1.0.2-dev1"

```

In the ayon backend you will need to create a new bundle with the kitsu version included.

Set up poetry env

```shell
cd ayon-kitsu/tests

# install dependencies
poetry install --no-root

```

### Running Tests

```shell
cd ayon-kitsu/tests

# run tests
poetry run pytest
```

For any addon updates you will need to reload ayon-backend:

```shell
cd ayon-docker

docker compose exec server ./reload.sh
```
