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

### Project deletion unit tests

The tests in `unit/` use mocked HTTP and database calls. They do not require
live projects and do not delete anything. From the repository root, run
the server tests in an AYON backend environment, with this repository on
`PYTHONPATH`:

```shell
python -m unittest discover -s tests/unit -p test_project_remove.py -v
```

Run the event-handler tests with the processor dependencies installed:

```shell
PYTHONPATH=services/processor python -m unittest discover \
    -s tests/unit -p test_project_delete_processor.py -v
```

### Project deletion integration tests

`tests/test_project_deletion.py` runs in the normal pytest environment. It
creates uniquely named projects, removes only those projects, and restores
the selected addon's settings after each test. Run this against a test server;
the deletion setting is changed temporarily. Set `AYON_KITSU_TEST_VERSION` to
target an isolated addon version instead of the production version.

```shell
poetry run pytest tests/test_project_deletion.py -v
```
