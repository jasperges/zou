import datetime

from flask import request, abort, current_app
from flask_restful import Resource, reqparse
from flask_jwt_extended import jwt_required

from zou.app.mixin import ArgsMixin
from zou.app.utils import permissions
from zou.app.services import (
    file_tree,
    files_service,
    persons_service,
    projects_service,
    assets_service,
    tasks_service,
    entities_service,
    user_service
)

from zou.app.services.exception import (
    WorkingFileNotFoundException,
    OutputTypeNotFoundException,
    PersonNotFoundException,
    WrongFileTreeFileException,
    MalformedFileTreeException,
    EntryAlreadyExistsException
)


class WorkingFilePathResource(Resource):

    @jwt_required
    def post(self, task_id):
        (
            name,
            mode,
            software_id,
            comment,
            revision,
            separator
        ) = self.get_arguments()

        try:
            task = tasks_service.get_task(task_id)
            if not permissions.has_manager_permissions():
                user_service.check_has_task_related(task["project_id"])

            software = files_service.get_software(software_id)
            is_revision_set_by_user = revision != 0
            if not is_revision_set_by_user:
                revision = files_service.get_next_working_file_revision(
                    task_id,
                    name
                )
            file_path = file_tree.get_working_folder_path(
                task,
                mode=mode,
                software=software,
                name=name,
                sep=separator
            )
            file_name = file_tree.get_working_file_name(
                task,
                mode=mode,
                revision=revision,
                software=software,
                name=name
            )
        except MalformedFileTreeException:
            return {
                "error":
                    "Tree is not properly written, check modes and variables",
                "received_data": request.json,
            }, 400

        return {"path": file_path, "name": file_name}, 200

    def get_arguments(self):
        maxsoft = files_service.get_or_create_software("3ds Max", "max", ".max")

        parser = reqparse.RequestParser()
        parser.add_argument("name", default="main")
        parser.add_argument("mode", default="working")
        parser.add_argument("software_id", default=maxsoft["id"])
        parser.add_argument("comment", default="")
        parser.add_argument("revision", default=0)
        parser.add_argument("sep", default="/")
        args = parser.parse_args()

        return (
            args["name"],
            args["mode"],
            args["software_id"],
            args["comment"],
            args["revision"],
            args["sep"]
        )


class EntityOutputFilePathResource(Resource, ArgsMixin):

    @jwt_required
    def post(self, entity_id):
        args = self.get_arguments()

        try:
            entity = entities_service.get_entity(entity_id)
            if not permissions.has_manager_permissions():
                user_service.check_has_task_related(entity["project_id"])

            output_type = files_service.get_output_type(
                args["output_type_id"]
            )
            task_type = tasks_service.get_task_type(args["task_type_id"])
            entity = entities_service.get_entity(entity_id)
            if not permissions.has_manager_permissions():
                user_service.check_has_task_related(entity["project_id"])

            is_revision_set_by_user = args["revision"] != 0
            if not is_revision_set_by_user:
                revision = files_service.get_next_output_file_revision(
                    entity_id,
                    args["name"]
                )
            else:
                revision = args["revision"]

            folder_path = file_tree.get_output_folder_path(
                entity,
                mode=args["mode"],
                output_type=output_type,
                task_type=task_type,
                name=args["name"],
                sep=args["separator"],
                revision=args["revision"]
            )
            file_name = file_tree.get_output_file_name(
                entity,
                mode=args["mode"],
                revision=revision,
                output_type=output_type,
                task_type=task_type,
                name=args["name"]
            )
        except MalformedFileTreeException:
            return {
                "error":
                    "Tree is not properly written, check modes and variables",
                "received_data": request.json,
            }, 400

        return {"folder_path": folder_path, "file_name": file_name}, 200

    def get_arguments(self):
        return self.get_args([
            ("name", "main", False),
            ("mode", "output", False),
            ("output_type_id", None, True),
            ("task_type_id", None, True),
            ("revision", 0, False),
            ("extension", "", False),
            ("separator", "/", False)
        ])


