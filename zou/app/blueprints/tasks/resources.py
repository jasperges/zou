import datetime

from flask import abort, request
from flask_restful import Resource, reqparse
from flask_jwt_extended import jwt_required

from zou.app.services.exception import (
    TaskNotFoundException,
    PersonNotFoundException,
    MalformedFileTreeException,
    WrongDateFormatException,
)
from zou.app.services import (
    assets_service,
    deletion_service,
    entities_service,
    files_service,
    file_tree_service,
    news_service,
    notifications_service,
    persons_service,
    projects_service,
    shots_service,
    tasks_service,
    user_service,
)
from zou.app.utils import query, permissions
from zou.app.mixin import ArgsMixin


class CommentTaskResource(Resource):
    """
    Creates a new comment for given task. It requires a text, a task_status
    and a person as arguments. This way, comments keep history of status
    changes. When the comment is created, it updates the task status with
    given task status.
    """

    @jwt_required
    def post(self, task_id):
        (task_status_id, comment, person_id) = self.get_arguments()

        task = tasks_service.get_task(task_id)
        user_service.check_project_access(task["project_id"])
        task_status = tasks_service.get_task_status(task_status_id)

        if person_id:
            person = persons_service.get_person(person_id)
        else:
            person = persons_service.get_current_user()

        comment = tasks_service.create_comment(
            object_id=task_id,
            object_type="Task",
            task_status_id=task_status_id,
            person_id=person["id"],
            text=comment,
        )

        status_changed = task_status_id != task["task_status_id"]
        new_data = {
            "task_status_id": task_status_id,
            "last_comment_date": comment["created_at"],
        }
        if status_changed:
            if task_status["is_retake"]:
                retake_count = task["retake_count"]
                if retake_count is None or retake_count == "NoneType":
                    retake_count = 0
                new_data["retake_count"] = retake_count + 1

            if task_status["is_done"]:
                new_data["end_date"] = datetime.datetime.now()
            else:
                new_data["end_date"] = None

            if (
                task_status["short_name"] == "wip"
                and task["real_start_date"] is None
            ):
                new_data["real_start_date"] = datetime.datetime.now()

        tasks_service.update_task(task_id, new_data)
        task = tasks_service.get_task_with_relations(task_id)

        notifications_service.create_notifications_for_task_and_comment(
            task, comment, change=status_changed
        )
        news_service.create_news_for_task_and_comment(
            task, comment, change=status_changed
        )

        comment["task_status"] = task_status
        comment["person"] = person
        return comment, 201

    def get_arguments(self):
        parser = reqparse.RequestParser()
        parser.add_argument(
            "task_status_id", required=True, help="Task Status ID is missing"
        )
        parser.add_argument("comment", default="")
        parser.add_argument("person_id", default="")
        args = parser.parse_args()

        return (args["task_status_id"], args["comment"], args["person_id"])


class AddPreviewResource(Resource):
    """
    Add a preview to given task. Revision is automatically set: it is
    equal to last revision + 1.
    """

    @jwt_required
    def post(self, task_id, comment_id):
        task = tasks_service.get_task(task_id)
        user_service.check_project_access(task["project_id"])

        comment = tasks_service.get_comment(comment_id)
        tasks_service.get_task_status(comment["task_status_id"])
        person = persons_service.get_current_user()
        preview_file = tasks_service.add_preview_file_to_comment(
            comment_id, person["id"], task_id
        )
        return preview_file, 201


class AddExtraPreviewResource(Resource):
    """
    Add a preview to given comment.
    """

    @jwt_required
    def post(self, task_id, comment_id, preview_file_id):
        task = tasks_service.get_task(task_id)
        user_service.check_project_access(task["project_id"])
        tasks_service.get_comment(comment_id)

        person = persons_service.get_current_user()
        related_preview_file = files_service.get_preview_file(preview_file_id)

        preview_file = tasks_service.add_preview_file_to_comment(
            comment_id, person["id"], task_id, related_preview_file["revision"]
        )
        return preview_file, 201

    @jwt_required
    def delete(self, task_id, comment_id, preview_file_id):
        task = tasks_service.get_task(task_id)
        user_service.check_project_access(task["project_id"])
        deletion_service.remove_preview_file_by_id(preview_file_id)
        return "", 204


