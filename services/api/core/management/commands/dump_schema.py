"""Dump the OpenAPI schema to a file, deterministically.

    uv run python manage.py dump_schema                    # to docs/openapi.yml
    uv run python manage.py dump_schema --check            # CI: fail if stale
    uv run python manage.py dump_schema --stdout           # print it

Exists because ``manage.py spectacular`` renders through drf-spectacular's own
YAML renderer, which orders the operations inside a path by set iteration. That
order changes with Python's hash seed, so a committed schema generated on one
machine would not match one generated on another — and the CI drift check would
fail on commits that changed nothing. This command goes through
:mod:`config.renderers` so the output is a function of the code alone.
"""

from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style

from config.renderers import CanonicalOpenApiYamlRenderer


class Command(BaseCommand):
    help = "Generate the OpenAPI schema in a stable, canonical form."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--output",
            default="docs/openapi.yml",
            help="Where to write the schema. Relative to services/api.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Do not write. Exit non-zero if the committed file is out of date.",
        )
        parser.add_argument("--stdout", action="store_true", help="Print instead of writing.")
        parser.add_argument(
            "--fail-on-warn",
            action="store_true",
            default=True,
            help="Fail on schema warnings (default).",
        )

    def handle(self, *args, **options) -> None:
        from pathlib import Path

        from django.conf import settings
        from drf_spectacular.generators import SchemaGenerator

        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)
        errors = getattr(generator, "errors", None) or []

        if options["fail_on_warn"] and errors:
            raise CommandError(
                "Schema generation produced errors:\n"
                + "\n".join(f"  {error}" for error in errors[:20])
            )

        rendered = CanonicalOpenApiYamlRenderer().render(
            schema, renderer_context={"indent": 2, "no_style": no_style()}
        )
        if isinstance(rendered, bytes):
            rendered = rendered.decode("utf-8")

        target = Path(options["output"])
        if not target.is_absolute():
            target = Path(settings.BASE_DIR) / target

        if options["stdout"]:
            sys.stdout.write(rendered)
            return

        if options["check"]:
            if not target.exists():
                raise CommandError(
                    f"{target} does not exist. Generate it with:\n"
                    f"  cd services/api && uv run python manage.py dump_schema"
                )
            if target.read_text(encoding="utf-8") != rendered:
                raise CommandError(
                    f"{target.name} is out of date. Regenerate it with:\n"
                    f"  cd services/api && uv run python manage.py dump_schema"
                )
            self.stdout.write(self.style.SUCCESS(f"{target.name} is up to date."))
            return

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {target}"))