class LastWorkingFilesResource(Resource):

    @jwt_required
    def get(self, task_id):
        result = {}
        task = tasks_service.get_task(task_id)
        if not permissions.has_manager_permissions():
            user_service.check_has_task_related(task["project_id"])
        result = files_service.get_last_working_files_for_task(task["id"])

        return result


class TaskWorkingFilesResource(Resource):

    @jwt_required
    def get(self, task_id):
        result = {}
        task = tasks_service.get_task(task_id)
        if not permissions.has_manager_permissions():
            user_service.check_has_task_related(task["project_id"])
        result = files_service.get_working_files_for_task(task["id"])

        return result


class NewWorkingFileResource(Resource):

    @jwt_required
    def post(self, task_id):
        (
            name,
            description,
            comment,
            person_id,
            software_id,
            revision,
            sep
        ) = self.get_arguments()

        try:
            task = tasks_service.get_task(task_id)
            if not permissions.has_manager_permissions():
                user_service.check_has_task_related(task["project_id"])
            software = files_service.get_software(software_id)
            tasks_service.assign_task(
                task_id,
                persons_service.get_current_user()["id"]
            )

            if revision == 0:
                revision = files_service.get_next_working_revision(
                    task_id,
                    name
                )

            path = self.build_path(task, name, revision, software, sep)

            working_file = files_service.create_new_working_revision(
                task_id,
                person_id,
                software_id,
                name=name,
                path=path,
                comment=comment,
                revision=revision
            )
        except EntryAlreadyExistsException:
            return {"error": "The given working file already exists."}, 400

        return working_file, 201

    def build_path(self, task, name, revision, software, sep):
        folder_path = file_tree.get_working_folder_path(
            task,
            name=name,
            software=software
        )
        file_name = file_tree.get_working_file_name(
            task,
            name=name,
            software=software,
            revision=revision
        )
        return "%s%s%s" % (folder_path, sep, file_name)

    def get_arguments(self):
        person = persons_service.get_current_user()
        maxsoft = files_service.get_or_create_software("3ds Max", "max", ".max")

        parser = reqparse.RequestParser()
        parser.add_argument(
            "name",
            help="The asset name is required.",
            required=True
        )
        parser.add_argument("description", default="")
        parser.add_argument("comment", default="")
        parser.add_argument("person_id", default=person["id"])
        parser.add_argument("software_id", default=maxsoft["id"])
        parser.add_argument("revision", default=0, type=int)
        parser.add_argument("sep", default="/")
        args = parser.parse_args()
        return (
            args["name"],
            args["description"],
            args["comment"],
            args["person_id"],
            args["software_id"],
            args["revision"],
            args["sep"]
        )


class ModifiedFileResource(Resource):

    @jwt_required
    def put(self, working_file_id):
        working_file = files_service.get_working_file(working_file_id)
        task = tasks_service.get_task(working_file["task_id"])
        if not permissions.has_manager_permissions():
            user_service.check_has_task_related(task["project_id"])
        working_file = files_service.update_working_file(
            working_file_id,
            {"updated_at": datetime.datetime.utcnow()}
        )
        return working_file


class CommentWorkingFileResource(Resource):

    @jwt_required
    def put(self, working_file_id):
        comment = self.get_comment_from_args()
        working_file = files_service.get_working_file(working_file_id)
        task = tasks_service.get_task(working_file["task_id"])
        if not permissions.has_manager_permissions():
            user_service.check_has_task_related(task["project_id"])
        working_file = self.update_comment(working_file_id, comment)
        return working_file

    def get_comment_from_args(self):
        parser = reqparse.RequestParser()
        parser.add_argument(
            "comment",
            required=True,
            help="Comment field expected."
        )
        args = parser.parse_args()
        comment = args["comment"]
        return comment

    def update_comment(self, working_file_id, comment):
        working_file = files_service.update_working_file(
            working_file_id,
            {"comment": comment}
        )
        return working_file


