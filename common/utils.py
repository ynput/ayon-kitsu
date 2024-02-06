""" conversion utils with no dependencies for tests """

import re

def to_entity_name(name) -> str:
    """ convert names so they will pass Ayon Entity name validation 
    """
    # @see ayon_server.types.NAME_REGEX = r"^[a-zA-Z0-9_]([a-zA-Z0-9_\.\-]*[a-zA-Z0-9_])?$"
    assert name, "Entity name cannot be empty"

    name = name.strip()

    # replace whitespace
    name = re.sub(r'\s+', "_", name)
    # remove any invalid characters
    name = re.sub(r'[^a-zA-Z0-9_\.\-]', '', name)

    # first and last characters cannot be . or -
    name = re.sub(r'^[^a-zA-Z0-9_]+', '', name)
    name = re.sub(r'[^a-zA-Z0-9_]+$', '', name)
    return name

def to_project_name(name) -> str:
    # @see ayon_server.types.PROJECT_NAME_REGEX = r"^[a-zA-Z0-9_]*$"
    name = to_entity_name(name)
    name = re.sub(r'[^a-zA-Z0-9_]', '', name)
    return name


def to_project_code(code: str) -> str:
    # @see ayon_server.types.PROJECT_CODE_REGEX = r"^[a-zA-Z0-9_][a-zA-Z0-9_]*[a-zA-Z0-9_]$"

    code = to_entity_name(code)

    # remove any invalid characters
    code = re.sub(r'[^a-zA-Z0-9_]', '', code)
    
    # not explicit but the code should be <=10 characters long
    code = code[:10]

    # not explicit but the code should be >=2 characters long
    assert len(code) >= 2, "Project Code should be 2 characters or more"

    return code

def to_label(label:str) -> str:
    # @see ayon_server.types.LABEL_REGEX = r"^[^';]*$"
    return re.sub(r"[';]", '', label)


# // create a ayon name and ayon code
#     // based on pairing.kitsuProjectName
#     // ayon project names can only contain alphanumeric characters and underscores
#     // ayon project codes can only contain alphanumeric characters and must be 3-6 characters long

#     let name = pairing.kitsuProjectName
#     name = name.replace(/[^a-zA-Z0-9_]/g, '_')
#     name = name.replace(/_+/g, '_')
#     name = name.replace(/^_/, '')
#     name = name.replace(/_$/, '')
#     setAyonProjectName(name)

#     let code = pairing.kitsuProjectCode || pairing.kitsuProjectName
#     code = code.replace(/[^a-zA-Z0-9]/g, '')
#     code = code.replace(/_+/g, '')
#     code = code.replace(/^_/, '')
#     code = code.replace(/_$/, '')
#     code = code.toLowerCase()
#     code = code.substring(0, 6)
#     setAyonProjectCode(code)