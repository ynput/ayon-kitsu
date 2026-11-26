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

    normalize_movie = True
    match_version_number = True

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
        revision = (
            instance.data["version"] if self.match_version_number else None
        )
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

            preview_file = self.create_preview(task_id, comment_id, revision)
            gazu.task.upload_preview_file(
                preview_file,
                review_path,
                normalize_movie=self.normalize_movie,
            )
            self.log.info("Review upload on comment")

    def create_preview(self, task_id, comment_id, revision):
        """Create the preview. Let Kitsu set the revision if it is taken.

        Kitsu counts revisions for each task, not for each product. Thus
        the AYON version can already exist as a revision on the task.
        """
        try:
            return gazu.task.create_preview(
                task_id, comment_id, revision=revision
            )
        except gazu.exception.ParameterException as e:
            if revision is None:
                raise
            self.log.warning(
                f"Kitsu does not accept revision {revision}: {e}."
                " Kitsu sets the revision number."
            )
            return gazu.task.create_preview(task_id, comment_id)