class TaskPreviewsResource(Resource):
    """
    Return previews linked to given task.
    """

    @jwt_required
    def get(self, task_id):
        task = tasks_service.get_task(task_id)
        user_service.check_project_access(task["project_id"])
        return files_service.get_preview_files_for_task(task_id)


class TaskCommentsResource(Resource):
    """
    Return comments link to given task.
    """

    @jwt_required
    def get(self, task_id):
        task = tasks_service.get_task(task_id)
        user_service.check_project_access(task["project_id"])
        is_client = permissions.has_client_permissions()
        is_manager = permissions.has_manager_permissions()
        return tasks_service.get_comments(task_id, is_client, is_manager)


class TaskCommentResource(Resource):
    """
    Remove given comment and update linked task accordingly.
    TODO: make deletion authorization stronger
    """

    @jwt_required
    def delete(self, task_id, comment_id):
        task = tasks_service.get_task(task_id)
        user_service.check_project_access(task["project_id"])
        deletion_service.remove_comment(comment_id)
        tasks_service.clear_comment_cache(comment_id)
        return "", 204


class PersonTasksResource(Resource):
    """
    Return task assigned to given user of which status has is_done flag sets
    to false.
    """

    @jwt_required
    def get(self, person_id):
        if not permissions.has_admin_permissions():
            projects = user_service.related_projects()
        else:
            projects = projects_service.open_projects()
        return tasks_service.get_person_tasks(person_id, projects)


class PersonDoneTasksResource(Resource):
    """
    Return task assigned to given user of which status has is_done flag sets
    to true. It return only tasks related to open projects.
    """

    @jwt_required
    def get(self, person_id):
        if not permissions.has_admin_permissions():
            projects = user_service.related_projects()
        else:
            projects = projects_service.open_projects()
        return tasks_service.get_person_done_tasks(person_id, projects)


class CreateShotTasksResource(Resource):
    """
    Create a new task for given shot and task type.
    """

    @jwt_required
    def post(self, task_type_id):
        criterions = query.get_query_criterions_from_request(request)
        if "project_id" not in criterions:
            return {"error": True, "message": "Project ID is missing"}, 400

        user_service.check_manager_project_access(criterions["project_id"])
        shots = shots_service.get_shots(criterions)
        task_type = tasks_service.get_task_type(task_type_id)
        tasks = [tasks_service.create_task(task_type, shot) for shot in shots]
        return tasks, 201


class CreateAssetTasksResource(Resource):
    """
    Create a new task for given asset and task type.
    """

    @jwt_required
    def post(self, task_type_id):
        criterions = query.get_query_criterions_from_request(request)
        if "project_id" not in criterions:
            return {"error": True, "message": "Project ID is missing"}, 400

        user_service.check_manager_project_access(criterions["project_id"])
        assets = assets_service.get_assets(criterions)
        task_type = tasks_service.get_task_type(task_type_id)
        tasks = [
            tasks_service.create_task(task_type, asset) for asset in assets
        ]
        return tasks, 201


class ToReviewResource(Resource):
    """
    Change a task status to "to review". It creates a new preview file entry
    and set path from the hard disk.
    """

    @jwt_required
    def put(self, task_id):
        (
            person_id,
            comment,
            name,
            revision,
            change_status,
        ) = self.get_arguments()

        try:
            task = tasks_service.get_task(task_id)
            user_service.check_project_access(task["project_id"])

            if person_id is not None:
                person = persons_service.get_person(person_id)
            else:
                person = persons_service.get_current_user()

            preview_path = self.get_preview_path(task, name, revision)

            task = tasks_service.task_to_review(
                task["id"], person, comment, preview_path, change_status
            )
        except PersonNotFoundException:
            return {"error": True, "message": "Cannot find given person."}, 400

        return task

    def get_preview_path(self, task, name, revision):
        try:
            folder_path = file_tree_service.get_working_folder_path(
                task, name=name, mode="preview", revision=revision
            )
            file_name = file_tree_service.get_working_file_name(
                task, name=name, mode="preview", revision=revision
            )
        except MalformedFileTreeException:  # No template for preview files.
            return {"folder_path": "", "file_name": ""}

        return {"folder_path": folder_path, "file_name": file_name}

    def get_arguments(self):
        parser = reqparse.RequestParser()
        parser.add_argument("person_id", default=None)
        parser.add_argument("comment", default="")
        parser.add_argument("name", default="main")
        parser.add_argument("revision", default=1, type=int)
        parser.add_argument("change_status", default=True, type=bool)
        args = parser.parse_args()

        return (
            args["person_id"],
            args["comment"],
            args["name"],
            args["revision"],
            args["change_status"],
        )


