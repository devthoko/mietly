from .models import AuditLog


def log(user, action, message, obj=None, order=None, **data):
    if user is not None and not getattr(user, "is_authenticated", False):
        user = None
    return AuditLog.objects.create(
        user=user,
        action=action,
        message=message[:500],
        object_type=obj._meta.label if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        order=order,
        data=data,
    )
