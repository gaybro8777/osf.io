from django.core.exceptions import ValidationError
from rest_framework import exceptions
from rest_framework import serializers as ser

from api.base.exceptions import Conflict
from api.base.serializers import (
    JSONAPISerializer, IDField, TypeField, HideIfWithdrawal, HideIfNotWithdrawal,
    LinksField, RelationshipField, VersionedDateTimeField, JSONAPIListField,
    ShowIfVersion, NodeFileHyperLinkField, WaterbutlerLink, HideIfPreprint
)
from api.base.utils import absolute_reverse, get_user_auth
from api.nodes.serializers import (
    NodeCitationSerializer,
    NodeLicenseSerializer,
    NodeContributorsSerializer,
    NodeProviderSerializer,
    NodeContributorsCreateSerializer,
    NodeContributorDetailSerializer,
    get_license_details,
    NodeTagField
)
from api.taxonomies.serializers import TaxonomizableSerializerMixin
from framework.exceptions import PermissionsError
from website import settings
from website.exceptions import NodeStateError
from osf.exceptions import PreprintProviderError
from website.project import signals as project_signals
from osf.models import BaseFileNode, Preprint, PreprintProvider, Node, NodeLicense
from osf.utils import permissions as osf_permissions


class PrimaryFileRelationshipField(RelationshipField):
    def get_object(self, file_id):
        return BaseFileNode.load(file_id)

    def to_internal_value(self, data):
        file = self.get_object(data)
        return {'primary_file': file}

class NodeRelationshipField(RelationshipField):
    def get_object(self, node_id):
        try:
            return Node.load(node_id)
        except AttributeError:
            raise exceptions.ValidationError(detail='Node not correctly specified.')

    def to_internal_value(self, data):
        node = self.get_object(data)
        return {'node': node}

class PreprintProviderRelationshipField(RelationshipField):
    def get_object(self, node_id):
        return PreprintProvider.load(node_id)

    def to_internal_value(self, data):
        provider = self.get_object(data)
        return {'provider': provider}


class PreprintLicenseRelationshipField(RelationshipField):
    def to_internal_value(self, license_id):
        license = NodeLicense.load(license_id)
        if license:
            return {'license_type': license}
        raise exceptions.NotFound('Unable to find specified license.')


