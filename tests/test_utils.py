import pytest
from common.utils import to_entity_name, to_project_name, to_project_code, to_label

""" tests for common.utils.py

    $ poetry run pytest tests/test_utils.py 
"""

def test_to_entity_name():
    assert to_entity_name("Test Project") == "Test_Project", "spaces should be replaced with an underscore"
    assert to_entity_name("Test  Project") == "Test_Project", "multiple spaces should be replaced with a single underscore"
    assert to_entity_name("Test_Project") == "Test_Project", "underscores should be maintained"
    assert to_entity_name("Test#* Project?") == "Test_Project", "non contain alphanumeric characters should be removed"
    assert to_entity_name("Test Project 123") == "Test_Project_123", "numbers supported"
    assert to_entity_name("  Test Project 123 ") == "Test_Project_123", "trailing whitespace should be removed"
    assert to_entity_name(".Test Project 123--") == "Test_Project_123", "trailing non contain alphanumeric characters should be removed"
    assert to_entity_name("Test-Project.123 ") == "Test-Project.123", "hyphens and dots ARE allowed"

    with pytest.raises(Exception, match='Entity name cannot be empty'):
        to_project_code("")


def test_to_project_name():
    assert to_project_name("Test-Project.123 ") == "TestProject123", "hyphens and dots are NOT allowed"

    assert to_project_name("Test Project") == "Test_Project", "spaces should be replaced with an underscore"
    assert to_project_name("Test  Project") == "Test_Project", "multiple spaces should be replaced with a single underscore"
    assert to_project_name("Test_Project") == "Test_Project", "underscores should be maintained"
    assert to_project_name("Test#* Project?") == "Test_Project", "non contain alphanumeric characters characters should be removed"
    assert to_project_name("Test Project 123") == "Test_Project_123", "numbers supported"
    assert to_project_name("  Test Project 123 ") == "Test_Project_123", "trailing whitespace should be removed"

def test_to_project_code():
    assert to_project_code("Test-P") == "TestP", "hyphens and dots are NOT allowed"
    assert to_project_code("Test P") == "Test_P", "spaces should be replaced with an underscore"
    assert to_project_code("Test#* P?") == "Test_P", "non contain alphanumeric characters characters should be removed"
    assert to_project_code("Tp123") == "Tp123", "numbers supported"
    assert to_project_code("  Tp123 ") == "Tp123", "trailing whitespace should be removed"
    assert to_project_code("0123456789abc") == "0123456789", "should be limited to 10 characters in length"

    with pytest.raises(Exception, match='Project Code should be 2 characters or more'):
        to_project_code("T")

def test_to_label():
    assert to_label("Test Label") == "Test Label", "spaces supported in labels"
    assert to_label("Test;Label'") == "TestLabel", "semi-colons and single quote not allowed to prevent sql injection"
    
    
    
    

