from ayon_applications import PreLaunchHook
import os

class PreStatusChange(PreLaunchHook):
    order = 1
    launch_types = ()
    note_status_shortname = "wip"

    def execute(self):
        import gazu
        kitsuId = self.data["task_entity"]["data"]["kitsuId"]
        
        self.log.debug(f"Changing Kitsu task status to WIP. Task id {kitsuId}")

        try:
            gazu.set_host(os.environ["KITSU_SERVER"])

            gazu.log_in(os.environ["KITSU_LOGIN"], os.environ["KITSU_PWD"])

            kitsu_status = gazu.task.get_task_status_by_short_name(
                self.note_status_shortname
            )


            task=gazu.task.get_task(kitsuId)

            gazu.task.add_comment(task["id"], kitsu_status)    

            gazu.log_out() 
        except:
            self.log.info("Kitsu status change failed")
