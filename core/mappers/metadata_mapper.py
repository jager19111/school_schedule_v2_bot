from core.models.dto import (
    ClassListDTO,
    GroupListDTO,
    TeacherListDTO, SchoolDictionariesDTO
)
from core.models.metadata import SchoolMetadata


class MetadataMapper:
    @staticmethod
    def to_class_list_dto(
        metadata: SchoolMetadata,
    ) -> ClassListDTO:
        return ClassListDTO(
            classes={
                class_id: school_class.name
                for class_id, school_class in metadata.classes.items()
            }
        )

    @staticmethod
    def to_teacher_list_dto(
        metadata: SchoolMetadata,
    ) -> TeacherListDTO:
        return TeacherListDTO(
            teachers={
                teacher_id: teacher.name
                for teacher_id, teacher in metadata.teachers.items()
            }
        )

    @staticmethod
    def to_group_list_dto(
        metadata: SchoolMetadata,
    ) -> GroupListDTO:
        return GroupListDTO(
            groups=dict(metadata.groups)
        )
        

    @staticmethod
    def to_school_dictionaries(
        metadata: SchoolMetadata,
    ) -> SchoolDictionariesDTO:
        """SchoolMetadata -> SchoolDictionariesDTO (справочники для клавиатур)."""
        return SchoolDictionariesDTO(
            classes={
                class_id: school_class.name
                for class_id, school_class in metadata.classes.items()
            },
            groups=dict(metadata.groups),
        )
