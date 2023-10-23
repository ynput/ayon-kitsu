#!/usr/bin/env python

"""Prepares server package from addon repo to upload to server.

Requires Python 3.9. (Or at least 3.8+).

This script should be called from cloned addon repo.

It will produce 'package' subdirectory which could be pasted into server
addon directory directly (eg. into `ayon-backend/addons`).

Format of package folder:
ADDON_REPO/package/{addon name}/{addon version}

You can specify `--output_dir` in arguments to change output directory where
package will be created. Existing package directory will always be purged if
already present! This could be used to create package directly in server folder
if available.

Package contains server side files directly,
client side code zipped in `private` subfolder.
"""

import os
import sys
import re
import shutil
import json
import platform
import argparse
import logging
import collections
import zipfile
from typing import Any, Optional, Iterable, Pattern

# Name of addon
#   - e.g. 'maya'
ADDON_NAME: str = "kitsu"
# Name of folder where client code is located to copy 'version.py'
#   - e.g. 'ayon_maya'
ADDON_CLIENT_DIR: str = ""

# Patterns of directories to be skipped for server part of addon
IGNORE_DIR_PATTERNS: list[Pattern] = [
    re.compile(pattern)
    for pattern in [
        # Skip directories starting with '.'
        r"^\.",
        # Skip any pycache folders
        "^__pycache__$"
    ]
]

# Patterns of files to be skipped for server part of addon
IGNORE_FILE_PATTERNS: list[Pattern] = [
    re.compile(pattern)
    for pattern in {
        # Skip files starting with '.'
        # NOTE this could be an issue in some cases
        r"^\.",
        # Skip '.pyc' files
        r"\.pyc$"
    }
]


class ZipFileLongPaths(zipfile.ZipFile):
    """Allows longer paths in zip files.

    Regular DOS paths are limited to MAX_PATH (260) characters, including
    the string's terminating NUL character.
    That limit can be exceeded by using an extended-length path that
    starts with the '\\?\' prefix.
    """
    _is_windows = platform.system().lower() == "windows"

    def _extract_member(self, member, tpath, pwd):
        if self._is_windows:
            tpath = os.path.abspath(tpath)
            if tpath.startswith("\\\\"):
                tpath = "\\\\?\\UNC\\" + tpath[2:]
            else:
                tpath = "\\\\?\\" + tpath

        return super(ZipFileLongPaths, self)._extract_member(
            member, tpath, pwd
        )


def safe_copy_file(src_path: str, dst_path: str):
    """Copy file and make sure destination directory exists.

    Ignore if destination already contains directories from source.

    Args:
        src_path (str): File path that will be copied.
        dst_path (str): Path to destination file.
    """

    if src_path == dst_path:
        return

    dst_dir: str = os.path.dirname(dst_path)
    try:
        os.makedirs(dst_dir)
    except Exception:
        pass

    shutil.copy2(src_path, dst_path)


def _value_match_regexes(value: str, regexes: Iterable[Pattern]) -> bool:
    return any(
        regex.search(value)
        for regex in regexes
    )


