"""Media storage backends."""

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class PublicMediaStorage(S3Boto3Storage):
    """S3 bucket for user uploads.

    Profile pictures and shop photos are served straight from S3 rather than
    proxied through Gunicorn, and cached immutably — an uploaded image never
    changes at the same URL.
    """

    location = "media"
    default_acl = "public-read"
    file_overwrite = False
    querystring_auth = False

    @property
    def bucket_name(self) -> str:
        # Only defined when USE_S3 is on, which is also the only time this class
        # is instantiated. Read defensively rather than assuming.
        return str(getattr(settings, "AWS_STORAGE_BUCKET_NAME", ""))
