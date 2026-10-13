from django.apps import AppConfig


class ApiKeysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api_keys"
    verbose_name = "API keys"

    def ready(self) -> None:
        # drf-spectacular finds authentication extensions by import, not by
        # scanning installed apps, so without this every view in the published
        # schema grows a warning about an authenticator it cannot resolve.
        from api_keys import schema  # noqa: F401
