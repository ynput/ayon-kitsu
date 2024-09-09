from ayon_applications import PreLaunchHook
from ayon_kitsu.addon import is_kitsu_enabled_in_settings

import os
import gazu
import re



class PreStatusChange(PostLaunchHook):
    order = 1
    launch_types = ()

        # status settings
    set_status_app_start_note = False
    app_start_status_shortname = "wip"
    status_change_conditions = {
        "status_conditions": []
        }

        # comment settings
    custom_comment_template = {
        "enabled": False,
        "comment_template": "{comment}",
    }



    def execute(self):
        if not "KITSU_LOGIN" in os.environ:
            self.log.info(f"KITSU_LOGIN is not set. assuming rendeing in deadline. Skipping status.")
            return


        data = self.launch_context.data
        project_settings = data["project_settings"]["kitsu"]["appstart"]

        if project_settings["set_status_app_start_note"]:
            set_status_app_start_note= True
            self.log.info(f"Kitsu Status change is Enabled.")
        else:
            self.log.info(f"Kitsu Status change is disabled.")
            return
        
        if not project_settings["app_start_status_shortname"]:
            self.log.info(f"App starting status in not configured")
            return
        app_start_status_shortname= project_settings["app_start_status_shortname"]

        if project_settings["app_startstatus_change_conditions"]:
            status_conditions= project_settings["app_startstatus_change_conditions"]
        else:
            self.log.info(f"Status change condotions are empty")

        gazu.set_host(os.environ["KITSU_SERVER"])
        gazu.log_in(os.environ["KITSU_LOGIN"], os.environ["KITSU_PWD"])

        if not self.data["task_entity"]["data"]["kitsuId"]:
            self.log.info(f"This task doenst have kitsu task id. Skipping kitsu task change.")
            return
        
        kitsuId = self.data["task_entity"]["data"]["kitsuId"]
        task=gazu.task.get_task(kitsuId)
        task_current_status_shortname= task["task_status"]["short_name"]


        # Check if any status condition is not met
        allow_status_change = True
        for status_cond in status_conditions:
            condition = status_cond["condition"] == "equal"
            match = status_cond["short_name"] == task_current_status_shortname
            if match and not condition or condition and not match:
                allow_status_change = False
                break

        if allow_status_change:
            if not gazu.task.get_task_status_by_short_name(self.app_start_status_shortname):
                self.log.info(f"Failed to recieve kitsu status instance for shortname. Skipping Status change.")
                return
            kitsu_wip_status = gazu.task.get_task_status_by_short_name(self.app_start_status_shortname)
            
            self.log.info(f"Current Kitsu task status is {task_current_status_shortname}. Task id {kitsuId}")
            
            self.log.info(f"Changing Kitsu task status to {self.app_start_status_shortname}.")

            gazu.task.add_comment(task["id"], kitsu_wip_status,)
            self.log.info(task["id"])

            if not project_settings["set_pause_status_to_other_tasks"]:
                self.log.info(f"Pausing all other tasks with same status disabled.")
            else:
                self.log.info(f"Pausing all other tasks with same status enabled.")
                pause_status_shortname= project_settings["psuse_status_shortname"]
                if gazu.task.get_task_status_by_short_name(pause_status_shortname):
                    pause_status=gazu.task.get_task_status_by_short_name(pause_status_shortname)
                    user_tasks= gazu.user.all_tasks_to_do()
                    for other_task in user_tasks:
                        same_status = other_task["task_status_short_name"] == app_start_status_shortname
                        same_task = other_task["id"] == kitsuId
                        if same_status and not same_task:
                            gazu.task.add_comment(other_task["id"], pause_status,)
                else:
                     self.log.info(f"Failed to recieve kitsu pause status instance. Skipping pause Status change.")
        else:
            self.log.info(f"Status not changed due to conditions: {status_conditions}")
                
            
        gazu.log_out() 
