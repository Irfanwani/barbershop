"""Give every shop a public address.

Three steps rather than one, because a unique index cannot be built while
every row still holds the same empty slug — which is exactly the state a
plain `AddField` leaves the table in.
"""

import django.core.validators
from django.db import migrations, models
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    """Give every existing shop an address.

    These shops are already linked to from Instagram bios and printed
    leaflets. A column that starts empty leaves every one of them 404ing the
    moment this ships.
    """
    Provider = apps.get_model("providers", "ProviderProfile")

    # Materialised, not a server-side cursor: this loop writes to the table it
    # is reading, and a cursor that sees its own writes re-reads rows forever.
    for provider in list(Provider.objects.filter(slug__isnull=True).only("pk", "display_name")):
        base = slugify(provider.display_name)[:60] or "shop"
        candidate = base
        suffix = 2
        while Provider.objects.filter(slug=candidate).exclude(pk=provider.pk).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1

        provider.slug = candidate
        provider.save(update_fields=["slug"])


class Migration(migrations.Migration):
    dependencies = [
        ("providers", "0007_staff_staffworkinghours_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="providerprofile",
            name="slug",
            # db_index=False deliberately: a SlugField indexes itself by
            # default, and the unique index added below would be the second
            # index under the same name. The column is added bare, filled, and
            # only then indexed.
            field=models.SlugField(blank=True, db_index=False, max_length=80, null=True),
        ),
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="providerprofile",
            name="slug",
            field=models.SlugField(blank=True, max_length=80, unique=True),
        ),
    ]
