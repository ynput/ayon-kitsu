import ayon_api
import gazu 

def sync_project_statuses():
    # Récupère les statuses Kitsu
    kitsu_statuses = gazu.task.all_task_statuses()
    kitsu_statuses.sort(key=lambda x: not x.get("is_default"))
    print(f"@@@@@@@@ kitsu_statuses\n{kitsu_statuses}\n")
    # Récupère les settings AYON pour le mapping
    settings = ayon_api.get_addon_settings("kitsu", "1.2.7")
    default_status_info = (
        settings["sync_settings"]["default_sync_info"]["default_status_info"]
    )
    print(f"@@@@@@@@ default_status_info\n{default_status_info}\n")

    # Mapping Kitsu → AYON
    for status in kitsu_statuses:
        found = False
        for settings_status in default_status_info:
            if status["short_name"] == settings_status["short_name"]:
                print(f"@@@@@@@@ status\n{status}\n")
                print(f"@@@@@@@@ settings_status\n{settings_status}\n")
                found = True
                status["icon"] = settings_status["icon"]
                status["state"] = settings_status["state"]
        if not found:
            status["icon"] = "task_alt"
            status["state"] = "in_progress"

    statuses = [
        {
            "name": s["name"],
            "shortName": s["short_name"],
            "color": s["color"],
            "state": s["state"],
            "icon": s["icon"],
        }
        for s in kitsu_statuses
    ]
    print(f"@@@@@@@@ statuses\n{statuses}\n")


    # anatomy_dict = anatomy.dict()
    # for key in anatomy_dict["attributes"]:
    #     if key in attributes:
    #         anatomy_dict["attributes"][key] = attributes[key]
    #         logging.debug(
    #             "updated project",
    #             prj_name,
    #             "anatomy attribute",
    #             key,
    #             "to",
    #             attributes[key],
    #         )

    # anatomy_dict["statuses"] = statuses