# Kitsu addon

CGWire's [Kitsu](https://www.cg-wire.com/kitsu) integration for AYON.

## Developer setup

### Linting and formatting

```shell
# Install the dev dependencies with Poetry
$ poetry install --no-root

# Format all the .py files
$ poetry run ruff format
```

## Create the package

In order to upload your addon to your AYON server, you need to create the .zip file:

```shell
$ python create_package.py
```

It will create it like: `./package/kits-<version>.zip`

## Run tests

See the [tests](./tests/) folder.