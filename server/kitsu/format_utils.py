import unicodedata
import re
from nxtools import slugify


def create_short_name(name: str) -> str:
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


def create_name_and_label(kitsu_name: str) -> dict[str, str]:
    """From a name coming from kitsu, create a name and label."""
    return {
        "name": slugify(kitsu_name, separator="_"),
        "label": to_label(kitsu_name),
    }


def to_username(first_name: str, last_name: str | None = None) -> str:
    """converts usernames from kitsu - converts accents"""

    name = (
        f"{first_name.strip()}.{last_name.strip()}" if last_name else first_name.strip()
    )

    name = name.lower()
    name = remove_accents(name)
    return to_entity_name(name)


def to_project_name(name: str) -> str:
    # @see ayon_server.types.PROJECT_NAME_REGEX = r"^[a-zA-Z0-9_]*$"
    name = to_entity_name(name)
    # remove any unsupported characters
    name = re.sub(r"[^a-zA-Z0-9_]", "", name)
    return name


def to_project_code(code: str) -> str:
    # @see ayon_server.types.PROJECT_CODE_REGEX = r"^[a-zA-Z0-9_][a-zA-Z0-9_]*[a-zA-Z0-9_]$"

    code = to_entity_name(code)

    # remove any invalid characters
    code = re.sub(r"[^a-zA-Z0-9_]", "", code)

    # not explicit but the code should be <=10 characters long
    code = code[:10]

    # not explicit but the code should be >=2 characters long
    assert len(code) >= 2, "Project Code should be 2 characters or more"

    return code


def to_label(label: str) -> str:
    # @see ayon_server.types.LABEL_REGEX = r"^[^';]*$"
    return re.sub(r"[';]", "", label)


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


def to_entity_name(name) -> str:
    """convert names so they will pass Ayon Entity name validation"""
    # @see ayon_server.types.NAME_REGEX = r"^[a-zA-Z0-9_]([a-zA-Z0-9_\.\-]*[a-zA-Z0-9_])?$"
    assert name, "Entity name cannot be empty"

    name = name.strip()

    # replace whitespace
    name = re.sub(r"\s+", "_", name)
    # remove any invalid characters
    name = re.sub(r"[^a-zA-Z0-9_\.\-]", "", name)

    # first and last characters cannot be . or -
    name = re.sub(r"^[^a-zA-Z0-9_]+", "", name)
    name = re.sub(r"[^a-zA-Z0-9_]+$", "", name)
    return name