class InstanceOutputFilePathResource(Resource, ArgsMixin):

    @jwt_required
    def post(self, asset_instance_id):
        (
            name,
            mode,
            output_type_id,
            task_type_id,
            revision,
            separator
        ) = self.get_arguments()

        try:
            asset_instance = assets_service.get_asset_instance(
                asset_instance_id)
            asset = assets_service.get_asset(asset_instance["asset_id"])
            output_type = files_service.get_output_type(output_type_id)
            task_type = tasks_service.get_task_type(task_type_id)
            if not permissions.has_manager_permissions():
                user_service.check_has_task_related(asset["project_id"])

            folder_path = file_tree.get_instance_folder_path(
                asset_instance,
                output_type=output_type,
                task_type=task_type,
                mode=mode,
                name=name,
                revision=revision,
                sep=separator
            )
            file_name = file_tree.get_instance_file_name(
                asset_instance,
                output_type=output_type,
                task_type=task_type,
                mode=mode,
                name=name,
                revision=revision
            )
        except MalformedFileTreeException as e:
            current_app.logger.error(e)
            return {
                "error":
                    "Tree is not properly written, check modes and variables",
                "received_data": request.json,
            }, 400

        return {"path": folder_path, "name": file_name}, 200

    def get_arguments(self):
        args = self.get_args([
            ("name", "main", False),
            ("mode", "output", False),
            ("output_type_id", None, True),
            ("task_type_id", None, True),
            ("revision", 0, False),
            ("sep", "/", False)
        ])
        return (
            args["name"],
            args["mode"],
            args["output_type_id"],
            args["task_type_id"],
            args["revision"],
            args["sep"]
        )


class SetTreeResource(Resource):

    @jwt_required
    def post(self, project_id):
        (tree_name) = self.get_arguments()

        try:
            permissions.check_manager_permissions()
            tree = file_tree.get_tree_from_file(tree_name)
            project = projects_service.update_project(
                project_id,
                {"file_tree": tree}
            )
        except WrongFileTreeFileException:
            abort(400, "Selected tree is not available")

        return project

    def get_arguments(self):
        parser = reqparse.RequestParser()
        parser.add_argument(
            "tree_name",
            help="The name of the tree to set is required.",
            required=True
        )
        args = parser.parse_args()

        return (
            args.get("tree_name", ""),
        )


class NewEntityOutputFileResource(Resource, ArgsMixin):

    @jwt_required
    def post(self, entity_id):
        args = self.get_arguments()

        try:
            revision = int(args["revision"])

            try:
                working_file = files_service.get_working_file(
                    args["working_file_id"]
                )
                working_file_id = working_file["id"]
            except WorkingFileNotFoundException:
                pass

            entity = entities_service.get_entity(entity_id)
            if not permissions.has_manager_permissions():
                user_service.check_has_task_related(entity["project_id"])
            output_type = files_service.get_output_type(args["output_type_id"])
            task_type = tasks_service.get_task_type(args["task_type_id"])

            if args["person_id"] is None:
                person = persons_service.get_current_user()
            else:
                person = persons_service.get_person(args["person_id"])

            output_file = files_service.create_new_output_revision(
                entity_id,
                working_file_id,
                output_type["id"],
                person["id"],
                args["task_type_id"],
                revision=revision,
                name=args["name"],
                comment=args["comment"],
                extension=args["extension"]
            )

            output_file_dict = self.add_path_info(
                output_file,
                "output",
                entity,
                output_type,
                task_type=task_type,
                name=args["name"],
                extension=args["extension"],
                separator=args["sep"]
            )
        except OutputTypeNotFoundException:
            return {"error": "Cannot find given output type."}, 400
        except PersonNotFoundException:
            return {"error": "Cannot find given person."}, 400
        except EntryAlreadyExistsException:
            return {"error": "The given output file already exists."}, 400

        return output_file_dict, 201

    def get_arguments(self):
        return self.get_args([
            ("name", "main", False),
            ("mode", "output", False),
            ("output_type_id", None, True),
            ("task_type_id", None, True),
            ("person_id", None, False),
            ("working_file_id", "", True),
            ("comment", "", True),
            ("revision", 0, False),
            ("extension", "", False),
            ("sep", "/", False)
        ])

    def add_path_info(
        self,
        output_file,
        mode,
        entity,
        output_type,
        task_type=None,
        name="main",
        extension="",
        separator="/"
    ):
        folder_path = file_tree.get_output_folder_path(
            entity,
            mode=mode,
            output_type=output_type,
            task_type=task_type,
            name=name,
            sep=separator
        )
        file_name = file_tree.get_output_file_name(
            entity,
            mode=mode,
            revision=output_file["revision"],
            output_type=output_type,
            task_type=task_type,
            name=name
        )

        output_file.update({
            "folder_path": folder_path,
            "file_name": file_name
        })

        files_service.update_output_file(
            output_file["id"],
            {
                "path": "%s%s%s%s" % (
                    folder_path,
                    separator,
                    file_name,
                    extension
                )
            }
        )
        return output_file


