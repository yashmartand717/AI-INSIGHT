"""The host app owns authorization and recipient relationships. Fail closed."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.utils.module_loading import import_string


class AccessAdapter:
    def school_for(self, user):
        raise PermissionDenied("Configure a school membership adapter")

    def can_manage(self, user, school_id):
        return False

    def validate_records(self, school_id, records):
        """Validate students, classes and permitted data against the host database."""
        raise PermissionDenied("Configure student validation")

    def recipients(self, school_id, student_ids):
        """Return [{email, role, student_ids}] from verified host relationships."""
        raise PermissionDenied("Configure recipient relationships")


def adapter():
    path = getattr(settings, "INSIGHTS_ACCESS_ADAPTER", "")
    if not path:
        raise ImproperlyConfigured("Set INSIGHTS_ACCESS_ADAPTER")
    return import_string(path)()


def management_scope(user):
    access = adapter()
    school = str(access.school_for(user))
    if not school or len(school) > 100 or not access.can_manage(user, school):
        raise PermissionDenied("You cannot manage reports for this school")
    return school
