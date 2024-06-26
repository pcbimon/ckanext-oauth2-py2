# -*- coding: utf-8 -*-

# Copyright (c) 2014 CoNWeT Lab., Universidad Politécnica de Madrid
# Copyright (c) 2018 Future Internet Consulting and Development Solutions S.L.

# This file is part of OAuth2 CKAN Extension.

# OAuth2 CKAN Extension is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# OAuth2 CKAN Extension is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with OAuth2 CKAN Extension.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals

import logging
import oauth2
import os

from functools import partial
from ckan import plugins
from ckan.common import g
from ckan.plugins import toolkit
from urlparse import urlparse
from flask import session,redirect
import re
from ckan.lib.navl.validators import ignore_missing, not_empty, empty
import ckan.lib.navl.dictization_functions as df
from ckan.common import _
from six import string_types
from ckan.model import (PACKAGE_NAME_MAX_LENGTH)
from ckan.logic.schema import default_user_schema
import ckan.lib.plugins as lib_plugins
Invalid = df.Invalid
Missing = df.Missing
missing = df.missing

# Allow alphanumeric characters, spaces, dashes, and dots
name_match = re.compile('[a-zA-Z0-9_\-\. ]+$')

log = logging.getLogger(__name__)


def _no_permissions(context, msg):
    user = context['user']
    return {'success': False, 'msg': msg.format(user=user)}


@toolkit.auth_sysadmins_check
def user_create(context, data_dict):
    log.debug('Checking if the user can be created')
    log.debug('User Request Is Admin? : %s' % (context['auth_user_obj'].sysadmin == True))
    try:
        if not context['auth_user_obj'].sysadmin:
            msg = toolkit._('Only system administrators can create users')
            return _no_permissions(context, msg)
        else:
            return {'success': True}
    except Exception as e:
        return _no_permissions(context, msg)


@toolkit.auth_sysadmins_check
def user_update(context, data_dict):
    log.debug('Checking if the user can be updated')
    log.debug('User Request Is Admin? : %s' % (context['auth_user_obj'].sysadmin == True))
    try:
        if not context['auth_user_obj'].sysadmin:
            msg = toolkit._('Only system administrators can update users')
            return _no_permissions(context, msg)
        else:
            return {'success': True}
    except Exception as e:
        return _no_permissions(context, msg)
        


@toolkit.auth_sysadmins_check
def user_reset(context, data_dict):
    msg = toolkit._('Users cannot reset passwords.')
    return _no_permissions(context, msg)


@toolkit.auth_sysadmins_check
def request_reset(context, data_dict):
    msg = toolkit._('Users cannot reset passwords.')
    return _no_permissions(context, msg)


def _get_previous_page(default_page):
    if 'came_from' not in toolkit.request.params:
        came_from_url = toolkit.request.headers.get('Referer', default_page)
    else:
        came_from_url = toolkit.request.params.get('came_from', default_page)

    came_from_url_parsed = urlparse(came_from_url)

    # Avoid redirecting users to external hosts
    if came_from_url_parsed.netloc != '' and came_from_url_parsed.netloc != toolkit.request.host:
        came_from_url = default_page

    # When a user is being logged and REFERER == HOME or LOGOUT_PAGE
    # he/she must be redirected to the dashboard
    pages = ['/', '/user/logged_out_redirect']
    if came_from_url_parsed.path in pages:
        came_from_url = default_page

    return came_from_url
name_match = re.compile('[a-zA-Z0-9_\-\.]+$')

def name_validator(value, context):
    if not isinstance(value, string_types):
        raise Invalid(_('Names must be strings'))

    # check basic textual rules
    if value in ['new', 'edit', 'search']:
        raise Invalid(_('That name cannot be used'))
    if len(value) < 2:
        raise Invalid(_('Must be at least %s characters long') % 2)
    if len(value) > PACKAGE_NAME_MAX_LENGTH:
        raise Invalid(_('Name must be a maximum of %i characters long') % \
                      PACKAGE_NAME_MAX_LENGTH)
    if not name_match.match(value):
        raise Invalid(_('Name must be alphanumeric characters, dashes, or dots only'))
    return value


