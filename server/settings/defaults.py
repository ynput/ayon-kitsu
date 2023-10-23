DEFAULT_VALUES = {
    "entities_naming_pattern": {"episode": "E##", "sequence": "SQ##", "shot": "SH##"},
    "publish": {
        "IntegrateKitsuNote": {
            "set_status_note": False,
            "note_status_shortname": "wfa",
            "status_change_conditions": {
                "status_conditions": [],
                "product_type_requirements": [],
            },
            "custom_comment_template": {
                "enabled": False,
                "comment_template": "{comment}\n\n|  |  |\n|--|--|\n| version| `{version}` |\n| product type | `{product[type]}` |\n| name | `{name}` |",
            },
        }
    },
}
