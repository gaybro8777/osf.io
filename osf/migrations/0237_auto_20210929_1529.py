# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2021-09-29 15:29
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django_extensions.db.fields
import osf.models.base
import osf.models.registration_bulk_upload_job
import osf.utils.datetime_aware_jsonfield
import osf.utils.fields


class Migration(migrations.Migration):

    dependencies = [
        ('osf', '0236_auto_20210913_2008'),
    ]

    operations = [
        migrations.CreateModel(
            name='RegistrationBulkUploadJob',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', django_extensions.db.fields.CreationDateTimeField(auto_now_add=True, verbose_name='created')),
                ('modified', django_extensions.db.fields.ModificationDateTimeField(auto_now=True, verbose_name='modified')),
                ('payload_hash', models.CharField(max_length=255, unique=True)),
                ('state', models.IntegerField(choices=[(osf.models.registration_bulk_upload_job.JobState(0), 'PENDING'), (osf.models.registration_bulk_upload_job.JobState(1), 'INITIALIZED'), (osf.models.registration_bulk_upload_job.JobState(2), 'PICKED_UP'), (osf.models.registration_bulk_upload_job.JobState(3), 'DONE_FULL'), (osf.models.registration_bulk_upload_job.JobState(4), 'DONE_PARTIAL'), (osf.models.registration_bulk_upload_job.JobState(5), 'DONE_ERROR')], default=osf.models.registration_bulk_upload_job.JobState(0))),
                ('email_sent', osf.utils.fields.NonNaiveDateTimeField(blank=True, null=True)),
                ('initiator', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('provider', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='osf.RegistrationProvider')),
                ('schema', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='osf.RegistrationSchema')),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model, osf.models.base.QuerySetExplainMixin),
        ),
        migrations.CreateModel(
            name='RegistrationBulkUploadRow',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', django_extensions.db.fields.CreationDateTimeField(auto_now_add=True, verbose_name='created')),
                ('modified', django_extensions.db.fields.ModificationDateTimeField(auto_now=True, verbose_name='modified')),
                ('is_completed', models.BooleanField(default=False)),
                ('is_picked_up', models.BooleanField(default=False)),
                ('csv_raw', models.TextField(default='')),
                ('csv_parsed', osf.utils.datetime_aware_jsonfield.DateTimeAwareJSONField(default=dict, encoder=osf.utils.datetime_aware_jsonfield.DateTimeAwareJSONEncoder)),
                ('row_hash', models.CharField(default='', max_length=255, unique=True)),
                ('draft_registration', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='osf.DraftRegistration')),
                ('upload', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='osf.RegistrationBulkUploadJob')),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model, osf.models.base.QuerySetExplainMixin),
        ),
        migrations.AddField(
            model_name='abstractprovider',
            name='bulk_upload_auto_approval',
            field=models.NullBooleanField(default=False),
        ),
    ]