class OAuth2Plugin(plugins.SingletonPlugin):

    plugins.implements(plugins.IAuthenticator, inherit=True)
    plugins.implements(plugins.IAuthFunctions, inherit=True)
    plugins.implements(plugins.IRoutes, inherit=True)
    plugins.implements(plugins.IValidators)
    plugins.implements(plugins.IConfigurer)

    def __init__(self, name=None):
        '''Store the OAuth 2 client configuration'''
        log.debug('Init OAuth2 extension')

        self.oauth2helper = oauth2.OAuth2Helper()

    def before_map(self, m):
        log.debug('Setting up the redirections to the OAuth2 service')

        m.connect('/user/login',
                  controller='ckanext.oauth2.controller:OAuth2Controller',
                  action='login')

        # We need to handle petitions received to the Callback URL
        # since some error can arise and we need to process them
        m.connect('/authen-service/OAuthCallback',
                  controller='ckanext.oauth2.controller:OAuth2Controller',
                  action='callback')
        m.connect('/user/_logout',
                  controller='ckanext.oauth2.controller:OAuth2Controller',
                  action='logout')
        m.connect('/user/not_authorized',
                  controller='ckanext.oauth2.controller:OAuth2Controller',
                  action='not_authorized')
        # Redirect the user to the OAuth service register page
        if self.register_url:
            m.redirect('/user/register', self.register_url)

        # Redirect the user to the OAuth service reset page
        if self.reset_url:
            m.redirect('/user/reset', self.reset_url)

        # Redirect the user to the OAuth service reset page
        if self.edit_url:
            m.redirect('/user/edit/{user}', self.edit_url)
        return m
    def identify(self):
        log.debug('identify')

        def _refresh_and_save_token(user_name):
            new_token = self.oauth2helper.refresh_token(user_name)
            if new_token:
                toolkit.c.usertoken = new_token

        environ = toolkit.request.environ
        apikey = toolkit.request.headers.get(self.authorization_header, '')
        user_name = None

        if self.authorization_header == "authorization":
            if apikey.startswith('Bearer '):
                apikey = apikey[7:].strip()
            else:
                apikey = ''

        # This API Key is not the one of CKAN, it's the one provided by the OAuth2 Service
        if apikey:
            try:
                token = {'access_token': apikey}
                user_name = self.oauth2helper.identify(token)
            except Exception:
                pass

        # If the authentication via API fails, we can still log in the user using session.
        if user_name is None and 'repoze.who.identity' in environ:
            user_name = environ['repoze.who.identity']['repoze.who.userid']
            log.info('User %s logged using session' % user_name)

        # If we have been able to log in the user (via API or Session)
        if user_name:
            g.user = user_name
            toolkit.c.user = user_name
            toolkit.c.usertoken = self.oauth2helper.get_stored_token(user_name)
            toolkit.c.usertoken_refresh = partial(_refresh_and_save_token, user_name)
        else:
            g.user = None
            log.warn('The user is not currently logged...')

    def get_auth_functions(self):
        # we need to prevent some actions being authorized.
        return {
            'user_create': user_create,
            'user_update': user_update,
            'user_reset': user_reset,
            'request_reset': request_reset
        }

    def update_config(self, config):
        # Update our configuration
        self.register_url = os.environ.get("CKAN_OAUTH2_REGISTER_URL", config.get('ckan.oauth2.register_url', None))
        self.reset_url = os.environ.get("CKAN_OAUTH2_RESET_URL", config.get('ckan.oauth2.reset_url', None))
        self.edit_url = os.environ.get("CKAN_OAUTH2_EDIT_URL", config.get('ckan.oauth2.edit_url', None))
        self.authorization_header = os.environ.get("CKAN_OAUTH2_AUTHORIZATION_HEADER", config.get('ckan.oauth2.authorization_header', 'Authorization')).lower()
        config['ckan.auth.public_user_details'] = False
        config['ckan.auth.create_user_via_web'] = False
        config['ckan.auth.create_user_via_api']= False

        # Add this plugin's templates dir to CKAN's extra_template_paths, so
        # that CKAN will use this plugin's custom templates.
        plugins.toolkit.add_template_directory(config, 'templates')
        plugins.toolkit.add_public_directory(config, 'public')
    def get_validators(self):
        return {'name_validator': name_validator}
