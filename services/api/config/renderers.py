"""Schema rendering.

drf-spectacular emits the operations inside a path in whatever order the view's
allowed-method set happens to iterate, which varies with Python's hash seed. That
makes the committed ``docs/openapi.yml`` impossible to keep byte-identical
between a developer's machine and CI — the drift check would fail on an unrelated
commit roughly a third of the time.

Canonicalising the order here means the generated file is a function of the code
alone. The drift check is then a real signal rather than a coin flip.
"""

from __future__ import annotations

from copy import deepcopy

from drf_spectacular.renderers import OpenApiYamlRenderer

#: The order methods appear in the document. Chosen to read naturally and,
#: more importantly, to be fixed.
METHOD_ORDER = ["get", "put", "post", "patch", "delete", "head", "options", "trace"]


def canonicalise(schema: dict) -> dict:
    """Return ``schema`` with a deterministic key order."""
    schema = deepcopy(schema)

    for path_item in schema.get("paths", {}).values():
        methods = [key for key in path_item if key in METHOD_ORDER]
        methods.sort(key=METHOD_ORDER.index)
        others = [key for key in path_item if key not in METHOD_ORDER]
        ordered = {key: path_item[key] for key in methods}
        # `parameters` is path-level metadata, not an operation. Last reads best.
        ordered.update({key: path_item[key] for key in sorted(others)})
        path_item.clear()
        path_item.update(ordered)

    components = schema.get("components")
    if isinstance(components, dict):
        for section, entries in components.items():
            if isinstance(entries, dict) and section not in {"securitySchemes"}:
                components[section] = {key: entries[key] for key in sorted(entries)}

    if isinstance(schema.get("tags"), list):
        schema["tags"] = sorted(schema["tags"], key=lambda tag: tag.get("name", ""))

    return schema


class CanonicalOpenApiYamlRenderer(OpenApiYamlRenderer):
    """The project's default schema renderer."""

    def render(self, schema, renderer_context=None):
        return super().render(canonicalise(schema), renderer_context or {})