class NewInstanceOutputFileResource(Resource, ArgsMixin):

    @jwt_required
    def post(self, asset_instance_id):
        args = self.get_arguments()

        try:
            revision = int(args["revision"])
            try:
                working_file = files_service.get_working_file(
                    args["working_file_id"]
                )
                working_file_id = working_file["id"]
            except WorkingFileNotFoundException:
                pass
            asset_instance = assets_service.get_asset_instance(
                asset_instance_id
            )

            entity = assets_service.get_asset(asset_instance["asset_id"])
            if not permissions.has_manager_permissions():
                user_service.check_has_task_related(entity["project_id"])

            output_type = files_service.get_output_type(args["output_type_id"])
            task_type = tasks_service.get_task_type(args["task_type_id"])
            if args["person_id"] is None:
                person = persons_service.get_current_user()
            else:
                person = persons_service.get_person(args["person_id"])

            output_file = files_service.create_new_output_revision(
                asset_instance["asset_id"],
                working_file_id,
                output_type["id"],
                person["id"],
                task_type["id"],
                asset_instance_id=asset_instance["id"],
                revision=revision,
                name=args["name"],
                comment=args["comment"],
                extension=args["extension"]
            )

            output_file_dict = self.add_path_info(
                output_file,
                "output",
                asset_instance,
                output_type,
                task_type=task_type,
                name=args["name"],
                extension=args["extension"],
                separator=args["sep"]
            )
        except OutputTypeNotFoundException:
            return {"message": "Cannot find given output type."}, 400
        except PersonNotFoundException:
            return {"message": "Cannot find given person."}, 400
        except EntryAlreadyExistsException:
            return {"message": "The given output file already exists."}, 400

        return output_file_dict, 201

    def get_arguments(self):
        return self.get_args([
            ("name", "main", False),
            ("mode", "output", False),
            ("output_type_id", None, True),
            ("task_type_id", None, True),
            ("person_id", None, False),
            ("working_file_id", "", True),
            ("comment", "", True),
            ("revision", 0, False),
            ("extension", "", False),
            ("sep", "/", False)
        ])

    def add_path_info(
        self,
        output_file,
        mode,
        asset_instance,
        output_type,
        task_type=None,
        name="main",
        extension="",
        separator="/"
    ):
        folder_path = file_tree.get_instance_folder_path(
            asset_instance,
            mode=mode,
            output_type=output_type,
            task_type=task_type,
            name=name,
            sep=separator
        )
        file_name = file_tree.get_instance_file_name(
            asset_instance,
            mode=mode,
            revision=output_file["revision"],
            output_type=output_type,
            task_type=task_type,
            name=name
        )

        output_file.update({
            "folder_path": folder_path,
            "file_name": file_name
        })

        files_service.update_output_file(
            output_file["id"],
            {
                "path": "%s%s%s%s" % (
                    folder_path,
                    separator,
                    file_name,
                    extension
                )
            }
        )
        return output_file


class GetNextEntityOutputFileRevisionResource(Resource, ArgsMixin):

    @jwt_required
    def post(self, entity_id):
        args = self.get_arguments()
        entity = entities_service.get_entity(entity_id)
        output_type = files_service.get_output_type(args["output_type_id"])
        task_type = tasks_service.get_task_type(args["task_type_id"])
        if not permissions.has_manager_permissions():
            user_service.check_has_task_related(entity["project_id"])

        next_revision_number = \
            files_service.get_next_output_file_revision(
                entity["id"],
                output_type["id"],
                task_type["id"],
                args["name"]
            )

        return {
            "next_revision": next_revision_number
        }, 200

    def get_arguments(self):
        return self.get_args([
            ("name", "main", False),
            ("output_type_id", None, True),
            ("task_type_id", None, True)
        ])


