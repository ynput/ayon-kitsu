import re
import unicodedata
from typing import Any

"""
A collection of helper functions for Ayon Addons
minimal dependencies, pytest unit tests
"""


def required_values(
    entity: dict[str, Any], keys: list[str], allow_empty_value: bool = False
) -> list[Any]:
    """check the entity dict has the required keys and a value for each"""
    values = []
    for key in keys:
        if key not in entity:
            raise ValueError(f"Key '{key}' not set for entity: {entity}")
        if not allow_empty_value and not entity.get(key):
            raise ValueError(
                f"Value for '{key}' cannot be empty for entity: {entity}"
            )
        values.append(entity.get(key))
    return values


## ========== KITSU -> AYON NAME CONVERSIONS =====================


def create_short_name(name: str) -> str:
    """create a shortname from the full name when a shortname is not present"""
    code = name.lower()

    if "_" in code:
        subwords = code.split("_")
        code = "".join([subword[0] for subword in subwords])[:4]
    elif len(name) > 4:
        vowels = ["a", "e", "i", "o", "u"]
        filtered_word = "".join([char for char in code if char not in vowels])
        code = filtered_word[:4]

    # if there is a number at the end of the code, add it to the code
    last_char = code[-1]
    if last_char.isdigit():
        code += last_char

    return code


def to_username(first_name: str, last_name: str | None = None) -> str:
    """converts usernames from kitsu - converts accents"""

    name = (
        f"{first_name.strip()}.{last_name.strip()}"
        if last_name
        else first_name.strip()
    )

    name = name.lower()
    name = remove_accents(name)
    return to_entity_name(name)


def remove_accents(input_str: str) -> str:
    """swap accented characters for a-z equivilants ž => z"""

    nfkd_form = unicodedata.normalize("NFKD", input_str)
    result = "".join([c for c in nfkd_form if not unicodedata.combining(c)])

    # manually replace exceptions
    # @see https://stackoverflow.com/questions/3194516/replace-special-characters-with-ascii-equivalent
    replacement_map = {
        "Æ": "AE",
        "Ð": "D",
        "Ø": "O",
        "Þ": "TH",
        "ß": "ss",
        "æ": "ae",
        "ð": "d",
        "ø": "o",
        "þ": "th",
        "Œ": "OE",
        "œ": "oe",
        "ƒ": "f",
    }
    for k, v in replacement_map.items():
        if k in result:
            result = result.replace(k, v)

    # remove any unsupported characters
    result = re.sub(r"[^a-zA-Z0-9_\.\-]", "", result)

    return result


def to_entity_name(name: str) -> str:
    r"""convert names so they will pass AYON Entity name validation
    @see ayon_server.types.NAME_REGEX
        r"^[a-zA-Z0-9_]([a-zA-Z0-9_\.\-]*[a-zA-Z0-9_])?$"
    """

    if not name:
        raise ValueError("Entity name cannot be empty")

    name = name.strip()

    # replace whitespace
    name = re.sub(r"\s+", "_", name)
    # remove any invalid characters
    name = re.sub(r"[^a-zA-Z0-9_\.\-]", "", name)

    # first and last characters cannot be . or -
    name = re.sub(r"^[^a-zA-Z0-9_]+", "", name)
    name = re.sub(r"[^a-zA-Z0-9_]+$", "", name)
    return name
