#!/usr/bin/env python
# -*- encoding: UTF-8 -*-
#  This file is part of Mylar.
#
#  Mylar is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mylar is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mylar.  If not, see <http://www.gnu.org/licenses/>.
#
# Form based authentication for CherryPy. Requires the
# Session tool to be loaded.
# from cherrypy/tools on gitHub

import logging
import time
from html import escape
from urllib.parse import quote

import cherrypy

import lazylibrarian
from lazylibrarian import database
from lazylibrarian.common import pwd_generator
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import md5_utf8

SESSION_KEY = '_cp_username'


def check_credentials(username, password):
    """Verifies credentials for username and password.
    Returns None on success or a string describing the error on failure"""
    # Adapt to your needs
    if not CONFIG['USER_ACCOUNTS']:
        forms_user = cherrypy.request.config['auth.forms_username']
        forms_pass = cherrypy.request.config['auth.forms_password']
        if username == forms_user and password == forms_pass:
            return None
        return "Incorrect username or password."
    db = database.DBConnection()
    res = db.match('SELECT Password from users where UserName=?', (username,))
    db.close()
    if res and res['Password'] == md5_utf8(password):
        return None
    return "Incorrect username or password."


# noinspection PyUnusedLocal
def check_auth(*args, **kwargs):
    """A tool that looks in config for 'auth.require'. If found, and it
    is not None, a login is required and the entry is evaluated as a list of
    conditions that the user must fulfill"""
    conditions = cherrypy.request.config.get('auth.require', None)
    get_params = quote(cherrypy.request.request_line.split()[1])
    if conditions is not None:
        # noinspection PyUnresolvedReferences
        username = cherrypy.session.get(SESSION_KEY)  # pylint: disable=no-member
        if username:
            cherrypy.request.login = username
            for condition in conditions:
                # A condition is just a callable that returns true or false
                if not condition():
                    raise cherrypy.HTTPRedirect(f"auth/login?from_page={get_params}")
        else:
            raise cherrypy.HTTPRedirect(f"auth/login?from_page={get_params}")


cherrypy.tools.auth = cherrypy.Tool('before_handler', check_auth)


def require_auth(*conditions):
    """A decorator that appends conditions to the auth.require config
    variable."""

    # noinspection PyProtectedMember
    def decorate(f):
        if not hasattr(f, '_cp_config'):
            f._cp_config = {}
        if 'auth.require' not in f._cp_config:
            f._cp_config['auth.require'] = []
        f._cp_config['auth.require'].extend(conditions)
        return f
    return decorate


# Conditions are callables that return True
# if the user fulfills the conditions they define, False otherwise
#
# They can access the current username as cherrypy.request.login
#
# Define those at will however suits the application.

def member_of(groupname):
    def check():
        # replace with actual check if <username> is in <groupname>
        return cherrypy.request.login == 'joe' and groupname == 'admin'
    return check


def name_is(reqd_username):
    return lambda: reqd_username == cherrypy.request.login

# These might be handy


def any_of(*conditions):
    """Returns True if any of the conditions match"""
    def check():
        return any(c() for c in conditions)
    return check


# By default, all conditions are required, but this might still be
# needed if you want to use it inside of an any_of(...) condition
def all_of(*conditions):
    """Returns True if all the conditions match"""
    def check():
        return all(c() for c in conditions)
    return check

# Controller to provide login and logout actions


class AuthController:
    @staticmethod
    def on_login(username, password):
        logger = logging.getLogger(__name__)
        """Called on successful login"""
        # create user cookie
        db = database.DBConnection()
        # if user accounts exist, or this user logged in before, find the user entry
        res = db.match('SELECT UserID,Prefs from users where UserName=?', (username,))
        if res:
            logger.debug(f"{username} is a registered user")
        elif not CONFIG['USER_ACCOUNTS']:  # and we haven't got a user entry for them...
            db.upsert('users', {'Last_Login': str(int(time.time())),
                                'Login_Count': 1,
                                'UserID': pwd_generator(),
                                'Name': username,
                                'Password': md5_utf8(password),
                                'Perms': lazylibrarian.perm_admin
                                }, {'UserName': username})
            logger.debug(f"{username} added as a new admin user")
            res = db.match('SELECT UserID,Prefs from users where UserName=?', (username,))
        logger.info(f'{username} successfully logged in.')
        # cherrypy.response.cookie['ll_uid'] = res['UserID']
        # cherrypy.response.cookie['ll_prefs'] = res['Prefs']
        lazylibrarian.LOGINUSER = f"!{res['UserID']}"
        db.close()

    @staticmethod
    def on_logout(username):
        """Called on logout"""
        lazylibrarian.webServe.clear_our_cookies()
        lazylibrarian.LOGINUSER = None

    # noinspection PyUnusedLocal
    @staticmethod
    def get_loginform(username, msg="Enter login information", from_page="/"):
        from lazylibrarian.webServe import serve_template
        img = 'images/ll.png'
        if CONFIG['HTTP_ROOT']:
            img = f"{CONFIG['HTTP_ROOT']}/{img}"
        return serve_template(templatename="formlogin.html", username=escape(username, True),
                              title='Login', img=img, from_page=from_page)

    # noinspection PyUnusedLocal
    @cherrypy.expose
    def login(self, current_username=None, current_password=None, remember_me='0', from_page="/", **kwargs):
        if current_username is None or current_password is None:
            return self.get_loginform("", from_page=from_page)
        error_msg = check_credentials(current_username, current_password)
        if error_msg:
            return self.get_loginform(current_username, error_msg, from_page)
        # noinspection PyUnresolvedReferences
        cherrypy.session.regenerate()  # pylint: disable=no-member
        # noinspection PyUnresolvedReferences
        cherrypy.session[SESSION_KEY] = cherrypy.request.login = current_username  # pylint: disable=no-member
        self.on_login(current_username, current_password)
        # Patched: from_page is built from check_auth()'s raw
        # cherrypy.request.request_line, which is the URI nginx forwarded
        # unmodified, already including HTTP_ROOT (nginx does not strip it
        # for this app, matching how sonarr/radarr's own UrlBase expects the
        # prefix to arrive intact). Unconditionally prepending HTTP_ROOT
        # here doubled it (e.g. /lazylibrarian//lazylibrarian/), 404ing the
        # very first post-login redirect every time, confirmed live. Only
        # prepend when it isn't already there.
        root = CONFIG['HTTP_ROOT'].rstrip('/')
        if root and not from_page.startswith(root):
            from_page = f"{root}/{from_page}"
        raise cherrypy.HTTPRedirect(from_page or CONFIG['HTTP_ROOT'])

    @cherrypy.expose
    def logout(self, from_page="/"):
        # noinspection PyUnresolvedReferences
        sess = cherrypy.session  # pylint: disable=no-member
        username = sess.get(SESSION_KEY, None)
        sess[SESSION_KEY] = None
        if username:
            cherrypy.request.login = None
            self.on_logout(username)
            # Patched: same double-prefix fix as login() above.
            root = CONFIG['HTTP_ROOT'].rstrip('/')
            if root and not from_page.startswith(root):
                from_page = f"{root}/{from_page}"
            raise cherrypy.HTTPRedirect(from_page or CONFIG['HTTP_ROOT'])