class PreprintSerializer(TaxonomizableSerializerMixin, JSONAPISerializer):
    filterable_fields = frozenset([
        'id',
        'date_created',
        'date_modified',
        'date_published',
        'original_publication_date',
        'provider',
        'is_published',
        'subjects',
        'reviews_state',
        'node_is_public',
    ])

    id = IDField(source='_id', read_only=True)
    type = TypeField()

    date_created = VersionedDateTimeField(source='created', read_only=True)
    date_modified = VersionedDateTimeField(source='modified', read_only=True)
    date_published = VersionedDateTimeField(read_only=True)
    original_publication_date = VersionedDateTimeField(required=False)
    doi = ser.CharField(source='article_doi', required=False, allow_null=True)
    is_published = HideIfWithdrawal(ser.BooleanField(required=False))
    is_preprint_orphan = HideIfWithdrawal(ser.BooleanField(read_only=True))
    license_record = HideIfWithdrawal(NodeLicenseSerializer(required=False, source='license'))
    title = ser.CharField(required=True, max_length=512)
    description = ser.CharField(required=False, allow_blank=True, allow_null=True)
    tags = JSONAPIListField(child=NodeTagField(), required=False)
    node_is_public = ShowIfVersion(HideIfWithdrawal(ser.BooleanField(read_only=True, source='node__is_public')), min_version=2.0, max_version=2.7)
    preprint_doi_created = HideIfWithdrawal(VersionedDateTimeField(read_only=True))
    date_withdrawn = VersionedDateTimeField(read_only=True, allow_null=True)
    withdrawal_justification = HideIfNotWithdrawal(ser.CharField(required=False, read_only=True, allow_blank=True))
    current_user_permissions = ser.SerializerMethodField(help_text='List of strings representing the permissions '
                                                                   'for the current user on this preprint.')

    contributors = RelationshipField(
        related_view='preprints:preprint-contributors',
        related_view_kwargs={'preprint_id': '<_id>'},
    )
    reviews_state = HideIfWithdrawal(ser.CharField(source='machine_state', read_only=True, max_length=15))
    date_last_transitioned = HideIfWithdrawal(VersionedDateTimeField(read_only=True))

    citation = HideIfWithdrawal(RelationshipField(
        related_view='preprints:preprint-citation',
        related_view_kwargs={'preprint_id': '<_id>'}
    ))

    identifiers = HideIfWithdrawal(RelationshipField(
        related_view='preprints:identifier-list',
        related_view_kwargs={'preprint_id': '<_id>'}
    ))

    node = HideIfWithdrawal(NodeRelationshipField(
        related_view='nodes:node-detail',
        related_view_kwargs={'node_id': '<node._id>'},
        read_only=False
    ))

    license = PreprintLicenseRelationshipField(
        related_view='licenses:license-detail',
        related_view_kwargs={'license_id': '<license.node_license._id>'},
        read_only=False
    )

    provider = HideIfWithdrawal(PreprintProviderRelationshipField(
        related_view='providers:preprint-providers:preprint-provider-detail',
        related_view_kwargs={'provider_id': '<provider._id>'},
        read_only=False
    ))

    files = HideIfWithdrawal(RelationshipField(
        related_view='preprints:preprint-providers',
        related_view_kwargs={'preprint_id': '<_id>'}
    ))

    primary_file = HideIfWithdrawal(PrimaryFileRelationshipField(
        related_view='files:file-detail',
        related_view_kwargs={'file_id': '<primary_file._id>'},
        read_only=False
    ))

    review_actions = HideIfWithdrawal(RelationshipField(
        related_view='preprints:preprint-review-action-list',
        related_view_kwargs={'preprint_id': '<_id>'}
    ))

    links = LinksField(
        {
            'self': 'get_preprint_url',
            'html': 'get_absolute_html_url',
            'doi': 'get_article_doi_url',
            'preprint_doi': 'get_preprint_doi_url'
        }
    )

    class Meta:
        type_ = 'preprints'

    def get_preprint_url(self, obj):
        return absolute_reverse('preprints:preprint-detail', kwargs={'preprint_id': obj._id, 'version': self.context['request'].parser_context['kwargs']['version']})

    def get_absolute_url(self, obj):
        return self.get_preprint_url(obj)

    def get_article_doi_url(self, obj):
        return 'https://dx.doi.org/{}'.format(obj.article_doi) if obj.article_doi else None

    def get_current_user_permissions(self, obj):
        user = self.context['request'].user
        all_perms = ['read', 'write', 'admin']
        user_perms = []
        for p in all_perms:
            if obj.has_permission(user, p):
                user_perms.append(p)
        return user_perms

    def get_preprint_doi_url(self, obj):
        doi_identifier = obj.get_identifier('doi')
        if doi_identifier:
            return 'https://dx.doi.org/{}'.format(doi_identifier.value)
        else:
            built_identifier = settings.EZID_FORMAT.format(namespace=settings.DOI_NAMESPACE, guid=obj._id).replace('doi:', '').upper()
            return 'https://dx.doi.org/{}'.format(built_identifier) if built_identifier and obj.is_published else None

    def update(self, preprint, validated_data):
        assert isinstance(preprint, Preprint), 'You must specify a valid preprint to be updated'

        auth = get_user_auth(self.context['request'])
        if not preprint.has_permission(auth.user, osf_permissions.WRITE):
            raise exceptions.PermissionDenied(detail='User must have admin or write permissions to update a preprint.')

        published = validated_data.pop('is_published', None)
        if published and preprint.provider.is_reviewed:
            raise Conflict('{} uses a moderation workflow, so preprints must be submitted for review instead of published directly. Submit a preprint by creating a `submit` Action at {}'.format(
                preprint.provider.name,
                absolute_reverse('preprints:preprint-review-action-list', kwargs={
                    'version': self.context['request'].parser_context['kwargs']['version'],
                    'preprint_id': preprint._id
                })
            ))

        save_preprint = False
        recently_published = False

        primary_file = validated_data.pop('primary_file', None)
        if primary_file:
            self.set_field(preprint.set_primary_file, primary_file, auth)
            save_preprint = True

        old_tags = set(preprint.tags.values_list('name', flat=True))
        if validated_data.get('tags'):
            current_tags = set(validated_data.pop('tags', []))
        elif self.partial:
            current_tags = set(old_tags)
        else:
            current_tags = set()

        for new_tag in (current_tags - old_tags):
            preprint.add_tag(new_tag, auth=auth)
        for deleted_tag in (old_tags - current_tags):
            preprint.remove_tag(deleted_tag, auth=auth)

        if 'node' in validated_data:
            node = validated_data.pop('node', None)
            self.set_field(preprint.set_supplemental_node, node, auth)
            save_preprint = True

        if 'subjects' in validated_data:
            subjects = validated_data.pop('subjects', None)
            self.set_field(preprint.set_subjects, subjects, auth)
            save_preprint = True

        if 'title' in validated_data:
            title = validated_data['title']
            self.set_field(preprint.set_title, title, auth)
            save_preprint = True

        if 'description' in validated_data:
            description = validated_data['description']
            self.set_field(preprint.set_description, description, auth)
            save_preprint = True

        if 'article_doi' in validated_data:
            preprint.article_doi = validated_data['article_doi']
            save_preprint = True

        if 'license_type' in validated_data or 'license' in validated_data:
            license_details = get_license_details(preprint, validated_data)
            self.set_field(preprint.set_preprint_license, license_details, auth)
            save_preprint = True

        if 'original_publication_date' in validated_data:
            preprint.original_publication_date = validated_data['original_publication_date']
            save_preprint = True

        if published is not None:
            if not preprint.primary_file:
                raise exceptions.ValidationError(detail='A valid primary_file must be set before publishing a preprint.')
            self.set_field(preprint.set_published, published, auth)
            save_preprint = True
            recently_published = published
            preprint.set_privacy('public', log=False, save=True)

        if save_preprint:
            preprint.save()

        # Send preprint confirmation email signal to new authors on preprint! -- only when published
        # TODO: Some more thought might be required on this; preprints made from existing
        # nodes will send emails making it seem like a new node.
        if recently_published:
            for author in preprint.contributors:
                if author != auth.user:
                    project_signals.contributor_added.send(preprint, contributor=author, auth=auth, email_template='preprint')

        return preprint

    def set_field(self, func, val, auth, save=False):
        try:
            func(val, auth)
        except PermissionsError as e:
            raise exceptions.PermissionDenied(detail=e.message)
        except (ValueError, ValidationError, NodeStateError) as e:
            raise exceptions.ValidationError(detail=e.message)
        except PreprintProviderError as e:
            if 'Only one preprint per provider can be submitted for a node' in e.message:
                raise Conflict(e.message)


