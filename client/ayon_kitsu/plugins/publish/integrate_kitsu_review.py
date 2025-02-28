# -*- coding: utf-8 -*-
import gazu
import pyblish.api

from ayon_kitsu.pipeline import KitsuPublishInstancePlugin


class IntegrateKitsuReview(KitsuPublishInstancePlugin):
    """Integrate Kitsu Review"""

    order = pyblish.api.IntegratorOrder + 0.01
    label = "Kitsu Review"
    families = ["kitsu"]
    optional = True

    def process(self, instance):
        # Check comment has been created
        comment_id = instance.data.get("kitsuComment", {}).get("id")
        if not comment_id:
            self.log.debug(
                "Comment not created, review not pushed to preview."
            )
            return

        kitsu_task = instance.data.get("kitsuTask")
        if not kitsu_task:
            self.log.debug("No kitsu task found, skipping review upload.")
            return

        # Add review representations as preview of comment
        task_id = kitsu_task["id"]
        for representation in instance.data.get("representations", []):
            # Skip if not tagged as review
            if "kitsureview" not in representation.get("tags", []):
                self.log.debug(
                    f"Skipping representation {representation['name']} "
                    "because it has no 'kitsureview' tag"
                )
                continue
            review_path = representation.get("published_path")
            self.log.debug(f"Found review at: {review_path}")

            gazu.task.add_preview(
                task=task_id,
                comment=comment_id,
                preview_file_path=review_path,
                normalize_movie=True,
                revision=instance.data["version"],
            )
            self.log.info("Review upload on comment")
