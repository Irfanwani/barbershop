"""Telling the schema generator how an API key is presented.

Without this, every view in the published schema grows a warning saying the
authenticator could not be resolved - and a schema full of warnings is a schema
nobody reads, which is the opposite of the point of having one.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiKeyScheme(OpenApiAuthenticationExtension):
    target_class = "api_keys.authentication.ApiKeyAuthentication"
    name = "ApiKey"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": (
                "An API key, as `Authorization: ApiKey <prefix>.<secret>`. "
                "Keys act as the account that owns them, never as an identity "
                "of their own."
            ),
        }