class GetNextInstanceOutputFileRevisionResource(Resource, ArgsMixin):

    @jwt_required
    def post(self, asset_instance_id):
        args = self.get_arguments()

        asset_instance = assets_service.get_asset_instance(asset_instance_id)
        entity = entities_service.get_entity(asset_instance["asset_id"])
        output_type = files_service.get_output_type(args["output_type_id"])
        task_type = tasks_service.get_task_type(args["task_type_id"])
        if not permissions.has_manager_permissions():
            user_service.check_has_task_related(entity["project_id"])

        next_revision_number = \
            files_service.get_next_output_file_revision(
                entity["id"],
                output_type["id"],
                task_type["id"],
                args["name"],
                asset_instance_id=asset_instance["id"]
            )

        return {
            "next_revision": next_revision_number
        }, 200

    def get_arguments(self):
        return self.get_args([
            ("name", "main", False),
            ("output_type_id", None, True),
            ("task_type_id", None, True)
        ])


class LastEntityOutputFilesResource(Resource):

    @jwt_required
    def get(self, entity_id):
        entity = entities_service.get_entity(entity_id)
        if not permissions.has_manager_permissions():
            user_service.check_has_task_related(entity["project_id"])
        return files_service.get_last_output_files_for_entity(entity["id"])


class LastInstanceOutputFilesResource(Resource):

    @jwt_required
    def get(self, asset_instance_id):
        asset_instance = assets_service.get_asset_instance(asset_instance_id)
        entity = entities_service.get_entity(asset_instance["asset_id"])
        if not permissions.has_manager_permissions():
            user_service.check_has_task_related(entity["project_id"])
        return files_service.get_last_output_files_for_instance(
            asset_instance["id"]
        )


class EntityOutputTypesResource(Resource):

    @jwt_required
    def get(self, entity_id):
        entity = entities_service.get_entity(entity_id)
        user_service.check_project_access(entity["project_id"])
        return files_service.get_output_types_for_entity(entity_id)


class InstanceOutputTypesResource(Resource):

    @jwt_required
    def get(self, asset_instance_id):
        asset_instance = assets_service.get_asset_instance(asset_instance_id)
        entity = entities_service.get_entity(asset_instance["asset_id"])
        user_service.check_project_access(entity["project_id"])
        return files_service.get_output_types_for_instance(asset_instance_id)


class EntityOutputTypeOutputFilesResource(Resource):

    @jwt_required
    def get(self, entity_id, output_type_id):
        entity = entities_service.get_entity(entity_id)
        files_service.get_output_type(output_type_id)
        user_service.check_project_access(entity["project_id"])
        return files_service.get_output_files_for_output_types_and_entity(
            entity_id,
            output_type_id
        )


class InstanceOutputTypeOutputFilesResource(Resource):

    @jwt_required
    def get(self, asset_instance_id, output_type_id):
        asset_instance = assets_service.get_asset_instance(asset_instance_id)
        asset = assets_service.get_asset(asset_instance["asset_id"])
        user_service.check_project_access(asset["project_id"])

        files_service.get_output_type(output_type_id)
        return files_service.get_output_files_for_output_type_and_asset_instance(
            asset_instance_id,
            output_type_id
        )


class FileResource(Resource):

    @jwt_required
    def get(self, file_id):
        try:
            file_dict = files_service.get_working_file(file_id)
            task = tasks_service.get_task(file_dict["task_id"])
            project_id = task["project_id"]
        except WorkingFileNotFoundException:
            file_dict = files_service.get_output_file(file_id)
            entity = entities_service.get_entity(file_dict["entity_id"])
            project_id = entity["project_id"]

        if not permissions.has_manager_permissions():
            user_service.check_has_task_related(project_id)
        return file_dict