class PreprintCreateSerializer(PreprintSerializer):
    # Overrides PreprintSerializer to make id nullable, adds `create`
    id = IDField(source='_id', required=False, allow_null=True)

    def create(self, validated_data):
        creator = self.context['request'].user
        provider = validated_data.pop('provider', None)
        if not provider:
            raise exceptions.ValidationError(detail='You must specify a valid provider to create a preprint.')

        title = validated_data.pop('title')
        description = validated_data.pop('description', '')
        preprint = Preprint(provider=provider, title=title, creator=creator, description=description)
        preprint.save()

        return self.update(preprint, validated_data)


class PreprintCitationSerializer(NodeCitationSerializer):

    class Meta:
        type_ = 'preprint-citation'


class PreprintContributorsSerializer(NodeContributorsSerializer):
    """ Separate from UserSerializer due to necessity to override almost every field as read only
    """
    preprint = RelationshipField(
        related_view='preprints:preprint-detail',
        related_view_kwargs={'preprint_id': '<preprint._id>'}
    )

    node = HideIfPreprint(RelationshipField(
        related_view='nodes:node-detail',
        related_view_kwargs={'node_id': '<node._id>'}
    ))

    class Meta:
        type_ = 'contributors'

    def get_absolute_url(self, obj):
        return absolute_reverse(
            'preprints:preprint-contributor-detail',
            kwargs={
                'user_id': obj.user._id,
                'preprint_id': self.context['request'].parser_context['kwargs']['preprint_id'],
                'version': self.context['request'].parser_context['kwargs']['version']
            }
        )


class PreprintContributorsCreateSerializer(NodeContributorsCreateSerializer, PreprintContributorsSerializer):
    """
    Overrides PreprintContributorsSerializer to add email, full_name, send_email, and non-required index and users field.

    id and index redefined because of the two serializers we've inherited
    """
    id = IDField(source='_id', required=False, allow_null=True)
    index = ser.IntegerField(required=False, source='_order')

    email_preferences = ['preprint', 'false']

    def get_proposed_permissions(self, validated_data):
        return validated_data.get('permission') or osf_permissions.WRITE


class PreprintContributorDetailSerializer(NodeContributorDetailSerializer, PreprintContributorsSerializer):
    """
    Overrides NodeContributorDetailSerializer to set the preprint instead of the node

    id and index redefined because of the two serializers we've inherited
    """
    id = IDField(required=True, source='_id')
    index = ser.IntegerField(required=False, read_only=False, source='_order')


class PreprintProviderSerializer(NodeProviderSerializer):
    node = HideIfPreprint(ser.CharField(source='node_id', read_only=True))
    preprint = ser.CharField(source='node_id', read_only=True)

    files = NodeFileHyperLinkField(
        related_view='preprints:preprint-files',
        related_view_kwargs={'preprint_id': '<node._id>'},
        kind='folder',
        never_embed=True
    )

    links = LinksField({
        'upload': WaterbutlerLink(),
    })