def find_files_in_subdir(
    src_path: str,
    ignore_file_patterns: Optional[list[Pattern]]=None,
    ignore_dir_patterns: Optional[list[Pattern]]=None
) -> list[tuple[str, str]]:
    """Find all files to copy in subdirectories of given path.

    All files that match any of the patterns in 'ignore_file_patterns' will
        be skipped and any directories that match any of the patterns in
        'ignore_dir_patterns' will be skipped with all subfiles.

    Args:
        src_path (str): Path to directory to search in.
        ignore_file_patterns (Optional[list[Pattern]]): List of regexes
            to match files to ignore.
        ignore_dir_patterns (Optional[list[Pattern]]): List of regexes
            to match directories to ignore.

    Returns:
        list[tuple[str, str]]: List of tuples with path to file and parent
            directories relative to 'src_path'.
    """

    if ignore_file_patterns is None:
        ignore_file_patterns = IGNORE_FILE_PATTERNS

    if ignore_dir_patterns is None:
        ignore_dir_patterns = IGNORE_DIR_PATTERNS
    output: list[tuple[str, str]] = []

    hierarchy_queue: collections.deque = collections.deque()
    hierarchy_queue.append((src_path, []))
    while hierarchy_queue:
        item: tuple[str, str] = hierarchy_queue.popleft()
        dirpath, parents = item
        for name in os.listdir(dirpath):
            path: str = os.path.join(dirpath, name)
            if os.path.isfile(path):
                if not _value_match_regexes(name, ignore_file_patterns):
                    items: list[str] = list(parents)
                    items.append(name)
                    output.append((path, os.path.sep.join(items)))
                continue

            if not _value_match_regexes(name, ignore_dir_patterns):
                items: list[str] = list(parents)
                items.append(name)
                hierarchy_queue.append((path, items))

    return output


def copy_frontend_content(
    addon_output_dir: str,
    current_dir: str,
    log: logging.Logger
):
    """Copies 'frontend' portion

    Frontent must be built first into `dist` subfolder.
    """
    log.info("Copying frontend content")

    filepaths_to_copy: list[tuple[str, str]] = []
    frontend_dirpath: str = os.path.join(current_dir, "frontend")

    if not os.path.exists(frontend_dirpath):
        return

    source_dist = os.path.join(frontend_dirpath, "dist")
    if not os.path.exists(source_dist):
        raise ValueError(
            "Build frontend first with `yarn install && yarn build`")  # noqa
    for item in find_files_in_subdir(source_dist):
        src_path, dst_subpath = item
        dst_path: str = os.path.join(addon_output_dir, "frontend", "dist",
                                     dst_subpath)
        filepaths_to_copy.append((src_path, dst_path))

    # Copy files
    for src_path, dst_path in filepaths_to_copy:
        safe_copy_file(src_path, dst_path)


def copy_server_content(
    addon_output_dir: str,
    current_dir: str,
    log: logging.Logger
):
    """Copies server side folders to 'addon_package_dir'

    Args:
        addon_output_dir (str): package dir in addon repo dir
        current_dir (str): addon repo dir
        log (logging.Logger)
    """

    log.info("Copying server content")

    filepaths_to_copy: list[tuple[str, str]] = []
    server_dirpath: str = os.path.join(current_dir, "server")

    # Version
    src_version_path: str = os.path.join(current_dir, "version.py")
    dst_version_path: str = os.path.join(addon_output_dir, "version.py")
    filepaths_to_copy.append((src_version_path, dst_version_path))

    for item in find_files_in_subdir(server_dirpath):
        src_path, dst_subpath = item
        dst_path: str = os.path.join(addon_output_dir, dst_subpath)
        filepaths_to_copy.append((src_path, dst_path))

    # Copy files
    for src_path, dst_path in filepaths_to_copy:
        safe_copy_file(src_path, dst_path)