class ClearAssignationResource(Resource):
    """
    Remove all assignations set to given task.
    """

    @jwt_required
    def put(self):
        (task_ids) = self.get_arguments()

        if len(task_ids) > 0:
            task = tasks_service.get_task(task_ids[0])
            user_service.check_manager_project_access(task["project_id"])

        for task_id in task_ids:
            try:
                tasks_service.clear_assignation(task_id)
            except TaskNotFoundException:
                pass
        return task_ids

    def get_arguments(self):
        parser = reqparse.RequestParser()
        parser.add_argument(
            "task_ids",
            help="Tasks list required.",
            required=True,
            action="append",
        )
        args = parser.parse_args()
        return args["task_ids"]


class TasksAssignResource(Resource):
    """
    Assign given task lists to given person. If a given task ID is wrong,
    it ignores it.
    """

    @jwt_required
    def put(self, person_id):
        (task_ids) = self.get_arguments()

        if len(task_ids) > 0:
            task = tasks_service.get_task(task_ids[0])
            user_service.check_manager_project_access(task["project_id"])

        tasks = []
        for task_id in task_ids:
            try:
                task = self.assign_task(task_id, person_id)
                author = persons_service.get_current_user()
                notifications_service.create_assignation_notification(
                    task_id, person_id, author["id"]
                )
                tasks.append(task)
            except TaskNotFoundException:
                pass
            except PersonNotFoundException:
                return {"error": "Assignee doesn't exist in database."}, 400

        if len(tasks) > 0:
            projects_service.add_team_member(tasks[0]["project_id"], person_id)

        return tasks

    def get_arguments(self):
        parser = reqparse.RequestParser()
        parser.add_argument(
            "task_ids",
            help="Tasks list required.",
            required=True,
            action="append",
        )
        args = parser.parse_args()
        return args["task_ids"]

    def assign_task(self, task_id, person_id):
        return tasks_service.assign_task(task_id, person_id)


class TaskAssignResource(Resource):
    """
    Assign given task to given person.
    """

    @jwt_required
    def put(self, task_id):
        (person_id) = self.get_arguments()

        try:
            task = tasks_service.get_task(task_id)
            user_service.check_manager_project_access(task["project_id"])

            self.assign_task(task_id, person_id)
            notifications_service.create_assignation_notification(
                task_id, person_id
            )
            projects_service.add_team_member(task["project_id"], person_id)
        except PersonNotFoundException:
            return {"error": "Assignee doesn't exist in database."}, 400

        return task

    def get_arguments(self):
        parser = reqparse.RequestParser()
        parser.add_argument(
            "person_id", help="Assignee ID required.", required=True
        )
        args = parser.parse_args()

        return args.get("person_id", "")

    def assign_task(self, task_id, person_id):
        return tasks_service.assign_task(task_id, person_id)


class TaskFullResource(Resource):
    """
    Return a task with many information: full details for assignees, full
    details for task type, full details for task status, etc.
    """

    @jwt_required
    def get(self, task_id):
        task = tasks_service.get_full_task(task_id)
        user_service.check_project_access(task["project_id"])
        return task


class TaskStartResource(Resource):
    """
    Set the status of a given task to Work In Progress.
    """

    @jwt_required
    def put(self, task_id):
        task = tasks_service.get_task(task_id)
        user_service.check_project_access(task["project_id"])
        return tasks_service.start_task(task["id"])


class TaskForEntityResource(Resource):
    """
    Return tasks related to given entity asset, episode, sequence, shot or
    scene.
    """

    @jwt_required
    def get(self, entity_id, task_type_id):
        entity = entities_service.get_entity(entity_id)
        user_service.check_project_access(entity["project_id"])
        return tasks_service.get_tasks_for_entity_and_task_type(
            entity_id, task_type_id
        )


