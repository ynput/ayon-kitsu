import pytest

from addon_helpers import (
    to_entity_name,
    to_username,
)


""" tests for formatting values to pass Ayon validation

    $ poetry run pytest tests/test_addon_helpers.py 
"""


def test_to_username():
    assert to_username("Bobby") == "bobby", "first name only"
    assert to_username("Bob", "McBobertson") == "bob.mcbobertson", "first and last name"
    assert to_username("Bob J", "Mc Bobertson") == "bobj.mcbobertson", "spaces in names"
    # assert to_username("Bob J.", "McBobertson") == "bobj.mcbobertson", "spaces in names"
    assert to_username("François", "Kožušček") == "francois.kozuscek", "unicode accents"
    assert (
        to_username("Bøb", "Brown") == "bob.brown"
    ), "some unicode accents not supported"
    assert (
        to_username("äöü", "Brown") == "aou.brown"
    ), "some unicode accents not supported"


def test_to_entity_name():
    assert (
        to_entity_name("Test Project") == "Test_Project"
    ), "spaces should be replaced with an underscore"
    assert (
        to_entity_name("Test  Project") == "Test_Project"
    ), "multiple spaces should be replaced with a single underscore"
    assert (
        to_entity_name("Test_Project") == "Test_Project"
    ), "underscores should be maintained"
    assert (
        to_entity_name("Test#* Project?") == "Test_Project"
    ), "non contain alphanumeric characters should be removed"
    assert to_entity_name("Test Project 123") == "Test_Project_123", "numbers supported"
    assert (
        to_entity_name("  Test Project 123 ") == "Test_Project_123"
    ), "trailing whitespace should be removed"
    assert (
        to_entity_name(".Test Project 123--") == "Test_Project_123"
    ), "trailing non contain alphanumeric characters should be removed"
    assert (
        to_entity_name("Test-Project.123 ") == "Test-Project.123"
    ), "hyphens and dots ARE allowed"

    with pytest.raises(Exception, match="Entity name cannot be empty"):
        to_entity_name("")