def zip_client_side(
    addon_package_dir: str,
    current_dir: str,
    log: logging.Logger
):
    """Copy and zip `client` content into 'addon_package_dir'.

    Args:
        addon_package_dir (str): Output package directory path.
        current_dir (str): Directory path of addon source.
        log (logging.Logger): Logger object.
    """

    client_dir: str = os.path.join(current_dir, "client")
    if not os.path.isdir(client_dir):
        log.info("Client directory was not found. Skipping")
        return

    log.info("Preparing client code zip")
    private_dir: str = os.path.join(addon_package_dir, "private")

    if not os.path.exists(private_dir):
        os.makedirs(private_dir)

    src_version_path: str = os.path.join(current_dir, "version.py")
    dst_version_path: str = os.path.join(ADDON_CLIENT_DIR, "version.py")

    zip_filepath: str = os.path.join(os.path.join(private_dir, "client.zip"))
    with ZipFileLongPaths(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Add client code content to zip
        for path, sub_path in find_files_in_subdir(client_dir):
            zipf.write(path, sub_path)

        # Add 'version.py' to client code
        zipf.write(src_version_path, dst_version_path)


def create_server_package(
    output_dir: str,
    addon_output_dir: str,
    addon_version: str,
    log: logging.Logger
):
    """Create server package zip file.

    The zip file can be installed to a server using UI or rest api endpoints.

    Args:
        output_dir (str): Directory path to output zip file.
        addon_output_dir (str): Directory path to addon output directory.
        addon_version (str): Version of addon.
        log (logging.Logger): Logger object.
    """

    log.info("Creating server package")
    output_path = os.path.join(
        output_dir, f"{ADDON_NAME}-{addon_version}.zip"
    )
    manifest_data: dict[str, str] = {
        "addon_name": ADDON_NAME,
        "addon_version": addon_version
    }
    with ZipFileLongPaths(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Write a manifest to zip
        zipf.writestr("manifest.json", json.dumps(manifest_data, indent=4))

        # Move addon content to zip into 'addon' directory
        addon_output_dir_offset = len(addon_output_dir) + 1
        for root, _, filenames in os.walk(addon_output_dir):
            if not filenames:
                continue

            dst_root = "addon"
            if root != addon_output_dir:
                dst_root = os.path.join(
                    dst_root, root[addon_output_dir_offset:]
                )
            for filename in filenames:
                src_path = os.path.join(root, filename)
                dst_path = os.path.join(dst_root, filename)
                zipf.write(src_path, dst_path)

    log.info(f"Output package can be found: {output_path}")


def main(
    output_dir: Optional[str]=None,
    skip_zip: Optional[bool]=False,
    keep_sources: Optional[bool]=False
):
    log: logging.Logger = logging.getLogger("create_package")
    log.info("Start creating package")

    current_dir: str = os.path.dirname(os.path.abspath(__file__))
    if not output_dir:
        output_dir = os.path.join(current_dir, "package")

    version_filepath: str = os.path.join(current_dir, "version.py")
    version_content: dict[str, Any] = {}
    with open(version_filepath, "r") as stream:
        exec(stream.read(), version_content)
    addon_version: str = version_content["__version__"]

    addon_output_root: str = os.path.join(output_dir, ADDON_NAME)
    addon_output_dir: str = os.path.join(
        addon_output_root, addon_version
    )
    if os.path.isdir(addon_output_dir):
        log.info(f"Purging {addon_output_dir}")
        shutil.rmtree(output_dir)

    log.info(f"Preparing package for {ADDON_NAME}-{addon_version}")

    if not os.path.exists(addon_output_dir):
        os.makedirs(addon_output_dir)

    copy_server_content(addon_output_dir, current_dir, log)

    copy_frontend_content(addon_output_dir, current_dir, log)

    zip_client_side(addon_output_dir, current_dir, log)

    # Skip server zipping
    if not skip_zip:
        create_server_package(
            output_dir, addon_output_dir, addon_version, log
        )
        # Remove sources only if zip file is created
        if not keep_sources:
            log.info("Removing source files for server package")
            shutil.rmtree(addon_output_root)
    log.info("Package creation finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-zip",
        dest="skip_zip",
        action="store_true",
        help=(
            "Skip zipping server package and create only"
            " server folder structure."
        )
    )
    parser.add_argument(
        "--keep-sources",
        dest="keep_sources",
        action="store_true",
        help=(
            "Keep folder structure when server package is created."
        )
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_dir",
        default=None,
        help=(
            "Directory path where package will be created"
            " (Will be purged if already exists!)"
        )
    )
    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        help="Debug log messages."
    )

    args = parser.parse_args(sys.argv[1:])
    level = logging.INFO
    if args.debug:
        level = logging.DEBUG
    logging.basicConfig(level=level)
    main(args.output_dir, args.skip_zip, args.keep_sources)