class SetTimeSpentResource(Resource):
    """
    Set time spent by a person on a task for a given day.
    """

    @jwt_required
    def post(self, task_id, date, person_id):
        args = self.get_arguments()

        try:
            task = tasks_service.get_task(task_id)
            user_service.check_project_access(task["project_id"])
            persons_service.get_person(person_id)
            time_spent = tasks_service.create_or_update_time_spent(
                task_id,
                person_id,
                datetime.datetime.strptime(date, "%Y-%m-%d"),
                args["duration"],
            )
            return time_spent, 201
        except ValueError:
            abort(404)
        except WrongDateFormatException:
            abort(404)

    def get_arguments(self):
        parser = reqparse.RequestParser()
        parser.add_argument("duration", default=0)
        args = parser.parse_args()
        return args


class AddTimeSpentResource(Resource):
    """
    Add given timeframe to time spent by a person on a task for a given day.
    """

    @jwt_required
    def post(self, task_id, date, person_id):
        args = self.get_arguments()

        try:
            task = tasks_service.get_task(task_id)
            user_service.check_project_access(task["project_id"])

            persons_service.get_person(person_id)
            time_spent = tasks_service.create_or_update_time_spent(
                task_id, person_id, date, args["duration"], add=True
            )
            return time_spent, 201
        except ValueError:
            abort(404)
        except WrongDateFormatException:
            abort(404)

    def get_arguments(self):
        parser = reqparse.RequestParser()
        parser.add_argument("duration", default=0, type=int)
        args = parser.parse_args()
        return args


class GetTimeSpentResource(Resource):
    """
    Get time spent on a given task by a given person.
    """

    @jwt_required
    def get(self, task_id, date):
        try:
            task = tasks_service.get_task(task_id)
            user_service.check_project_access(task["project_id"])
            return tasks_service.get_time_spents(task_id)
        except WrongDateFormatException:
            abort(404)


class DeleteAllTasksForTaskTypeResource(Resource):
    """
    Delete all tasks for a given task type and project. It's mainly used
    when tasks are created by mistake at the beginning of the project.
    """

    @jwt_required
    def delete(self, project_id, task_type_id):
        permissions.check_admin_permissions()
        projects_service.get_project(project_id)
        task_ids = deletion_service.remove_tasks_for_project_and_task_type(
            project_id, task_type_id
        )
        for task_id in task_ids:
            tasks_service.clear_task_cache(task_id)
        return "", 204


class ProjectSubscriptionsResource(Resource):
    """
    Retrieve all subcriptions to tasks related to given project.
    It's mainly used for synchronisation purpose.
    """

    @jwt_required
    def get(self, project_id):
        permissions.check_admin_permissions()
        projects_service.get_project(project_id)
        return notifications_service.get_subscriptions_for_project(project_id)


class ProjectNotificationsResource(Resource, ArgsMixin):
    """
    Retrieve all notifications related to given project.
    It's mainly used for synchronisation purpose.
    """

    @jwt_required
    def get(self, project_id):
        permissions.check_admin_permissions()
        projects_service.get_project(project_id)
        page = self.get_page()
        return notifications_service.get_notifications_for_project(
            project_id, page
        )


class ProjectTasksResource(Resource, ArgsMixin):
    """
    Retrieve all tasks related to given project.
    It's mainly used for synchronisation purpose.
    """

    @jwt_required
    def get(self, project_id):
        permissions.check_admin_permissions()
        projects_service.get_project(project_id)
        page = self.get_page()
        return tasks_service.get_tasks_for_project(project_id, page)


class ProjectCommentsResource(Resource, ArgsMixin):
    """
    Retrieve all comments to tasks related to given project.
    It's mainly used for synchronisation purpose.
    """

    @jwt_required
    def get(self, project_id):
        permissions.check_admin_permissions()
        projects_service.get_project(project_id)
        page = self.get_page()
        return tasks_service.get_comments_for_project(project_id, page)


class ProjectPreviewFilesResource(Resource, ArgsMixin):
    """
    Retrieve all comments to tasks related to given project.
    It's mainly used for synchronisation purpose.
    """

    @jwt_required
    def get(self, project_id):
        permissions.check_admin_permissions()
        projects_service.get_project(project_id)
        page = self.get_page()
        return files_service.get_preview_files_for_project(project_id, page)
