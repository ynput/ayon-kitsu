def required_values(entity: dict, keys: list[str], allow_empty_value=False):
    """check the entity dict has the required keys and a value for each"""
    values = []
    for key in keys:
        if key not in entity:
            raise ValueError(f"Key '{key}' not set for entity: {entity}")
        if not allow_empty_value and not entity.get(key):
            raise ValueError(f"Value for  '{key}' cannot be empty for entity: {entity}")
        values.append(entity.get(key))
    return values
