#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software, you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.


import base64
import contextlib
import datetime
import hashlib
import json
import logging
import os
import random
import re
import subprocess
import threading
import time
import traceback
import uuid
from shutil import copyfile, rmtree
from urllib.parse import quote, unquote, unquote_plus, urlsplit, urlunsplit

import cherrypy
from cherrypy.lib.static import serve_file
from deluge_client import DelugeRPCClient
from mako import exceptions
from mako.lookup import TemplateLookup
from rapidfuzz import fuzz

import lazylibrarian
from lazylibrarian import (
    ROLE,
    comicscan,
    database,
    deluge,
    grsync,
    hc,
    magazinescan,
    notifiers,
    nzbget,
    qbittorrent,
    rtorrent,
    sabnzbd,
    synology,
    transmission,
    utorrent,
    versioncheck,
)
from lazylibrarian.auth import AuthController, require_auth
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.bookrename import name_vars
from lazylibrarian.bookwork import add_series_members, delete_empty_series, set_series
from lazylibrarian.cache import ImageType, cache_img
from lazylibrarian.calibre import calibre_test, calibredb, get_calibre_id, sync_calibre_list
from lazylibrarian.calibre_integration import send_mag_issue_to_calibre
from lazylibrarian.comicid import cv_identify, cx_identify, name_words, title_words
from lazylibrarian.comicsearch import search_comics
from lazylibrarian.common import (
    create_support_zip,
    delete_empty_folders,
    get_readinglist,
    is_valid_email,
    log_header,
    mime_type,
    pwd_check,
    pwd_generator,
    run_script,
    set_readinglist,
    zip_audio,
)
from lazylibrarian.config2 import CONFIG, wishlist_type
from lazylibrarian.configtypes import ConfigBool
from lazylibrarian.csvfile import dump_table, export_csv, import_csv, restore_table
from lazylibrarian.dbupgrade import check_db
from lazylibrarian.download_client import delete_task, get_download_progress
from lazylibrarian.downloadmethods import (
    direct_dl_method,
    irc_dl_method,
    nzb_dl_method,
    tor_dl_method,
)
from lazylibrarian.filesystem import (
    DIRS,
    book_file,
    csv_file,
    get_directory,
    listdir,
    opf_file,
    path_exists,
    path_isdir,
    path_isfile,
    remove_file,
    safe_copy,
    safe_move,
    setperm,
    splitext,
    syspath,
)
from lazylibrarian.formatter import (
    check_float,
    check_int,
    check_year,
    clean_name,
    date_format,
    format_author_name,
    get_list,
    make_unicode,
    md5_utf8,
    now,
    plural,
    replace_all,
    safe_unicode,
    sort_definite,
    strip_quotes,
    surname_first,
    thread_name,
    today,
    unaccented,
)
from lazylibrarian.images import (
    coverswap,
    create_mag_cover,
    createthumb,
    get_author_image,
    get_book_cover,
    img_id,
    read_pdf_tags,
    write_pdf_tags,
)
from lazylibrarian.importer import (
    add_author_name_to_db,
    add_author_to_db,
    get_preferred_author,
    search_for,
    update_totals,
)
from lazylibrarian.librarysync import library_scan
from lazylibrarian.logconfig import LOGCONFIG
from lazylibrarian.magazinescan import (
    get_dateparts,
    magazine_scan,
    remove_if_empty,
    rename_issue,
)
from lazylibrarian.manual_import import (
    process_alternate,
    process_book_from_dir,
    process_issues,
)
from lazylibrarian.manualbook import search_item
from lazylibrarian.metadata_opf import create_opf
from lazylibrarian.notifiers import custom_notify_snatch, notify_snatch
from lazylibrarian.opds import OPDS
from lazylibrarian.opfedit import opf_read, opf_write
from lazylibrarian.postprocess import process_dir
from lazylibrarian.processcontrol import get_info_on_caller
from lazylibrarian.providers import test_provider
from lazylibrarian.rssfeed import gen_feed
from lazylibrarian.scheduling import (
    SchedulerCommand,
    all_author_update,
    check_running_jobs,
    ensure_running,
    restart_jobs,
    schedule_job,
    show_jobs,
    show_stats,
)
from lazylibrarian.searchbook import search_book
from lazylibrarian.searchmag import download_maglist, search_magazines
from lazylibrarian.searchrss import search_wishlist
from lazylibrarian.telemetry import TELEMETRY

lastauthor = ''
lastmagazine = ''
lastcomic = ''

api_sources = []
for item in lazylibrarian.INFOSOURCES.keys():
    # source, authorid, bookid
    info_source = lazylibrarian.INFOSOURCES[item]
    api_sources.append([info_source, info_source['author_key'], info_source['book_key']])


def clear_mako_cache(userid=0):
    logger = logging.getLogger(__name__)
    if userid:
        logger.warning(f"Clearing mako cache {userid}")
        makocache = os.path.join(DIRS.CACHEDIR, 'mako', str(userid))
    else:
        logger.warning("Clearing mako cache")
        makocache = os.path.join(DIRS.CACHEDIR, 'mako')
    try:
        rmtree(makocache, ignore_errors=True)
        # noinspection PyArgumentList
        os.makedirs(makocache, exist_ok=True)
    except Exception as e:
        logger.error(f"Error clearing mako cache: {str(e)}")


def clear_our_cookies():
    cherrypy.response.cookie['ll_uid'] = ''
    cherrypy.response.cookie['ll_uid']['expires'] = 0
    cherrypy.response.cookie['ll_prefs'] = '0'
    cherrypy.response.cookie['ll_prefs']['expires'] = 0


def serve_template(templatename, **kwargs):
    thread_name("WEBSERVER")
    logger = logging.getLogger(__name__)
    adminlogger = logging.getLogger('special.admin')
    interface_dir = os.path.join(str(DIRS.PROG_DIR), 'data', 'interfaces')
    template_dir = os.path.join(str(interface_dir), CONFIG['HTTP_LOOK'])
    if not path_isdir(template_dir):
        logger.error(f"Unable to locate template [{template_dir}], reverting to bookstrap")
        CONFIG.set_str('HTTP_LOOK', 'bookstrap')
        template_dir = os.path.join(str(interface_dir), CONFIG['HTTP_LOOK'])

    if templatename in ['logs.html', 'history.html']:
        # don't cache these so we can change refresh rate
        module_directory = None
    else:
        module_directory = os.path.join(DIRS.CACHEDIR, 'mako')
    _hplookup = TemplateLookup(directories=[template_dir], input_encoding='utf-8',
                               module_directory=module_directory)
    # noinspection PyBroadException
    try:
        style = CONFIG['BOOKSTRAP_THEME']
        userprefs = 0
        usertheme = ''
        if lazylibrarian.UPDATE_MSG:
            template = _hplookup.get_template("dbupdate.html")
            return template.render(perm=0, message="Database upgrade in progress, please wait...",
                                   title="Database Upgrade", timer=5, style=style)

        adminlogger.debug(str(cherrypy.request.headers))
        if not CONFIG.get_bool('USER_ACCOUNTS'):
            perm = lazylibrarian.perm_admin
            try:
                template = _hplookup.get_template(templatename)
            except (AttributeError, KeyError):
                clear_mako_cache()
                template = _hplookup.get_template(templatename)
        else:
            username = ''  # anyone logged in yet?
            userid = 0
            perm = 0
            res = {}
            cookie = None
            db = database.DBConnection()

            if lazylibrarian.LOGINUSER:
                formauth = lazylibrarian.LOGINUSER.startswith('!')
                lazylibrarian.LOGINUSER = lazylibrarian.LOGINUSER.strip('!')
                res = db.match('SELECT * from users where UserID=?', (lazylibrarian.LOGINUSER,))
                if res:
                    cherrypy.response.cookie['ll_uid'] = lazylibrarian.LOGINUSER
                    userid = lazylibrarian.LOGINUSER
                    if formauth:
                        logger.debug(f"Auth-login for {res['UserName']}")
                    else:
                        logger.debug(f"Auto-login for {res['UserName']}")
                        # lazylibrarian.SHOWLOGOUT = 0
                    db.action("UPDATE users SET Last_Login=?,Login_Count=? WHERE UserID=?",
                              (str(int(time.time())), int(res['Login_Count']) + 1, res['UserID']))
                else:
                    logger.debug(f"Login failed for userid {lazylibrarian.LOGINUSER}")
                    clear_our_cookies()
                lazylibrarian.LOGINUSER = None

            else:
                cookie = cherrypy.request.cookie
                authorization = cherrypy.request.headers.get('Authorization')
                if cookie and 'll_uid' in list(cookie.keys()):
                    res = db.match('SELECT * from users where UserID=?', (cookie['ll_uid'].value,))
                    if not res:
                        clear_our_cookies()
                elif authorization and authorization.startswith('Basic '):
                    auth_bytes = authorization.split('Basic ')[1].encode('ascii')
                    value_bytes = base64.b64decode(auth_bytes)
                    values = value_bytes.decode('ascii')
                    res = {}
                    if ':' in values:
                        user, pwd = values.split(':', 1)
                        res = db.match('SELECT * from users where UserName=? and Password=?', (user, md5_utf8(pwd)))
                if not res and CONFIG.get_bool('PROXY_AUTH'):
                    logger.debug('Proxy Auth enabled')
                    user = cherrypy.request.headers.get(CONFIG.get_str('PROXY_AUTH_USER'))
                    if user:
                        logger.debug(f"{CONFIG.get_str('PROXY_AUTH_USER')}: {user}")
                        res = db.match('SELECT * from users where UserName=?', (user,))
                        if res:
                            logger.debug(f"{user} is a registered user")
                            cherrypy.response.cookie['ll_uid'] = res['UserID']
                            cherrypy.response.cookie['ll_prefs'] = res['Prefs']
                            db.action("UPDATE users SET Last_Login=?,Login_Count=? WHERE UserID=?",
                                      (str(int(time.time())), int(res['Login_Count']) + 1, res['UserID']))
                        if not res and CONFIG.get_bool('PROXY_REGISTER'):
                            logger.debug(f"User {user} not registered, trying to add...")
                            fullname = cherrypy.request.headers.get(CONFIG.get_str('PROXY_AUTH_NAME'))
                            logger.debug(f"{CONFIG.get_str('PROXY_AUTH_NAME')}: {fullname}")
                            email = cherrypy.request.headers.get(CONFIG.get_str('PROXY_AUTH_EMAIL'))
                            logger.debug(f"{CONFIG.get_str('PROXY_AUTH_NAME')}: {email}")
                            if fullname and email:
                                new_pwd = pwd_generator()
                                msg = lazylibrarian.NEWUSER_MSG.replace('{username}', user).replace(
                                    '{password}', new_pwd).replace('{permission}', 'Friend')

                                result = notifiers.email_notifier.notify_message('LazyLibrarian New Account',
                                                                                 msg, email)
                                if result:
                                    cmd = ('INSERT into users (UserID, UserName, Name, Password, Email, '
                                           'SendTo, Perms) VALUES (?, ?, ?, ?, ?, ?, ?)')
                                    db.action(cmd, (pwd_generator(), user, fullname, md5_utf8(new_pwd),
                                                    email, '', lazylibrarian.perm_friend))
                                    msg = f"New user added from proxy auth: {user}: Friend"
                                    msg += f"<br>Email sent to {email}"
                                    cnt = db.match("select count(*) as counter from users")
                                    if cnt['counter'] > 1:
                                        lazylibrarian.SHOWLOGOUT = 1
                                    res = db.match('SELECT * from users where UserName=?', (user,))
                                    cherrypy.response.cookie['ll_uid'] = res['UserID']
                                    cherrypy.response.cookie['ll_prefs'] = res['Prefs']
                                    db.action("UPDATE users SET Last_Login=?,Login_Count=? WHERE UserID=?",
                                              (str(int(time.time())), int(res['Login_Count']) + 1, res['UserID']))
                                else:
                                    msg = "New user NOT added"
                                    msg += f"<br>Failed to send email to {email}"
                                logger.debug(msg)

                if not res:
                    columns = db.select('PRAGMA table_info(users)')
                    if not columns:  # no such table
                        cnt = 0
                    else:
                        cnt = db.match("select count(*) as counter from users")
                    if cnt and cnt['counter'] == 1 and CONFIG.get_bool('SINGLE_USER') and \
                            templatename not in ["register.html", "response.html", "opds.html"]:
                        res = db.match('SELECT * from users')
                        cherrypy.response.cookie['ll_uid'] = res['UserID']
                        cherrypy.response.cookie['ll_prefs'] = res['Prefs']
                        logger.debug(f"Auto-login for {res['UserName']}")
                        db.action("UPDATE users SET Last_Login=?,Login_Count=? WHERE UserID=?",
                                  (str(int(time.time())), int(res['Login_Count']) + 1, res['UserID']))
                        lazylibrarian.SHOWLOGOUT = 0
                    else:
                        lazylibrarian.SHOWLOGOUT = 1

                if not res:
                    remote_ip = cherrypy.request.headers.get('X-Forwarded-For')  # apache2
                    if not remote_ip:
                        remote_ip = cherrypy.request.headers.get('X-Host')  # lighthttpd
                    if not remote_ip:
                        remote_ip = cherrypy.request.headers.get('Remote-Addr')
                    if not remote_ip:
                        remote_ip = cherrypy.request.remote.ip
                    whitelist = get_list(CONFIG.get_csv('WHITELIST'))
                    to_whitelist = False
                    if remote_ip in whitelist:
                        # exact match
                        to_whitelist = True
                    for white in whitelist:
                        # allow ranges in the format 192.168.1.1/24
                        white_parts = white.split('.')
                        if (len(white_parts) == 4 and white_parts[3] == '1/24' and
                                remote_ip.startswith('.'.join(white_parts[:3]))):
                            to_whitelist = True
                            break
                    if to_whitelist:
                        columns = db.select('PRAGMA table_info(users)')
                        if not columns:  # no such table
                            cnt = 0
                        else:
                            cnt = db.match('SELECT count(*) as counter from users where Perms=65535')
                        if cnt and templatename not in ["register.html", "response.html", "opds.html"]:
                            res = db.match('SELECT * from users where Perms=65535')
                            cherrypy.response.cookie['ll_uid'] = res['UserID']
                            cherrypy.response.cookie['ll_prefs'] = res['Prefs']
                            logger.debug(f"Auto-login for {res['UserName']} at {remote_ip}")
                            db.action("UPDATE users SET Last_Login=?,Login_Count=? WHERE UserID=?",
                                      (str(int(time.time())), int(res['Login_Count']) + 1, res['UserID']))
                            lazylibrarian.SHOWLOGOUT = 0
                        else:
                            lazylibrarian.SHOWLOGOUT = 1
            if res:
                perm = check_int(res['Perms'], 0)
                username = res['UserName']
                userid = res['UserID']
                try:
                    res2 = db.match('SELECT Theme from users where UserID=?', (userid,))
                    if res2:
                        usertheme = res2['Theme']
                        if not usertheme:
                            usertheme = ''
                except Exception as e:
                    logger.debug(f"Unable to get user theme for {userid}: {str(e)}")
            db.close()
            if cookie and 'll_prefs' in list(cookie.keys()):
                userprefs = check_int(cookie['ll_prefs'].value, 0)

            if perm == 0 and templatename not in ["register.html", "response.html", "opds.html"]:
                if CONFIG.get_str('auth_type') == 'FORM' and not CONFIG.get_bool('USER_ACCOUNTS'):
                    templatename = "formlogin.html"
                else:
                    templatename = "login.html"
            elif (templatename == 'config.html' and not perm & lazylibrarian.perm_config) or \
                    (templatename == 'logs.html' and not perm & lazylibrarian.perm_logs) or \
                    (templatename == 'history.html' and not perm & lazylibrarian.perm_history) or \
                    (templatename == 'managebooks.html' and not perm & lazylibrarian.perm_managebooks) or \
                    (templatename == 'books.html' and not perm & lazylibrarian.perm_ebook) or \
                    (templatename == 'author.html' and not perm & lazylibrarian.perm_ebook
                     and not perm & lazylibrarian.perm_audio) or \
                    (templatename in ['magazines.html', 'issues.html', 'manageissues.html']
                     and not perm & lazylibrarian.perm_magazines) or \
                    (templatename in ['comics.html', 'comicissues.html', 'comicresults.html']
                     and not perm & lazylibrarian.perm_comics) or \
                    (templatename == 'audio.html' and not perm & lazylibrarian.perm_audio) or \
                    (templatename == 'choosetype.html' and not perm & lazylibrarian.perm_download) or \
                    (templatename in ['series.html', 'members.html'] and not perm & lazylibrarian.perm_series) or \
                    (templatename in ['editauthor.html', 'editbook.html', 'editissue.html'] and not
                        perm & lazylibrarian.perm_edit) or \
                    (templatename in ['manualsearch.html', 'searchresults.html']
                     and not perm & lazylibrarian.perm_search):
                logger.warning(f'User {username} attempted to access {templatename}')
                if not CONFIG.get_bool('USER_ACCOUNTS') and CONFIG.get_str('auth_type') == 'FORM':
                    templatename = "formlogin.html"
                else:
                    templatename = "login.html"

            adminlogger.debug(f"User {username}: {perm} {userprefs} {usertheme} {templatename}")

            theme = usertheme.split('_', 1)[0]
            if theme and theme != CONFIG['HTTP_LOOK']:
                template_dir = os.path.join(str(interface_dir), theme)
                if not path_isdir(template_dir):
                    logger.error(f"Unable to locate template [{template_dir}], reverting to bookstrap")
                    CONFIG.set_str('HTTP_LOOK', 'bookstrap')
                    template_dir = os.path.join(str(interface_dir), CONFIG['HTTP_LOOK'])

                module_directory = os.path.join(DIRS.CACHEDIR, 'mako', str(userid))
                _hplookup = TemplateLookup(directories=[template_dir], input_encoding='utf-8',
                                           module_directory=module_directory)
            try:
                template = _hplookup.get_template(templatename)
            except (AttributeError, KeyError):
                clear_mako_cache(userid)
                template = _hplookup.get_template(templatename)

        theme = usertheme.split('_', 1)
        if len(theme) > 1:
            style = theme[1]

        if templatename in ["login.html", "formlogin.html"]:
            cherrypy.response.cookie['ll_template'] = ''
            img = 'images/ll.png'
            if CONFIG['HTTP_ROOT']:
                img = f'{CONFIG["HTTP_ROOT"]}/{img}'
            if templatename == "login.html":
                return template.render(perm=0, title="Redirected", img=img, style=style)
            return template.render(perm=0, title='Login', img=img, from_page='/home')

        # keep template name for help context
        cherrypy.response.cookie['ll_template'] = templatename
        return template.render(perm=perm, pref=userprefs, style=style, **kwargs)

    except Exception:
        return exceptions.html_error_template().render()


# noinspection PyProtectedMember,PyGlobalUndefined,PyGlobalUndefined
class WebInterface:

    auth = AuthController()
    issues_data = ''

    @staticmethod
    def validate_param(keyword, value, tokens, errorpage):
        if not value:
            return True
        unquoted = unquote_plus(value)
        for token in tokens:
            if token in unquoted:
                logger = logging.getLogger(__name__)
                msg = f"Invalid {keyword}: contains {token}"
                logger.warning(msg)
                if errorpage:
                    raise cherrypy.HTTPError({errorpage}, msg)
                return False
        return True

    @staticmethod
    def check_permitted(required_perm):
        adminlogger = logging.getLogger('special.admin')
        userid = ''
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            cookie_userid = cookie['ll_uid'].value
            perm = 0
            db = database.DBConnection()
            res = db.match('SELECT * from users where UserID=?', (cookie_userid,))
            if res:
                perm = check_int(res['Perms'], 0)
                userid = res['UserID']
            else:
                adminlogger.debug(f"No match for userid [{cookie_userid}]")
                clear_our_cookies()
            db.close()
        else:
            perm = lazylibrarian.perm_admin

        if perm & required_perm:
            return

        _, method, _ = get_info_on_caller(depth=1)
        TELEMETRY.record_usage_data()
        logger = logging.getLogger(__name__)
        msg = f"Unauthorised attempt to access {method}"
        if userid:
            logger.warning(f'{msg} by user {userid}')
            db = database.DBConnection()
            cmd = 'INSERT into unauthorised (AccessTime, UserID, Attempt) VALUES (?, ?, ?)'
            db.action(cmd, (now(), userid, method))
        else:
            logger.warning(f'{msg}')

        raise cherrypy.HTTPError(403, msg)

    @cherrypy.expose
    @require_auth()
    def index(self):
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    @require_auth()
    def authors(self):
        title = 'Authors'
        if lazylibrarian.IGNORED_AUTHORS:
            if CONFIG.get_bool('IGNORE_PAUSED'):
                title = 'Inactive Authors'
            else:
                title = 'Ignored Authors'
        return serve_template(templatename="index.html", title=title, redirect=title.lower())

    @cherrypy.expose
    @require_auth()
    def home(self):
        logger = logging.getLogger(__name__)
        home = CONFIG.get_str('HOMEPAGE')
        logger.debug(f"Homepage [{home}]")
        if home == 'eBooks':
            raise cherrypy.HTTPRedirect("books")
        if home == 'Series':
            raise cherrypy.HTTPRedirect("series")
        if home == 'AudioBooks':
            raise cherrypy.HTTPRedirect("audio")
        if home == 'Magazines':
            raise cherrypy.HTTPRedirect("magazines")
        if home == 'Comics':
            raise cherrypy.HTTPRedirect("comics")
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def profile(self):
        title = 'User Profile'
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            db = database.DBConnection()
            try:
                user = db.match('SELECT UserName,UserID,Name,Email,SendTo,BookType,Theme,hc_id,hc_token '
                                'from users where UserID=?', (cookie['ll_uid'].value,))
                if user:
                    subs = db.select('SELECT Type,WantID from subscribers WHERE UserID=?', (cookie['ll_uid'].value,))
                    subscriptions = ''
                    for itm in subs:
                        if subscriptions:
                            subscriptions += '\n'
                        item_name = ''
                        if itm['Type'] == 'author':
                            res = db.match('SELECT AuthorName from authors WHERE authorid=?', (itm['WantID'],))
                            if res:
                                item_name = f"({res['AuthorName']})"
                        elif itm['Type'] == 'series':
                            res = db.match('SELECT SeriesName from series WHERE seriesid=?', (itm['WantID'],))
                            if res:
                                item_name = f"({res['SeriesName']})"
                        elif itm['Type'] == 'comic':
                            try:
                                comicid, issueid = itm['WantID'].split('_')
                            except ValueError:
                                comicid = ''
                            if comicid:
                                res = db.match('SELECT Title from comics WHERE comicid=?', (comicid,))
                                if res:
                                    item_name = f"({res['Title']})"
                        subscriptions += f'{itm["Type"]} {itm["WantID"]} {item_name}'
                    user = dict(user)
                    if not user['Theme']:
                        user['Theme'] = ''
                    themelist = ['Default']
                    for itm in lazylibrarian.BOOKSTRAP_THEMELIST:
                        themelist.append('bookstrap_' + itm)
                    return serve_template(templatename="profile.html", title=title, user=user, subs=subscriptions,
                                          typelist=get_list(CONFIG['EBOOK_TYPE']), themelist=themelist)
            finally:
                db.close()
        return serve_template(templatename="index.html", title='Authors', redirect='authors')

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_index(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        serversidelogger.debug(f"Start {iDisplayStart} Length {iDisplayLength} Col {iSortCol_0} "
                               f"Dir {sSortDir_0} Search [{sSearch}]")
        rows = []
        filtered = []
        rowlist = []
        userid = None
        userprefs = 0
        mydict = {}
        db = database.DBConnection()
        # noinspection PyBroadException
        try:
            if CONFIG.get_bool('USER_ACCOUNTS'):
                cookie = cherrypy.request.cookie
                if cookie and 'll_prefs' in list(cookie.keys()):
                    userprefs = check_int(cookie['ll_prefs'].value, 0)
                if cookie and 'll_uid' in list(cookie.keys()):
                    userid = cookie['ll_uid'].value
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            cmd = ("SELECT AuthorImg,AuthorName,LastBook,LastDate,Status,AuthorLink,LastLink,HaveBooks,"
                   "UnignoredBooks,AuthorID,LastBookID,DateAdded,Reason from authors ")
            if lazylibrarian.IGNORED_AUTHORS:
                cmd += "where Status == 'Ignored' "
                if CONFIG.get_bool('IGNORE_PAUSED'):
                    cmd += "or Status == 'Paused' "
            else:
                cmd += "where Status != 'Ignored' "
                if CONFIG.get_bool('IGNORE_PAUSED'):
                    cmd += "and  Status != 'Paused' "
            cmd += "and AuthorName is not null "

            if lazylibrarian.PRIMARY_AUTHORS:
                # is the author a primary author for any book...
                bookauthors = []
                res = db.select(f"SELECT AuthorID from bookauthors WHERE role={ROLE['PRIMARY']}")
                for author in res:
                    bookauthors.append(author['AuthorID'])
                cmd += " and AuthorID in (" + ", ".join(f"'{w}'" for w in bookauthors) + ")"
            myauthors = []
            if userid and userprefs & lazylibrarian.pref_myauthors:
                res = db.select("SELECT WantID from subscribers WHERE Type='author' and UserID=?", (userid,))
                serversidelogger.debug(f"User subscribes to {len(res)} authors")
                for author in res:
                    myauthors.append(author['WantID'])
                cmd += " and AuthorID in (" + ", ".join(f"'{w}'" for w in myauthors) + ")"

            cmd += " order by AuthorName COLLATE NOCASE"
            serversidelogger.debug(f"get_index {cmd}")

            rowlist = db.select(cmd)
            # At his point we want to sort and filter _before_ adding the html as it's much quicker
            # turn the sqlite rowlist into a list of lists
            if len(rowlist):
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    arow = list(row)
                    reasonlist = arow[12]
                    if not reasonlist:
                        reasonlist = "Unknown"
                    reasonlist = reasonlist.split()
                    reasonstring = ''
                    match reasonlist[0].lower().strip(":"):
                        case 'webserver':  # manual search and add of author
                            reasonstring = "Manual search"
                        case 'wishlist':  # added via wishlist rss search
                            reasonstring = "Wishlist search " + ' '.join(reasonlist[1:])
                        case 'process_alternate':  # added via import of alt folder
                            reasonstring = f"Import {' '.join(reasonlist[1:])} from alternate folder"
                        case 'ol.find_book':
                            reasonstring = "OpenLibrary search"
                        case 'ol_get_author_books':
                            reasonstring = "OpenLibrary search"
                        case 'gr.find_book':
                            reasonstring = "GoodReads search"
                        case 'gr_get_author_books':
                            reasonstring = "GoodReads search"
                        case 'hc.find_book':
                            reasonstring = "HardCover search"
                        case 'hc_get_author_books':
                            reasonstring = "HardCover search"
                        case 'gb.find_book':
                            reasonstring = "GoogleBooks search"
                        case 'gb_get_author_books':
                            reasonstring = "GoogleBooks search"
                        case 'import_csv':
                            reasonstring = "CSV import"
                        case 'sync_calibre_list':
                            reasonstring = "Calibre Sync"
                        case 'api':  # by name, id, and refresh
                            reasonstring = "API"
                        case 'add':
                            reasonstring = f"Import author of {' '.join(reasonlist[3:])}"
                        case 'contributor':
                            reasonstring = ' '.join(reasonlist)
                        case 'series':
                            reasonstring = "Search for series " + ' '.join(reasonlist[1:])
                        case _:
                            reasonstring = ''

                    if CONFIG.get_bool('SORT_SURNAME'):
                        arow[1] = surname_first(arow[1], postfixes=get_list(CONFIG.get_csv('NAME_POSTFIX')))
                    if CONFIG.get_bool('SORT_DEFINITE'):
                        arow[2] = sort_definite(arow[2], articles=get_list(CONFIG.get_csv('NAME_DEFINITE')))
                    arow[3] = date_format(arow[3], '', f'{arow[1]}/{arow[2]}', datelang=CONFIG['DATE_LANG'])
                    nrow = arow[:4]
                    havebooks = check_int(arow[7], 0)
                    totalbooks = check_int(arow[8], 0)
                    if totalbooks:
                        percent = int((havebooks * 100.0) / totalbooks)
                    else:
                        percent = 0
                    if percent > 100:
                        percent = 100

                    # if percent <= 25:
                    #     css = 'danger'
                    # elif percent <= 50:
                    #     css = 'warning'
                    # elif percent <= 75:
                    #     css = 'info'
                    # else:
                    #     css = 'success'

                    arow[12] = strip_quotes(reasonstring)
                    nrow.append(percent)
                    nrow.extend(arow[4:-2])
                    bar = ''
                    nrow.append(bar)
                    nrow.extend(arow[11:])
                    rows.append(nrow)  # add each rowlist to the masterlist
                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    filtered = [x for x in rows if sSearch.lower() in str(x).lower()]
                else:
                    filtered = rows

                sortcolumn = int(iSortCol_0) - 1
                if sortcolumn == 2:
                    sortcolumn = 13
                elif sortcolumn > 2:
                    sortcolumn -= 1
                serversidelogger.debug(f"sortcolumn {sortcolumn}")
                filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                              reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]
            serversidelogger.debug(f"get_index returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_index filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_index: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []
        finally:
            db.close()
            mydict = {'iTotalDisplayRecords': len(filtered),
                      'iTotalRecords': len(rowlist),
                      'aaData': rows,
                      'loading': lazylibrarian.AUTHORS_UPDATE,
                      'searching': lazylibrarian.SEARCHING,
                      }
        serversidelogger.debug(str(mydict))
        return mydict

    @staticmethod
    def label_thread(name=None):
        if name:
            thread_name(name)
        else:
            threadname = thread_name()
            if "Thread" in threadname:
                thread_name("WEBSERVER")

    # USERS ############################################################

    @cherrypy.expose
    @require_auth()
    def help(self):
        cookie = cherrypy.request.cookie
        if cookie and 'll_template' in list(cookie.keys()):
            template = cookie['ll_template'].value
            for itm in [['index.html', 'overview'],
                        ['books.html', 'ebooks'],
                        ['series.html', 'series'],
                        ['audio.html', 'audiobooks'],
                        ['magazines.html', 'magazines'],
                        ['managebooks.html', 'manage'],
                        ['history.html', 'history'],
                        ['logs.html', 'logs'],
                        ['config.html', 'config_menus'],
                        ['author.html', 'authors'],
                        ['issues.html', 'magazine_detail'],
                        ['users.html', 'config_users'],
                        ]:
                if template == itm[0]:
                    page = itm[1]
                    if template == 'config.html' and 'configTab' in list(cookie.keys()):
                        tab = check_int(cookie['configTab'].value, 1)
                        tabs = ['interface', 'importing', 'downloaders', 'providers', 'processing',
                                'notifications', 'categories', 'filters', 'genres']
                        with contextlib.suppress(IndexError):
                            page = 'config_' + tabs[tab - 1]
                    raise cherrypy.HTTPRedirect("https://lazylibrarian.gitlab.io/" + page)
        raise cherrypy.HTTPRedirect("https://lazylibrarian.gitlab.io/")

    @cherrypy.expose
    @require_auth()
    def logout(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        if cookie and 'll_uid' in list(cookie.keys()):
            db = database.DBConnection()
            db.action('UPDATE users SET prefs=? where UserID=?', (userprefs, cookie['ll_uid'].value))
            db.close()
        clear_our_cookies()
        lazylibrarian.LOGINUSER = None
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    @require_auth()
    def user_register(self):
        self.label_thread("REGISTER")
        return serve_template(templatename="register.html", title="User Registration / Contact form")

    @cherrypy.expose
    @require_auth()
    def user_update(self, **kwargs):
        if ('password' in kwargs and 'password2' in kwargs and kwargs['password'] and
                kwargs['password'] != kwargs['password2']):
            return "Passwords do not match"
        if kwargs['password'] and not pwd_check(kwargs['password']):
            return "Password must be at least 8 characters long\nand not contain spaces"
        logger = logging.getLogger(__name__)
        changes = ''
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            userid = cookie['ll_uid'].value
            db = database.DBConnection()
            user = db.match('SELECT UserName,Name,Email,Password,BookType,SendTo,Theme,hc_token '
                            'from users where UserID=?', (userid,))
            if user:
                if kwargs['username'] and user['UserName'] != kwargs['username']:
                    # if username changed, must not have same username as another user
                    match = db.match('SELECT UserName from users where UserName=?', (kwargs['username'],))
                    if match:
                        return "Unable to change username: already exists"
                    if self.validate_param("username", kwargs['username'], ['<', '>', '='], None):
                        changes += ' username'
                        db.action('UPDATE users SET UserName=? WHERE UserID=?', (kwargs['username'], userid))
                    else:
                        logger.warning("Invalid username")

                if kwargs['fullname'] and user['Name'] != kwargs['fullname']:
                    if self.validate_param("fullname", kwargs['fullname'], ['<', '>', '='], None):
                        changes += ' name'
                        db.action('UPDATE users SET Name=? WHERE UserID=?', (kwargs['fullname'], userid))
                    else:
                        logger.warning("Invalid fullname")

                if kwargs['email'] and user['Email'] != kwargs['email']:
                    if not is_valid_email(kwargs['email']):
                        logger.warning("Invalid email")
                    else:
                        changes += ' email'
                        db.action('UPDATE users SET email=? WHERE UserID=?', (kwargs['email'], userid))

                if user['Theme'] != kwargs['theme']:
                    valid = False
                    theme = kwargs['theme']
                    if theme in ['None', 'Default', '']:
                        theme = ''
                    if not theme:
                        valid = True
                    if theme == 'legacy':
                        valid = True
                    else:
                        parts = theme.split('_', 1)
                        if (parts[0] == 'bookstrap' and len(parts) == 2 and parts[1] in
                                lazylibrarian.BOOKSTRAP_THEMELIST):
                            valid = True
                    if valid:
                        changes += ' Theme'
                        db.action('UPDATE users SET Theme=? WHERE UserID=?', (theme, userid))
                    else:
                        logger.warning(f"Invalid user theme [{theme}]")

                if user['SendTo'] != kwargs['sendto']:
                    if not is_valid_email(kwargs['sendto']):
                        logger.warning("Invalid email")
                    else:
                        changes += ' sendto'
                        db.action('UPDATE users SET sendto=? WHERE UserID=?', (kwargs['sendto'], userid))

                if user['BookType'] != kwargs['booktype']:
                    changes += ' BookType'
                    db.action('UPDATE users SET BookType=? WHERE UserID=?', (kwargs['booktype'], userid))

                if user['hc_token'] != kwargs['hc_token']:
                    if self.validate_param("hardcopy token", kwargs['hc_token'], ['<', '>', '='], None):
                        changes += ' hc_token'
                        db.action('UPDATE users SET hc_token=? WHERE UserID=?', (kwargs['hc_token'], userid))
                    else:
                        logger.warning("Invalid hardcopy token")

                if kwargs['password']:
                    pwd = md5_utf8(kwargs['password'])
                    if pwd != user['password']:
                        changes += ' password'
                        db.action('UPDATE users SET password=? WHERE UserID=?', (pwd, userid))

                # only allow admin to change these
                # if kwargs['calread'] and user['CalibreRead'] != kwargs['calread']:
                #     changes += ' CalibreRead'
                #     db.action('UPDATE users SET CalibreRead=? WHERE UserID=?', (kwargs['calread'], userid))

                # if kwargs['caltoread'] and user['CalibreToRead'] != kwargs['caltoread']:
                #     changes += ' CalibreToRead'
                #     db.action('UPDATE users SET CalibreToRead=? WHERE UserID=?', (kwargs['caltoread'], userid))
            db.close()

            if changes:
                return f'Updated user details:{changes}'
        return "No changes made"

    @cherrypy.expose
    @require_auth()
    def user_login(self, **kwargs):
        # anti-phishing
        # block ip address if over 3 failed usernames in a row.
        # don't count attempts older than 24 hrs
        logger = logging.getLogger(__name__)
        self.label_thread("LOGIN")
        limit = int(time.time()) - 1 * 60 * 60
        lazylibrarian.USER_BLOCKLIST[:] = [x for x in lazylibrarian.USER_BLOCKLIST if x[1] > limit]
        remote_ip = cherrypy.request.remote.ip
        cnt = 0
        for itm in lazylibrarian.USER_BLOCKLIST:
            if itm[0] == remote_ip:
                cnt += 1
        if cnt >= 3:
            msg = f"IP address [{remote_ip}] is blocked"
            logger.warning(msg)
            return msg

        username = ''
        password = ''
        res = {}
        pwd = ''
        if 'username' in kwargs:
            username = kwargs['username']
        if 'password' in kwargs:
            password = kwargs['password']
        if username and password:
            pwd = md5_utf8(password)
            db = database.DBConnection()
            try:
                res = db.match('SELECT * from users where username=?', (username,))  # type: dict
            finally:
                db.close()
        if res and pwd == res['Password']:
            cherrypy.response.cookie['ll_uid'] = res['UserID']
            cherrypy.response.cookie['ll_prefs'] = res['Prefs']
            if 'remember' in kwargs:
                cherrypy.response.cookie['ll_uid']['Max-Age'] = '86400'

            # successfully logged in, clear any failed attempts
            lazylibrarian.USER_BLOCKLIST[:] = [x for x in lazylibrarian.USER_BLOCKLIST if x[0] != username]
            logger.debug(f"User {username} logged in")
            db = database.DBConnection()
            try:
                db.action("UPDATE users SET Last_Login=?,Login_Count=? WHERE UserID=?",
                          (str(int(time.time())), int(res['Login_Count']) + 1, res['UserID']))
            finally:
                db.close()
            lazylibrarian.SHOWLOGOUT = 1
            msg = ''
        elif res:
            # anti-phishing. Block user if 3 failed passwords in a row.
            cnt = 0
            for itm in lazylibrarian.USER_BLOCKLIST:
                if itm[0] == username:
                    cnt += 1
            if cnt >= 2:
                msg = "Too many failed attempts. Reset password or retry after 1 hour"
                logger.warning(f"Blocked user: {username}: [{remote_ip}] {msg}")
            else:
                lazylibrarian.USER_BLOCKLIST.append((username, int(time.time())))
                msg = f"Wrong password entered. You have {2 - cnt} {plural(2 - cnt, 'attempt')} left"
            logger.warning(f"Failed login attempt: {username}: [{remote_ip}] {lazylibrarian.LOGIN_MSG}")
        else:
            # invalid or missing username, or valid user but missing password
            msg = "Invalid user or password."
            logger.warning(f"Blocked IP: {username}: [{remote_ip}] {msg}")
            lazylibrarian.USER_BLOCKLIST.append((remote_ip, int(time.time())))
        return msg

    @cherrypy.expose
    @require_auth()
    def user_contact(self, **kwargs):
        self.label_thread('USERCONTACT')
        logger = logging.getLogger(__name__)
        remote_ip = cherrypy.request.remote.ip
        msg = f'IP: {remote_ip}\n'
        for itm in kwargs:
            if kwargs[itm]:
                line = f"{itm}: {unaccented(kwargs[itm], only_ascii=False)}\n"
            else:
                line = f"{itm}: \n"
            msg += line
        if 'email' in kwargs and kwargs['email']:
            result = notifiers.email_notifier.notify_message('Message from LazyLibrarian User',
                                                             msg, CONFIG['ADMIN_EMAIL'])
            if result:
                return "Message sent to admin, you will receive a reply by email"
            logger.error(f"Unable to send message to admin: {msg}")
            return "Message not sent, please try again later"
        return "No message sent, no return email address"

    @cherrypy.expose
    @require_auth()
    def user_admin(self):
        self.label_thread('USERADMIN')
        db = database.DBConnection()
        try:
            users = db.select('SELECT UserName from users')
        finally:
            db.close()
        return serve_template(templatename="users.html", title="Manage User Accounts", users=users)

    @cherrypy.expose
    @require_auth()
    def update_feeds(self, **kwargs):
        logger = logging.getLogger(__name__)
        if 'value' in kwargs and kwargs['value'] == '':
            # cancel or [x] pressed
            return 'No changes made'
        user = kwargs.pop('user', '')
        value = get_list(kwargs.pop('value[]', ''))
        cnt = 0
        db = database.DBConnection()
        for itm in kwargs:
            if '[text]' in itm:
                feedname = kwargs[itm]
                feednum = kwargs.get(itm.replace('[text]', '[value]'), '')
                if feedname and feednum:
                    res = db.match('SELECT * from subscribers WHERE Type=? and UserID=? and WantID=?',
                                   ("feed", user, feedname))
                    if feednum in value:
                        if res:
                            logger.debug(f"{feedname} {user} was already subscribed")
                        else:
                            cnt += 1
                            db.action('INSERT INTO subscribers (Type, UserID, WantID) VALUES (?, ?, ?)',
                                      ("feed", user, feedname))
                            logger.debug(f"Subscribed {user} to {feedname}")
                    else:
                        if res:
                            cnt += 1
                            db.action('DELETE from subscribers WHERE Type=? and UserID=? and WantID=?',
                                      ("feed", user, feedname))
                            logger.debug(f"Unsubscribed {user} to {feedname}")
                        else:
                            logger.debug(f"{feedname} {user} was already unsubscribed")
        db.close()
        return f"Changed {cnt} {plural(cnt, 'feed')}"

    @cherrypy.expose
    @require_auth()
    def user_feeds(self, **kwargs):
        logger = logging.getLogger(__name__)
        user = kwargs['user']
        if user:
            feedlist = []
            value = []
            cnt = 0
            db = database.DBConnection()
            try:
                feeds = db.select("SELECT * from subscribers where Type='feed' and UserID=?", (user,))
            finally:
                db.close()
            for provider in CONFIG.providers('RSS'):
                wishtype = wishlist_type(provider['HOST'])
                if wishtype:
                    cnt += 1
                    subscribed = False
                    for itm in feeds:
                        if itm['WantID'] == provider['DISPNAME']:
                            subscribed = True
                            break
                    feedlist.append({'text': provider['DISPNAME'], 'value': str(cnt)})
                    if subscribed:
                        value.append(str(cnt))
            res = json.dumps({'feeds': feedlist, 'value': value})
            logger.debug(res)
            return res
        return json.dumps({'feeds': '', 'value': ''})

    @cherrypy.expose
    @require_auth()
    def admin_delete(self, **kwargs):
        self.check_permitted(lazylibrarian.perm_admin)
        db = database.DBConnection()
        try:
            user = kwargs['user']
            if user:
                match = db.match('SELECT Perms from users where UserName=?', (user,))
                if match:
                    perm = check_int(match['Perms'], 0)
                    if perm & 1:
                        count = 0
                        perms = db.select('SELECT Perms from users')
                        for itm in perms:
                            val = check_int(itm['Perms'], 0)
                            if val & lazylibrarian.perm_config:
                                count += 1
                        if count < 2:
                            return "Unable to delete last administrator"
                    db.action('DELETE from users WHERE UserName=?', (user,))
                    return f"User {user} deleted"
                return "User not found"
            return "No user!"
        finally:
            db.close()

    @cherrypy.expose
    @require_auth()
    def get_user_profile(self, **kwargs):
        self.check_permitted(lazylibrarian.perm_admin)
        db = database.DBConnection()
        match = db.match('SELECT * from users where UserName=?', (kwargs['user'],))
        if match:
            subs = db.select('SELECT Type,WantID from subscribers WHERE UserID=?', (match['userid'],))
            cnt = db.match('select count(*) as counter from sent_file where UserID=?', (match['userid'],))
            last_login = check_int(match['Last_Login'], 0)
            subscriptions = ''
            for itm in subs:
                if itm['Type'] != 'ebook':
                    if subscriptions:
                        subscriptions += '\n'
                    subscriptions += f'{itm["Type"]} {itm["WantID"]}'
            res = json.dumps({'email': match['Email'], 'name': match['Name'], 'perms': match['Perms'],
                              'calread': match['CalibreRead'], 'caltoread': match['CalibreToRead'],
                              'sendto': match['SendTo'], 'booktype': match['BookType'], 'userid': match['UserID'],
                              'lastlogin': datetime.datetime.fromtimestamp(last_login).ctime()
                              if last_login else '',
                              'logins': match['Login_Count'], 'downloads': cnt['counter'], 'subs': subscriptions,
                              'theme': match['Theme'], 'hc_id': match['hc_id'], 'hc_token': match['hc_token']})
        else:
            res = json.dumps({'email': '', 'name': '', 'perms': '0', 'calread': '', 'caltoread': '', 'sendto': '',
                              'booktype': '', 'userid': '', 'lastlogin': '', 'logins': '0', 'subs': '',
                              'theme': '', 'hc_id': '', 'hc_token': ''})
        db.close()
        return res

    @cherrypy.expose
    @require_auth()
    def admin_users(self, **kwargs):
        self.check_permitted(lazylibrarian.perm_admin)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()

        user = kwargs['user']
        new_user = not user
        changes = ''

        if new_user:
            msg = "New user NOT added: "
            if not kwargs['username']:
                db.close()
                return msg + "No username given"
            # new user must not have same username as an existing one
            match = db.match('SELECT UserName from users where UserName=?', (kwargs['username'],))
            if match:
                db.close()
                return msg + "Username already exists"

            if not kwargs['fullname']:
                db.close()
                return msg + "No fullname given"

            if not kwargs['email']:
                db.close()
                return msg + "No email given"

            if not is_valid_email(kwargs['email']):
                db.close()
                return msg + "Invalid email given"

            perms = check_int(kwargs['perms'], 0)
            if not perms:
                db.close()
                return msg + "No permissions or invalid permissions given"
            if not kwargs['password']:
                db.close()
                return msg + "No password given"

            if perms == lazylibrarian.perm_admin:
                perm_msg = 'ADMIN'
            elif perms == lazylibrarian.perm_friend:
                perm_msg = 'Friend'
            elif perms == lazylibrarian.perm_guest:
                perm_msg = 'Guest'
            else:
                perm_msg = f'Custom {perms}'

            self.validate_param("username", kwargs['username'], ['<', '>', '='], 404)
            self.validate_param("fullname", kwargs['fullname'], ['<', '>', '='], 404)
            msg = lazylibrarian.NEWUSER_MSG.replace('{username}', kwargs['username']).replace(
                '{password}', kwargs['password']).replace(
                '{permission}', perm_msg)

            result = notifiers.email_notifier.notify_message('LazyLibrarian New Account', msg, kwargs['email'])

            if result:
                cmd = ("INSERT into users (UserID, UserName, Name, Password, Email, SendTo, Perms, hc_token) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
                db.action(cmd, (pwd_generator(), kwargs['username'], kwargs['fullname'],
                                md5_utf8(kwargs['password']), kwargs['email'], kwargs['sendto'], perms,
                                kwargs.get('hc_token', '')))
                msg = f"New user added: {kwargs['username']}: {perm_msg}"
                msg += f"<br>Email sent to {kwargs['email']}"
                cnt = db.match("select count(*) as counter from users")
                if cnt['counter'] > 1:
                    lazylibrarian.SHOWLOGOUT = 1
            else:
                msg = "New user NOT added"
                msg += f"<br>Failed to send email to {kwargs['email']}"
            db.close()
            return msg

        if user != kwargs['username']:
            # if username changed, must not have same username as another user
            match = db.match('SELECT UserName from users where UserName=?', (kwargs['username'],))
            if match:
                db.close()
                return "Username already exists"

        cmd = ("SELECT UserID,Name,Email,SendTo,Password,Perms,CalibreRead,CalibreToRead,BookType,Theme,"
               "hc_token from users where UserName=?")
        details = db.match(cmd, (user,))

        if details:
            userid = details['UserID']
            if kwargs['username'] and kwargs['username'] != user:
                changes += ' username'
                db.action('UPDATE users SET UserName=? WHERE UserID=?', (kwargs['username'], userid))

            if kwargs['fullname'] and details['Name'] != kwargs['fullname']:
                changes += ' name'
                db.action('UPDATE users SET Name=? WHERE UserID=?', (kwargs['fullname'], userid))

            if details['Email'] != kwargs['email']:
                if kwargs['email'] and not is_valid_email(kwargs['email']):
                    return "Invalid email given"
                changes += ' email'
                db.action('UPDATE users SET email=? WHERE UserID=?', (kwargs['email'], userid))

            if details['SendTo'] != kwargs['sendto']:
                if kwargs['sendto'] and not is_valid_email(kwargs['sendto']):
                    return "Invalid sendto email given"
                changes += ' sendto'
                db.action('UPDATE users SET sendto=? WHERE UserID=?', (kwargs['sendto'], userid))

            if kwargs['password']:
                pwd = md5_utf8(kwargs['password'])
                if pwd != details['Password']:
                    changes += ' password'
                    db.action('UPDATE users SET password=? WHERE UserID=?', (pwd, userid))

            if details['Theme'] != kwargs['theme']:
                valid = False
                if kwargs['theme'] == 'legacy':
                    valid = True
                elif kwargs['theme']:
                    parts = kwargs['theme'].split('_', 1)
                    if parts[0] == 'bookstrap' and len(parts) == 2 and parts[1] in lazylibrarian.BOOKSTRAP_THEMELIST:
                        valid = True
                if valid:
                    changes += ' Theme'
                    db.action('UPDATE users SET Theme=? WHERE UserID=?', (kwargs['theme'], userid))
                else:
                    logger.warning(f"Invalid user theme [{kwargs['theme']}]")

            if details['CalibreRead'] != kwargs['calread']:
                changes += ' CalibreRead'
                db.action('UPDATE users SET CalibreRead=? WHERE UserID=?', (kwargs['calread'], userid))

            if details['CalibreToRead'] != kwargs['caltoread']:
                changes += ' CalibreToRead'
                db.action('UPDATE users SET CalibreToRead=? WHERE UserID=?', (kwargs['caltoread'], userid))

            if details['BookType'] != kwargs['booktype']:
                changes += ' BookType'
                db.action('UPDATE users SET BookType=? WHERE UserID=?', (kwargs['booktype'], userid))

            if details['hc_token'] != kwargs['hc_token']:
                changes += ' hc_token'
                db.action('UPDATE users SET hc_token=? WHERE UserID=?', (kwargs['hc_token'], userid))

            if details['Perms'] != kwargs['perms']:
                oldperm = check_int(details['Perms'], 0)
                newperm = check_int(kwargs['perms'], 0)
                if oldperm & 1 and not newperm & 1:
                    count = 0
                    perms = db.select('SELECT Perms from users')
                    for itm in perms:
                        val = check_int(itm['Perms'], 0)
                        if val & 1:
                            count += 1
                    if count < 2:
                        db.close()
                        return "Unable to remove last administrator"
                if oldperm != newperm:
                    changes += ' Perms'
                    db.action('UPDATE users SET Perms=? WHERE UserID=?', (kwargs['perms'], userid))

        if changes:
            msg = f'Updated user details:{changes}'
        else:
            msg = "No changes made"
        db.close()
        return msg

    @cherrypy.expose
    @require_auth()
    def password_reset(self, **kwargs):
        self.label_thread('PASSWORD_RESET')
        logger = logging.getLogger(__name__)
        res = {}
        remote_ip = cherrypy.request.remote.ip
        db = database.DBConnection()
        if 'username' in kwargs and kwargs['username']:
            logger.debug(f"Reset password request from {kwargs['username']}, IP:{remote_ip}")
            res = db.match('SELECT UserID,Email from users where username=?', (kwargs['username'],))  # type: dict
            if res:
                if 'email' in kwargs and kwargs['email']:
                    if res['Email']:
                        if kwargs['email'] == res['Email']:
                            msg = ''
                        else:
                            msg = 'Email does not match our records'
                    else:
                        msg = 'No email address registered'
                else:
                    msg = 'No email address supplied'
            else:
                msg = "Unknown username"
        else:
            msg = "Who are you?"

        if res and not msg:
            new_pwd = pwd_generator()
            msg = f"Your new password is {new_pwd}"
            result = notifiers.email_notifier.notify_message('LazyLibrarian New Password', msg, res['Email'])
            if result:
                pwd = md5_utf8(new_pwd)
                db.action("UPDATE users SET Password=? WHERE UserID=?", (pwd, res['UserID']))
                return "Password reset, check your email"
            msg = f"Failed to send email to [{res['Email']}]"
            logger.debug(msg)
        db.close()
        msg = f"Password not reset: {msg}"
        logger.error(f"{msg} IP:{remote_ip}")
        return msg

    @cherrypy.expose
    @require_auth()
    def generatepwd(self):
        return pwd_generator()

    # SERIES ############################################################
    @cherrypy.expose
    @require_auth()
    def remove_series(self, seriesid):
        self.check_permitted(lazylibrarian.perm_edit)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        seriesdata = db.match("SELECT * from series WHERE seriesid=?", (seriesid,))
        if seriesdata:
            db.action("DELETE from series WHERE SeriesID=?", (seriesid,))
        else:
            logger.warning(f'Missing series: {seriesid}')
        db.close()
        raise cherrypy.HTTPRedirect("series")

    @cherrypy.expose
    @require_auth()
    def edit_series(self, seriesid):
        logger = logging.getLogger(__name__)
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('EDIT_SERIES')
        db = database.DBConnection()
        seriesdata = db.match("SELECT * from series WHERE seriesid=?", (seriesid,))
        if seriesdata:
            # use bookid to update seriesdata['Reason']
            seriesdata = dict(seriesdata)
            cmd = "select BookName,BookID from books where (bookid=?) or (gr_id=?) or (lt_workid=?)"
            reason = seriesdata['Reason']
            bookinfo = db.match(cmd, (reason, reason, reason))
            if bookinfo:
                seriesdata['Reason'] = f"{bookinfo['BookID']}: {bookinfo['BookName']}"

            cmd = "SELECT SeriesNum,BookName from member,books WHERE books.BookID=member.BookID and seriesid=?"
            memberdata = db.select(cmd, (seriesid,))
            # sort properly by seriesnum as sqlite doesn't (yet) have natural sort
            members = []
            for itm in memberdata:
                members.append(dict(itm))
            self.natural_sort(members, key=lambda y: y['SeriesNum'] if y['SeriesNum'] is not None else '')
            db.close()
            return serve_template(templatename="editseries.html", title="Edit Series", config=seriesdata,
                                  members=members)
        logger.info(f'Missing series {seriesid}')
        db.close()
        raise cherrypy.HTTPError(404, f"Series {seriesid} not found")

    @cherrypy.expose
    @require_auth()
    def series_update(self, seriesid='', **kwargs):
        self.check_permitted(lazylibrarian.perm_edit)
        logger = logging.getLogger(__name__)
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        db = database.DBConnection()
        if seriesid:
            old_data = db.match("SELECT * from series where seriesid=?", (seriesid,))
            if old_data:
                updated = False
                seriesname = old_data['SeriesName']
                seriesid = old_data['SeriesID']
                new_id = kwargs.get('new_id')
                if new_id and new_id != seriesid:
                    seriesid = new_id
                    updated = True
                new_name = kwargs.get('new_name')
                if new_name:
                    self.validate_param("new series name", new_name, ['<', '>', '='], 404)
                if new_name and new_name != seriesname:
                    seriesname = new_name
                    updated = True
                if updated:
                    db.action('PRAGMA foreign_keys = OFF')
                    db.action("UPDATE series SET SeriesID=?, SeriesName=? WHERE SeriesID=?",
                              (seriesid, seriesname, old_data['SeriesID']))
                    if seriesid != old_data['SeriesID']:
                        for table in ['member', 'seriesauthors']:
                            cmd = "UPDATE " + table + " SET SeriesID=? WHERE SeriesID=?"
                            db.action(cmd, (seriesid, old_data['SeriesID']))
                    db.action('PRAGMA foreign_keys = ON')
                    logger.debug(f"Updated series info for {seriesid}:{seriesname}")
            else:
                logger.debug(f"No match updating series {seriesid}")
                raise cherrypy.HTTPError(404, f"Series {seriesid} not found")
        db.close()
        raise cherrypy.HTTPRedirect("series")

    @cherrypy.expose
    @require_auth()
    def refresh_series(self, seriesid):
        logger = logging.getLogger(__name__)
        self.check_permitted(lazylibrarian.perm_force)
        threadname = f'SERIESMEMBERS_{seriesid}'
        if threadname in [n.name for n in list(threading.enumerate())]:
            logger.warning(f"{threadname} is already running")
        else:
            threading.Thread(target=add_series_members, name=threadname, args=[seriesid, True]).start()
        raise cherrypy.HTTPRedirect(f"series_members?seriesid={seriesid}&ignored=False")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_series(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        filtered = []
        userid = None
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            userid = cookie['ll_uid'].value
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)

        # noinspection PyBroadException
        try:
            # kwargs is used by datatables to pass params
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            which_status = 'All'
            if kwargs['whichStatus']:
                which_status = kwargs['whichStatus']

            author_id = ''
            if kwargs['AuthorID']:
                author_id = kwargs['AuthorID']

            if not author_id or author_id == 'None':
                author_id = ''

            # We pass series.SeriesID twice for datatables as the render function modifies it,
            # and we need it in two columns. There is probably a better way...
            cmd = ("SELECT series.SeriesID,AuthorName,SeriesName,series.Status,seriesauthors.AuthorID,series."
                   "SeriesID,Have,Total,series.Reason from series,authors,seriesauthors,member where "
                   "authors.AuthorID=seriesauthors.AuthorID and series.SeriesID=seriesauthors.SeriesID and "
                   "member.seriesid=series.seriesid")  # and seriesnum=1"

            if 'active' in kwargs and kwargs['active'] and not author_id:
                cmd += " and authors.status IN ('Active', 'Wanted')"

            args = []
            if which_status == 'Empty':
                cmd += " and Have = 0"
            elif which_status == 'Partial':
                cmd += " and Have > 0"
            elif which_status == 'Complete':
                cmd += " and Have > 0 and Have = Total"
            elif which_status not in ['All', 'None']:
                cmd += " and series.Status=?"
                args.append(which_status)
            if author_id:
                cmd += " and seriesauthors.AuthorID=?"
                args.append(author_id)

            myseries = []
            db = database.DBConnection()
            if userid and userprefs & lazylibrarian.pref_myseries:
                res = db.select("SELECT WantID from subscribers WHERE Type='series' and UserID=?", (userid,))
                serversidelogger.debug(f"User subscribes to {len(res)} series")
                for series in res:
                    myseries.append(series['WantID'])
                cmd += " and series.seriesID in (" + ", ".join(f"'{w}'" for w in myseries) + ")"

            cmd += " GROUP BY series.seriesID order by AuthorName,SeriesName"

            serversidelogger.debug(f"get_series {cmd}: {str(args)}")

            if args:
                rowlist = db.select(cmd, tuple(args))
            else:
                rowlist = db.select(cmd)
            db.close()

            # turn the sqlite rowlist into a list of lists
            if len(rowlist):
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    entry = list(row)  # turn sqlite objects into lists
                    rows.append(entry)  # add the rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    filtered = [x for x in rows if sSearch.lower() in str(x).lower()]
                else:
                    filtered = rows

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                for row in filtered:
                    row.append(row[0][:2])  # extract 2 letter source from seriesid
                    if CONFIG.get_bool('SORT_SURNAME'):
                        row[1] = surname_first(row[1], postfixes=get_list(CONFIG.get_csv('NAME_POSTFIX')))
                    have = check_int(row[6], 0)
                    total = check_int(row[7], 0)
                    if total:
                        percent = int((have * 100.0) / total)
                    else:
                        percent = 0

                    if percent > 100:
                        percent = 100

                    row.append(percent)

                if sortcolumn == 3:  # percent
                    sortcolumn = 9
                if sortcolumn == 4:  # status
                    sortcolumn = 3

                if sortcolumn == 9:  # sort on percent,-total
                    if sSortDir_0 == "desc":
                        filtered.sort(key=lambda y: (-int(y[10]), int(y[7])))
                    else:
                        filtered.sort(key=lambda y: (int(y[10]), -int(y[7])))
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

            serversidelogger.debug(f"get_series returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_series filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
            mydict = {'iTotalDisplayRecords': len(filtered),
                      'iTotalRecords': len(rowlist),
                      'aaData': rows,
                      }
            serversidelogger.debug(str(mydict))
            return mydict

        except Exception:
            logger.error(f'Unhandled exception in get_series: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []
            mydict = {'iTotalDisplayRecords': len(filtered),
                      'iTotalRecords': len(rowlist),
                      'aaData': rows,
                      }
            serversidelogger.debug(str(mydict))
            return mydict

    @cherrypy.expose
    @require_auth()
    def series(self, authorid=None, which_status=None, active=False):
        self.check_permitted(lazylibrarian.perm_series)
        title = "Series"
        if authorid:
            db = database.DBConnection()
            try:
                match = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
            finally:
                db.close()
            if match:
                title = f"{match['AuthorName']} Series"
            if '&' in title and '&amp;' not in title:
                title = title.replace('&', '&amp;')

        return serve_template(templatename="series.html", title=title, authorid=authorid, series=[],
                              whichStatus=which_status, active=active)

    @cherrypy.expose
    @require_auth()
    def series_members(self, seriesid, ignored=False):
        self.check_permitted(lazylibrarian.perm_series)
        db = database.DBConnection()
        cmd = ("SELECT SeriesName,series.SeriesID,AuthorName,seriesauthors.AuthorID from "
               "series,authors,seriesauthors where authors.AuthorID=seriesauthors.AuthorID and "
               "series.SeriesID=seriesauthors.SeriesID and series.SeriesID=?")
        series = db.match(cmd, (seriesid,))
        cmd = ("SELECT member.BookID,BookName,SeriesNum,BookImg,books.Status,AuthorName,authors.AuthorID,"
               "BookLink,WorkPage,AudioStatus,BookSub from member,series,books,authors where "
               "series.SeriesID=member.SeriesID and books.BookID=member.BookID and "
               "books.AuthorID=authors.AuthorID and ")
        if not ignored or ignored == 'False':
            cmd += "(books.Status != 'Ignored' and AudioStatus != 'Ignored')"
        else:
            cmd += "(books.Status == 'Ignored' or AudioStatus == 'Ignored')"
        cmd += " and series.SeriesID=? order by SeriesName"
        members = db.select(cmd, (seriesid,))
        # is it a multi-author series?
        multi = "False"
        authorid = ''
        for itm in members:
            if not authorid:
                authorid = itm['AuthorID']
            else:
                if authorid != itm['AuthorID']:
                    multi = "True"
                    break

        email = ''
        to_read = set()
        have_read = set()
        reading = set()
        abandoned = set()
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            cmd = "SELECT UserName,Perms,SendTo from users where UserID=?"
            userid = cookie['ll_uid'].value
            res = db.match(cmd, (userid,))
            if res:
                to_read = get_readinglist('ToRead', userid)
                have_read = get_readinglist('HaveRead', userid)
                reading = get_readinglist('Reading', userid)
                abandoned = get_readinglist('Abandoned', userid)
                email = res['SendTo']
                if not email:
                    email = ''
        db.close()
        # turn the sqlite rowlist into a list of lists
        rows = []

        if len(members):
            # the masterlist to be filled with the row data
            for row in members:  # iterate through the sqlite3.Row objects
                entry = list(row)
                if entry[0] in to_read:
                    flag = '&nbsp;<i class="far fa-bookmark"></i>'
                elif entry[0] in have_read:
                    flag = '&nbsp;<i class="fas fa-bookmark"></i>'
                elif entry[0] in reading:
                    flag = '&nbsp;<i class="fas fa-play-circle"></i>'
                elif entry[0] in abandoned:
                    flag = '&nbsp;<i class="fas fa-ban"></i>'
                else:
                    flag = ''
                if entry[10]:  # is there a subtitle
                    bk_name = f'{entry[1]}<br><small><i>{entry[10]}</i></small>'
                else:
                    bk_name = entry[1]
                newrow = {'BookID': entry[0], 'BookName': bk_name, 'SeriesNum': entry[2], 'BookImg': entry[3],
                          'Status': entry[4], 'AuthorName': entry[5], 'AuthorID': entry[6],
                          'BookLink': entry[7] if entry[7] else '', 'WorkPage': entry[8] if entry[8] else '',
                          'AudioStatus': entry[9], 'Flag': flag}

                rows.append(newrow)  # add the new dict to the masterlist

        return serve_template(templatename="members.html", title=series['SeriesName'],
                              members=rows, series=series, multi=multi, ignored=ignored, email=email)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_series_ajax(self, action=None, **args):
        self.check_permitted(lazylibrarian.perm_status)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        args.pop('book_table_length', None)
        passed = 0
        failed = 0
        redirect = ''
        if action:
            for seriesid in args:
                if action in ["Wanted", "Active", "Skipped", "Ignored", "Paused"]:
                    match = db.match('SELECT SeriesName from series WHERE SeriesID=?', (seriesid,))
                    if not match:
                        logger.debug(f"Failed to match {seriesid}")
                        failed += 1
                    else:
                        passed += 1
                        db.upsert("series", {'Status': action}, {'SeriesID': seriesid})
                        logger.debug(f'Status set to "{action}" for "{match["SeriesName"]}"')
                        if action in ['Wanted', 'Active']:
                            threadname = f'SERIESMEMBERS_{seriesid}'
                            if threadname not in [n.name for n in list(threading.enumerate())]:
                                threading.Thread(target=add_series_members, name=threadname,
                                                 args=[seriesid]).start()
                            ensure_running('series_update')
                        else:
                            # stop monitoring
                            db.action("UPDATE series SET Updated=0 WHERE SeriesID=?", (seriesid,))
                elif action in ["Unread", "Read", "ToRead", "Reading", "Abandoned"]:
                    cookie = cherrypy.request.cookie
                    if cookie and 'll_uid' in list(cookie.keys()):
                        userid = cookie['ll_uid'].value
                        to_read = set(get_readinglist('ToRead', userid))
                        have_read = set(get_readinglist('HaveRead', userid))
                        reading = set(get_readinglist('Reading', userid))
                        abandoned = set(get_readinglist('Abandoned', userid))
                        members = db.select('SELECT bookid from member where seriesid=?', (seriesid,))
                        if not members:
                            logger.debug(f"No members found for {seriesid}")
                            failed += 1
                        else:
                            for itm in members:
                                bookid = itm['bookid']
                                if action == "Unread":
                                    to_read.discard(bookid)
                                    have_read.discard(bookid)
                                    reading.discard(bookid)
                                    abandoned.discard(bookid)
                                    logger.debug(f'Status set to "unread" for "{bookid}"')
                                elif action == "Read":
                                    to_read.discard(bookid)
                                    reading.discard(bookid)
                                    abandoned.discard(bookid)
                                    have_read.add(bookid)
                                    logger.debug(f'Status set to "read" for "{bookid}"')
                                elif action == "ToRead":
                                    reading.discard(bookid)
                                    abandoned.discard(bookid)
                                    have_read.discard(bookid)
                                    to_read.add(bookid)
                                    logger.debug(f'Status set to "to read" for "{bookid}"')
                                elif action == "Reading":
                                    reading.add(bookid)
                                    abandoned.discard(bookid)
                                    have_read.discard(bookid)
                                    to_read.discard(bookid)
                                    logger.debug(f'Status set to "reading" for "{bookid}"')
                                elif action == "Abandoned":
                                    reading.discard(bookid)
                                    abandoned.add(bookid)
                                    have_read.discard(bookid)
                                    to_read.discard(bookid)
                                    logger.debug(f'Status set to "abandoned" for "{bookid}"')
                                passed += 1
                            set_readinglist('ToRead', userid, to_read)
                            set_readinglist('HaveRead', userid, have_read)
                            set_readinglist('Reading', userid, reading)
                            set_readinglist('Abandoned', userid, abandoned)

                elif action == 'Subscribe':
                    cookie = cherrypy.request.cookie
                    if cookie and 'll_uid' in list(cookie.keys()):
                        userid = cookie['ll_uid'].value
                        res = db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                                       (userid, 'series', seriesid))
                        if res:
                            logger.debug(f"User {userid} is already subscribed to {seriesid}")
                            failed += 1
                        else:
                            db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                                      (userid, 'series', seriesid))
                            logger.debug(f"Subscribe {userid} to series {seriesid}")
                            passed += 1
                elif action == 'Unsubscribe':
                    cookie = cherrypy.request.cookie
                    if cookie and 'll_uid' in list(cookie.keys()):
                        userid = cookie['ll_uid'].value
                        db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                  (userid, 'series', seriesid))
                        passed += 1
                        res = db.select('SELECT bookid from series where seriesid=?', (seriesid, ))
                        for iss in res:
                            db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                      (userid, 'series', iss['bookid']))
                        logger.debug(f"Unsubscribe {userid} to series {seriesid}")

            if "redirect" in args:
                redirect = f"series?authorid={args['redirect']}"
            else:
                redirect = "series"
        db.close()

        # Return JSON response instead of redirect
        total = passed + failed
        summary = f"Mark Series '{action}' completed."
        if total > 0:
            summary += f" {passed} successful"
            if failed > 0:
                summary += f", {failed} failed"
            summary += f" out of {total} total items."
        else:
            summary += " No items were processed."
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'summary': summary,
            'redirect': redirect
        }

    # CONFIG ############################################################

    @cherrypy.expose
    @require_auth()
    def save_filters(self):
        self.check_permitted(lazylibrarian.perm_admin)
        self.label_thread('WEBSERVER')
        savedir = DIRS.DATADIR
        mags = dump_table('magazines', savedir)
        msg = f"{mags} {plural(mags, 'magazine')} exported"
        return msg

    @cherrypy.expose
    @require_auth()
    def save_users(self):
        self.check_permitted(lazylibrarian.perm_admin)
        self.label_thread('WEBSERVER')
        savedir = DIRS.DATADIR
        users = dump_table('users', savedir)
        msg = f"{users} {plural(users, 'user')} exported"
        return msg

    @cherrypy.expose
    @require_auth()
    def load_filters(self):
        self.check_permitted(lazylibrarian.perm_admin)
        self.label_thread('WEBSERVER')
        savedir = DIRS.DATADIR
        mags = restore_table('magazines', savedir)
        msg = f"{mags} {plural(mags, 'magazine')} imported"
        return msg

    @cherrypy.expose
    @require_auth()
    def load_users(self):
        self.check_permitted(lazylibrarian.perm_admin)
        self.label_thread('WEBSERVER')
        savedir = DIRS.DATADIR
        users = restore_table('users', savedir)
        msg = f"{users} {plural(users, 'user')} imported"
        return msg

    @cherrypy.expose
    @require_auth()
    def config(self):
        logger = logging.getLogger(__name__)
        self.label_thread('CONFIG')
        http_look_dir = os.path.join(DIRS.PROG_DIR, 'data' + os.path.sep + 'interfaces')
        http_look_list = [name for name in listdir(http_look_dir)
                          if path_isdir(os.path.join(http_look_dir, name))]
        status_list = ['Skipped', 'Wanted', 'Have', 'Ignored']
        apprise_list = lazylibrarian.notifiers.apprise_notify.AppriseNotifier.notify_types()

        mags_list = []
        comics_list = []
        db = database.DBConnection()
        try:
            comics = db.select(
                'SELECT * from comics ORDER by Title COLLATE NOCASE')
            magazines = db.select(
                'SELECT * from magazines ORDER by Title COLLATE NOCASE')
        finally:
            db.close()
        if comics:
            for mag in comics:
                title = mag['Title']
                genre = mag['Genre']
                if not genre:
                    genre = ""
                comics_list.append({
                    'Title': title,
                    'Genre': genre
                })
        if magazines:
            for mag in magazines:
                title = mag['Title']
                regex = mag['Regex']
                genre = mag['Genre']
                if not genre:
                    genre = ""
                if not regex:
                    regex = ""
                reject = mag['Reject']
                if not reject:
                    reject = ""
                datetype = mag['DateType']
                if not datetype:
                    datetype = ""
                language = mag['Language']
                if not language:
                    language = CONFIG['PREF_MAGLANG']
                coverpage = check_int(mag['CoverPage'], 1)
                mags_list.append({
                    'Title': title,
                    'Reject': reject,
                    'Regex': regex,
                    'Genre': genre,
                    'DateType': datetype,
                    'CoverPage': coverpage,
                    'Language': language
                })

        BLOCKHANDLER.check_day()

        # Don't pass the whole config, no need to pass the
        # lazylibrarian.globals
        months = {}
        try:
            for cnt, itm in enumerate(lazylibrarian.MONTHNAMES[0]):
                months[cnt] = ', '.join(itm)
        except Exception as e:
            logger.error(f"Unable to load monthnames: {e}")
            logger.error(f"{lazylibrarian.MONTHNAMES}")

        seasons = {}
        try:
            for itm in lazylibrarian.SEASONS:
                value = lazylibrarian.SEASONS[itm]
                if value not in seasons:
                    seasons[value] = itm
                else:
                    seasons[value] = f"{seasons[value]}, {itm}"
        except Exception as e:
            logger.error(f"Unable to load seasons: {e}")
            logger.error(f"{lazylibrarian.SEASONS}")

        namevars = name_vars('test')
        testvars = {}
        for itm in namevars:
            testvars[itm] = namevars[itm].replace(' ', '&nbsp;')
        config = {
            "http_look_list": http_look_list,
            "apprise_list": apprise_list,
            "status_list": status_list,
            "magazines_list": mags_list,
            "comics_list": comics_list,
            "namevars": testvars,
            "seasons": seasons,
            "months": months,
            "updated": time.ctime(CONFIG.get_int('GIT_UPDATED'))
        }
        for itm in CONFIG.config.values():
            if isinstance(itm, ConfigBool):
                itm.reset_read_count()  # Reset read counts as we use this to determine which settings have changed
        return serve_template(templatename="config.html", title="Settings", config=config)

    @cherrypy.expose
    @require_auth()
    def config_update(self, **kwargs):
        """ Update config based on settings in the UI """
        logger = logging.getLogger(__name__)
        self.check_permitted(lazylibrarian.perm_config)
        db = database.DBConnection()
        adminmsg = ''
        if 'user_accounts' in kwargs and kwargs['user_accounts']:
            # logger.error('CFG2: Need to handle user account changes')
            email = ''
            if 'admin_email' in kwargs and kwargs['admin_email']:
                email = kwargs['admin_email']
            else:
                adminmsg += 'Please set a contact email so users can make requests<br>'

            if email and not is_valid_email(email):
                adminmsg += 'Contact email looks invalid, please check<br>'

            admin = db.match("SELECT password from users where name='admin'")
            if admin and admin['password'] == md5_utf8('admin'):
                adminmsg += "The default admin user is \"admin\" and password is \"admin\"<br>"
                adminmsg += "This is insecure, please change it on Config -> User Admin<br>"

        # store any genre changes
        genre_changes = ''
        genrelimit = check_int(kwargs.get('genrelimit', 0), 0)
        if lazylibrarian.GRGENRES.get('genreLimit', 10) != genrelimit:
            lazylibrarian.GRGENRES['genreLimit'] = genrelimit
            genre_changes += 'limit '
        genreusers = check_int(kwargs.get('genreusers', 0), 0)
        if lazylibrarian.GRGENRES.get('genreUsers', 10) != genreusers:
            lazylibrarian.GRGENRES['genreUsers'] = genreusers
            genre_changes += 'users '
        newexcludes = sorted(get_list(kwargs.get('genreexclude', ''), ','))
        if sorted(lazylibrarian.GRGENRES.get('genreExclude', [])) != newexcludes:
            lazylibrarian.GRGENRES['genreExclude'] = newexcludes
            genre_changes += 'excludes '
        newexcludes = sorted(get_list(kwargs.get('genreexcludeparts', ''), ','))
        if sorted(lazylibrarian.GRGENRES.get('genreExcludeParts', [])) != newexcludes:
            lazylibrarian.GRGENRES['genreExcludeParts'] = newexcludes
            genre_changes += 'parts '
        # now the replacements
        genredict = {}
        for itm in kwargs:
            if itm.startswith('genrereplace['):
                mykey = make_unicode(itm.split('[')[1].split(']')[0])
                myval = make_unicode(kwargs.get(itm, ''))
                if myval:
                    genredict[mykey] = myval

        # new genre to add
        if 'genrenew' in kwargs and 'genreold' in kwargs and kwargs['genrenew'] and kwargs['genreold']:
            genredict[make_unicode(kwargs['genreold'])] = make_unicode(kwargs['genrenew'])
            genre_changes += 'new-entry '

        dicts_same = False
        if len(lazylibrarian.GRGENRES.get('genreReplace', {})) != len(genredict):
            genre_changes += 'dict-length '
        else:
            shared_items = {k: lazylibrarian.GRGENRES['genreReplace'][k]
                            for k in lazylibrarian.GRGENRES['genreReplace']
                            if k in genredict and lazylibrarian.GRGENRES['genreReplace'][k] == genredict[k]}
            if len(shared_items) != len(genredict):
                genre_changes += 'shared-values '
            else:
                dicts_same = True

        if not dicts_same:
            lazylibrarian.GRGENRES['genreReplace'] = genredict

        if genre_changes:
            logger.debug(f"Genre changes: {genre_changes}")
            logger.debug("Writing out new genres.json")
            newdict = {
                'genreLimit': lazylibrarian.GRGENRES['genreLimit'],
                'genreUsers': lazylibrarian.GRGENRES['genreUsers'],
                'genreExclude': lazylibrarian.GRGENRES['genreExclude'],
                'genreExcludeParts': lazylibrarian.GRGENRES['genreExcludeParts'],
                'genreReplace': lazylibrarian.GRGENRES['genreReplace'],
            }
            with open(syspath(os.path.join(DIRS.DATADIR, 'genres.json')), 'w') as f:
                json.dump(newdict, f, indent=4)
            logger.debug("Applying genre changes")
            check_db()

        # months lists
        new_months = []
        x = range(13)
        for month_num in x:
            key = f"month_{month_num}"
            month_names = kwargs[key]
            new_months.append(get_list(month_names))
        if new_months != lazylibrarian.MONTHNAMES[0]:
            logger.debug("MONTHNAMES has changed")
            # validate the table looks correct, same number of entries per row
            valid = True
            length = len(new_months[0])  # number of language entries
            if length % 2:  # must be even, short and long for each language
                valid = False
            if valid:
                for itm in new_months:
                    if len(itm) != length:
                        valid = False
                        break

            if not valid:
                logger.debug("New MONTHNAMES is not valid, ignoring")
            else:
                json_file = os.path.join(DIRS.DATADIR, 'monthnames.json')
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(new_months, f, ensure_ascii=False)

                # Create a second copy of the monthnames without accents and lowercased to speed up matching
                cleantable = []
                for lyne in new_months:
                    cleanlyne = []
                    for itm in lyne:
                        cleanlyne.append(unaccented(itm).lower().strip('.'))
                    cleantable.append(cleanlyne)

                lazylibrarian.MONTHNAMES = [new_months, cleantable]

        # now the season dictionary
        new_seasons = {}
        for key in kwargs:
            if key.startswith('season_'):
                season_names = kwargs[key]
                season_value = check_int(key.split('_')[1], 0)
                for itm in get_list(season_names):
                    new_seasons[itm] = season_value
        if new_seasons != lazylibrarian.SEASONS:
            logger.debug("SEASONS has changed")
            lazylibrarian.SEASONS = new_seasons.copy()
            json_file = os.path.join(DIRS.DATADIR, 'seasons.json')
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(lazylibrarian.SEASONS, f, ensure_ascii=False)

        # now the config file entries
        for key, itm in CONFIG.config.items():
            if key.lower() in kwargs:
                value = kwargs[key.lower()]
                # validate entries here...
                if value:
                    if key.lower() in ['bok_host']:
                        tokens = ['<', '>', '"', "'", '+', '(', ')']
                    elif (key.lower() in ['user_agent', 'fmt_series'] or key.lower().endswith('_folder')
                          or key.lower().endswith('_file')):
                        tokens = ['<', '&', '>', '=', '"', "'", '+']
                    elif '_pass' in key.lower():
                        tokens = []  # passwords can contain any char as they are not displayed
                    else:
                        tokens = ['<', '&', '>', '=', '"', "'", '+', '(', ')']
                    if not self.validate_param(key.lower(), value, tokens, None):
                        newvalue = unquote_plus(value)
                        for token in tokens:
                            if token in newvalue:
                                newvalue = newvalue.replace(token, '')
                        value = newvalue
                        logger.warning(f"Invalid Token: Key {key} changed to {value}")
                CONFIG.set_from_ui(key, value)
            else:
                if isinstance(itm, ConfigBool) and itm.get_read_count() > 0:
                    itm.set_from_ui(False)  # Set other items to False that we've seen (i.e. are shown)
        CONFIG.ensure_valid_homepage()

        magazines = db.select('SELECT * from magazines')
        if magazines:
            count = 0
            for mag in magazines:
                title = mag['Title']
                reject = mag['Reject']
                regex = mag['Regex']
                genres = mag['Genre']
                datetype = mag['DateType']
                coverpage = check_int(mag['CoverPage'], 1)
                language = mag['Language']
                # seems kwargs parameters from cherrypy are sometimes passed as latin-1,
                # can't see how to configure it, so we need to correct it on accented magazine names
                # eg "Elle Quebec" where we might have e-acute stored as unicode
                # e-acute is \xe9 in latin-1  but  \xc3\xa9 in utf-8
                # otherwise the comparison fails, but sometimes accented characters won't
                # fit latin-1 but fit utf-8 how can we tell ???
                if not isinstance(title, str):
                    try:
                        title = title.encode('latin-1')
                    except UnicodeEncodeError:
                        try:
                            title = title.encode('utf-8')
                        except UnicodeEncodeError:
                            logger.warning(f'Unable to convert title [{repr(title)}]')
                            title = unaccented(title, only_ascii=False)

                new_value_dict = {}
                new_reject = kwargs.get(f'reject_list[{title}]')
                if new_reject != reject:
                    new_value_dict['Reject'] = new_reject
                new_regex = kwargs.get(f'regex[{title}]')
                if new_regex != regex:
                    new_value_dict['Regex'] = new_regex
                new_genres = kwargs.get(f'genre_list[{title}]')
                if new_genres != genres:
                    new_value_dict['Genre'] = new_genres
                new_datetype = kwargs.get(f'datetype[{title}]')
                if new_datetype != datetype:
                    new_value_dict['DateType'] = new_datetype
                new_coverpage = check_int(kwargs.get(f"coverpage[{title}]"), 1)
                if new_coverpage != coverpage:
                    new_value_dict['CoverPage'] = new_coverpage
                new_language = kwargs.get(f'language[{title}]')
                if new_language != language:
                    new_value_dict['Language'] = new_language
                if new_value_dict:
                    count += 1
                    db.upsert("magazines", new_value_dict, {'Title': title})
            if count:
                logger.info(f"Magazine {count} filters updated")
        db.close()

        CONFIG.update_providers_from_ui(kwargs)

        # Convert legacy log settings
        logtype = kwargs.get('log_type', '')
        if logtype == 'Quiet':
            newloglevel = logging.CRITICAL
        elif logtype == 'Normal':
            newloglevel = logging.INFO
        elif logtype == 'Debug':
            newloglevel = logging.DEBUG
        else:  # legacy interface, no log_type
            newloglevel = int(kwargs.get('loglevel', logging.INFO))

        # Enable/disable special loggers based on UI
        specials = []
        for logger in LOGCONFIG.get_special_logger_list():
            shortname = LOGCONFIG.get_short_special_logger_name(logger.name)
            uiname = f'log_{shortname}'
            if uiname in kwargs:
                specials.append(shortname)
        specialcsv = ','.join(specials)
        LOGCONFIG.enable_only_these_special_debuglogs(specialcsv)
        CONFIG.set_csv('LOGSPECIALDEBUG', specialcsv)

        # Store this in CONFIG so it's persisted. OnChange triggers event to activate.
        CONFIG.set_int('LOGLEVEL', newloglevel)
        CONFIG.save_config_and_backup_old(restart_jobs=True)
        if not lazylibrarian.STOPTHREADS:
            check_running_jobs()

        if adminmsg:
            return serve_template(templatename="response.html", prefix="",
                                  title="User Accounts", message=adminmsg, timer=0)

        raise cherrypy.HTTPRedirect("config")

    # SEARCH ############################################################

    @cherrypy.expose
    @require_auth()
    def search(self, searchfor, btnsearch=None):
        self.check_permitted(lazylibrarian.perm_search)
        logger = logging.getLogger('special.searching')
        logger.debug(f"Search {btnsearch}: {searchfor}")

        self.label_thread('SEARCH')
        if not searchfor:
            raise cherrypy.HTTPRedirect("home")

        if not self.validate_param("searchfor", searchfor, ['<', '>', '='], None):
            raise cherrypy.HTTPRedirect("home")

        lazylibrarian.SEARCHING = 1
        if searchfor.lower().startswith('authorid:'):
            self.add_author_id(searchfor[9:])
            return None
        if searchfor.lower().startswith('bookid:'):
            self.add_book(searchfor[7:])
            return None
        authid_key = 'AuthorID'
        bookid_key = 'BookID'
        for itm in api_sources:
            if CONFIG['BOOK_API'] == itm[0]:
                authid_key = itm[1]
                bookid_key = itm[2]
                break

        db = database.DBConnection()
        try:
            authorids = db.select(f"SELECT {authid_key} as AuthorID from authors where status != 'Loading'")
            loadingauthorids = db.select(f"SELECT {authid_key} as AuthorID from authors where status = 'Loading'")
            booksearch = db.select(f"SELECT Status,AudioStatus,{bookid_key} as BookID from books")
        finally:
            db.close()

        authorlist = []
        for itm in authorids:
            if itm['AuthorID']:
                authorlist.append(itm['AuthorID'])
        authorlist = list(set(authorlist))
        loadlist = []
        for itm in loadingauthorids:
            if itm['AuthorID']:
                loadlist.append(itm['AuthorID'])
        loadlist = list(set(loadlist))
        booklist = []
        for itm in booksearch:
            if itm['BookID']:
                booklist.append(itm['BookID'])
        booklist = list(set(booklist))
        # we don't know if searchfor is an author, book or isbn
        searchresults = search_for(searchfor, CONFIG['BOOK_API'])
        sortedlist = sorted(searchresults, key=lambda x: (x['highest_fuzz'], x['bookrate_count']),
                            reverse=True)
        lazylibrarian.SEARCHING = 0
        return serve_template(templatename="searchresults.html", title='Search Results: "' + searchfor + '"',
                              searchresults=sortedlist, authorlist=authorlist, loadlist=loadlist,
                              booklist=booklist, booksearch=booksearch)

    # AUTHOR ############################################################

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_authors_ajax(self, action=None, **args):
        self.check_permitted(lazylibrarian.perm_status)
        logger = logging.getLogger(__name__)
        for arg in ['author_table_length', 'ignored']:
            args.pop(arg, None)
        passed = 0
        failed = 0
        if action:
            db = database.DBConnection()
            try:
                for authorid in args:
                    check = db.match("SELECT AuthorName from authors WHERE AuthorID=?", (authorid,))
                    if not check:
                        logger.warning(f'Unable to set Status to "{action}" for "{authorid}"')
                        failed += 1
                    elif action in ["Active", "Wanted", "Paused", "Ignored"]:
                        db.upsert("authors", {'Status': action}, {'AuthorID': authorid})
                        logger.info(f'Status set to "{action}" for "{check["AuthorName"]}"')
                        passed += 1
                    elif action == "Delete":
                        logger.info(f"Deleting author and media files: {check['AuthorName']}")
                        books = db.select("SELECT BookFile,AudioFile from books WHERE AuthorID=?", (authorid,))
                        for book in books:
                            for location in [book['BookFile'], book['AudioFile']]:
                                if location and path_exists(location):
                                    try:
                                        foldername = os.path.dirname(location)
                                        logger.debug(f"Deleting folder: {foldername}")
                                        rmtree(foldername, ignore_errors=True)
                                    except Exception as e:
                                        logger.warning(f'rmtree failed on {location}, {type(e).__name__} {str(e)}')

                        delete_empty_folders(CONFIG['EBOOK_DIR'])
                        if CONFIG['MAG_RELATIVE']:
                            audio_folder = os.path.join(CONFIG['EBOOK_DIR'], CONFIG['AUDIO_DIR'])
                        else:
                            audio_folder = CONFIG['AUDIO_DIR']
                        delete_empty_folders(audio_folder)

                        db.action('DELETE from authors WHERE AuthorID=?', (authorid,))
                        passed += 1
                    elif action == "Remove":
                        logger.info(f"Removing author: {check['AuthorName']}")
                        db.action('DELETE from authors WHERE AuthorID=?', (authorid,))
                        passed += 1
                    elif action == 'Subscribe':
                        cookie = cherrypy.request.cookie
                        if cookie and 'll_uid' in list(cookie.keys()):
                            userid = cookie['ll_uid'].value
                            res = db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                                           (userid, 'author', authorid))
                            if res:
                                logger.debug(f"User {userid} is already subscribed to {authorid}")
                                failed += 1
                            else:
                                db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                                          (userid, 'author', authorid))
                                logger.debug(f"Subscribe {userid} to author {authorid}")
                                passed += 1
                    elif action == 'Unsubscribe':
                        cookie = cherrypy.request.cookie
                        if cookie and 'll_uid' in list(cookie.keys()):
                            userid = cookie['ll_uid'].value
                            db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                      (userid, 'author', authorid))
                            res = db.select('SELECT bookid from books where authorid=?', (authorid, ))
                            for iss in res:
                                db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                          (userid, 'ebook', iss['bookid']))
                            logger.debug(f"Unsubscribe {userid} author {authorid}")
                            passed += 1
            finally:
                db.close()

        # Return JSON response instead of redirect
        total = passed + failed
        summary = f"Mark Authors '{action}' completed."
        if total > 0:
            summary += f" {passed} successful"
            if failed > 0:
                summary += f", {failed} failed"
            summary += f" out of {total} total items."
        else:
            summary += " No items were processed."
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'summary': summary
        }

    @cherrypy.expose
    @require_auth()
    def author_page(self, authorid, book_lang=None, library='eBook', ignored=False, **args):
        global lastauthor
        self.check_permitted(lazylibrarian.perm_ebook + lazylibrarian.perm_audio)
        db = database.DBConnection()
        user = 0
        email = ''
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            user = cookie['ll_uid'].value
            res = db.match('SELECT SendTo from users where UserID=?', (user,))
            if res and res['SendTo']:
                email = res['SendTo']

        author = dict(db.match("SELECT * from authors WHERE AuthorID=?", (authorid,)))
        if not author:
            author = dict(db.match("SELECT * from authors WHERE ol_id=? or gr_id=? or hc_id=?",
                                   (authorid, authorid, authorid,)))
        if ignored:
            languages = db.select(
                "SELECT DISTINCT BookLang from books WHERE AuthorID=? AND Status ='Ignored'",
                (authorid,))
        else:
            languages = db.select(
                "SELECT DISTINCT BookLang from books WHERE AuthorID=? AND Status !='Ignored'",
                (authorid,))
        db.close()

        types = []
        if CONFIG.get_bool('EBOOK_TAB'):
            types.append('eBook')
        if CONFIG.get_bool('AUDIO_TAB'):
            types.append('AudioBook')
        if types and library not in types:
            library = types[0]
        if not types:
            library = None
        if not author:
            raise cherrypy.HTTPRedirect("authors")

        # if we've changed author, reset to first page of new authors books
        if authorid == lastauthor:
            firstpage = 'false'
        else:
            lastauthor = authorid
            firstpage = 'true'

        authorname = author['AuthorName']
        if not authorname:  # still loading?
            raise cherrypy.HTTPRedirect("authors")

        author['AuthorBorn'] = date_format(author['AuthorBorn'], CONFIG['AUTHOR_DATE_FORMAT'],
                                           context=authorname, datelang=CONFIG['DATE_LANG'])
        author['AuthorDeath'] = date_format(author['AuthorDeath'], CONFIG['AUTHOR_DATE_FORMAT'],
                                            context=authorname, datelang=CONFIG['DATE_LANG'])

        return serve_template(
            templatename="author.html", title=authorname, author=author,
            languages=languages, booklang=book_lang, types=types, library=library, ignored=ignored,
            showseries=CONFIG.get_int('SERIES_TAB'), firstpage=firstpage, user=user, email=email,
            book_filter=args.get('book_filter', ''))

    @cherrypy.expose
    @require_auth()
    def set_author(self, authorid, status):
        self.check_permitted(lazylibrarian.perm_status)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authorsearch = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
        if authorsearch:
            author_name = authorsearch['AuthorName']
            logger.info(f"{status} author: {author_name}")
            control_value_dict = {'AuthorID': authorid}
            new_value_dict = {'Status': status}
            db.upsert("authors", new_value_dict, control_value_dict)
            logger.debug(
                f'AuthorID [{authorid}]-[{author_name}] {status} - redirecting to Author home page')
            db.close()
            raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")
        logger.debug(f'pause_author Invalid authorid [{authorid}]')
        db.close()
        raise cherrypy.HTTPError(404, f"AuthorID {authorid} not found")

    @cherrypy.expose
    @require_auth()
    def pause_author(self, authorid):
        self.set_author(authorid, 'Paused')

    @cherrypy.expose
    @require_auth()
    def want_author(self, authorid):
        self.set_author(authorid, 'Wanted')

    @cherrypy.expose
    @require_auth()
    def resume_author(self, authorid):
        self.set_author(authorid, 'Active')

    @cherrypy.expose
    @require_auth()
    def ignore_author(self, authorid):
        self.set_author(authorid, 'Ignored')

    @cherrypy.expose
    @require_auth()
    def remove_author(self, authorid):
        self.check_permitted(lazylibrarian.perm_edit)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authorsearch = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
        if authorsearch:  # to stop error if try to remove an author while they are still loading
            author_name = authorsearch['AuthorName']
            logger.info(f"Removing all references to author: {author_name}")
            db.action('DELETE from authors WHERE AuthorID=?', (authorid,))
            # if the author was the only remaining contributor to a series, remove the series
            orphans = db.select('select seriesid from series except select seriesid from seriesauthors')
            for orphan in orphans:
                db.action('DELETE from series where seriesid=?', (orphan[0],))
        db.close()
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def refresh_author(self, authorid):
        self.check_permitted(lazylibrarian.perm_force)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authorsearch = db.match('SELECT * from authors WHERE AuthorID=?', (authorid,))
        db.close()
        if authorsearch:  # to stop error if try to refresh an author while they are still loading
            authorname = authorsearch['AuthorName']
            if not authorname or 'unknown' in authorname.lower() or 'anonymous' in authorname.lower():
                authorname = None
            threading.Thread(target=add_author_to_db, name=f"REFRESHAUTHOR_{authorid}",
                             args=[authorname, True, authorid, True,
                                   f"WebServer refresh_author {authorid}"]).start()
            raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")
        logger.debug(f'refresh_author Invalid authorid [{authorid}]')
        raise cherrypy.HTTPError(404, f"AuthorID {authorid} not found")

    @cherrypy.expose
    @require_auth()
    def follow_author(self, authorid):
        # empty GRfollow is not-yet-used, zero means manually unfollowed so sync leaves it alone
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authorsearch = db.match('SELECT AuthorName, GRfollow from authors WHERE AuthorID=?', (authorid,))
        if authorsearch:
            if authorsearch['GRfollow'] and authorsearch['GRfollow'] != '0':
                logger.warning(f"Already Following {authorsearch['AuthorName']}")
            else:
                msg = grsync.grfollow(authorid, True)
                if msg.startswith('Unable'):
                    logger.warning(msg)
                else:
                    logger.info(msg)
                    followid = msg.split("followid=")[1]
                    db.action("UPDATE authors SET GRfollow=? WHERE AuthorID=?", (followid, authorid))
        else:
            msg = f"Invalid authorid to follow ({authorid})"
            logger.error(msg)
            raise cherrypy.HTTPError(404, msg)

        db.close()
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    def unfollow_author(self, authorid):
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authorsearch = db.match('SELECT AuthorName, GRfollow from authors WHERE AuthorID=?', (authorid,))
        if authorsearch:
            if not authorsearch['GRfollow'] or authorsearch['GRfollow'] == '0':
                logger.warning(f"Not Following {authorsearch['AuthorName']}")
            else:
                msg = grsync.grfollow(authorid, False)
                if msg.startswith('Unable'):
                    logger.warning(msg)
                else:
                    db.action("UPDATE authors SET GRfollow='0' WHERE AuthorID=?", (authorid,))
                    logger.info(msg)
        else:
            msg = f"Invalid authorid to unfollow ({authorid})"
            logger.error(msg)
            raise cherrypy.HTTPError(404, msg)
        db.close()
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    def library_scan_author(self, authorid, **kwargs):
        self.check_permitted(lazylibrarian.perm_force)
        logger = logging.getLogger(__name__)
        fuzzlogger = logging.getLogger('special.fuzz')
        db = database.DBConnection()
        authorsearch = db.match('SELECT AuthorName from authors WHERE AuthorID=?', (authorid,))
        if authorsearch:  # to stop error if try to refresh an author while they are still loading
            author_name = authorsearch['AuthorName']
            types = []
            if CONFIG.get_bool('EBOOK_TAB'):
                types.append('eBook')
            if CONFIG.get_bool('AUDIO_TAB'):
                types.append('AudioBook')
            if not types:
                db.close()
                raise cherrypy.HTTPRedirect('authors')
            library = types[0]
            if 'library' in kwargs and kwargs['library'] in types:
                library = kwargs['library']

            if library == 'AudioBook':
                authordir = safe_unicode(os.path.join(get_directory('AudioBook'), author_name))
            else:  # if library == 'eBook':
                authordir = safe_unicode(os.path.join(get_directory('eBook'), author_name))
            if not path_isdir(authordir):
                logger.debug(f"Assumed authordir [{authordir}] not found")
                # books might not be in exact same authorname folder due to capitalisation
                # or accent stripping etc.
                # eg Calibre puts books into folder "Eric Van Lustbader", but
                # goodreads told lazylibrarian he's "Eric van Lustbader", note the lowercase 'v'
                # or calibre calls "Neil deGrasse Tyson" "Neil DeGrasse Tyson" with a capital 'D'
                # so try a fuzzy match...
                libdir = os.path.dirname(authordir)
                matchname, exists = get_preferred_author(author_name)
                if exists:
                    author_name = matchname
                    if exists != authorid:
                        logger.warning(f"{authorid}:{author_name} matches preferred id {exists}:{matchname}")
                    authorid = exists
                logger.debug(f"Scanning {libdir} for preferred name {matchname}")
                matchname = unaccented(matchname).lower()
                for itm in listdir(libdir):
                    match = fuzz.ratio(format_author_name(unaccented(itm),
                                                          get_list(CONFIG.get_csv('NAME_POSTFIX'))).lower(), matchname)
                    if match >= CONFIG.get_int('NAME_RATIO'):
                        authordir = os.path.join(libdir, itm)
                        fuzzlogger.debug(f"Fuzzy match folder {round(match, 2)}% {itm} for {author_name}")
                        # TODO Add this name variant as an aka if not already there?
                        break

            if not path_isdir(authordir):
                logger.debug(f"[{authordir}] still not found")
                # if still not found, see if we have a book by them, and what directory it's in
                if library == 'AudioBook':
                    sourcefile = 'AudioFile'
                else:
                    sourcefile = 'BookFile'
                cmd = f"SELECT {sourcefile} from books where AuthorID=? and {sourcefile} <> ''"
                anybook = db.match(cmd, (authorid,))
                if anybook:
                    logger.debug(f"Found {sourcefile} {anybook[sourcefile]} for {authorid}:{author_name}")
                    authordir = safe_unicode(os.path.dirname(os.path.dirname(anybook[sourcefile])))
                else:
                    logger.debug(f"No {sourcefile} in library for {authorid}:{author_name}")

            if path_isdir(authordir):
                remv = CONFIG.get_bool('FULL_SCAN')
                logger.debug(f"Using [{authordir}] for {authorid}:{author_name}")
                try:
                    threading.Thread(target=library_scan, name=f'AUTHOR_SCAN_{authorid}',
                                     args=[authordir, library, authorid, remv]).start()
                except Exception as e:
                    logger.error(f'Unable to complete the scan: {type(e).__name__} {str(e)}')
            else:
                # maybe we don't have any of their books
                logger.warning(f'Unable to find author directory: {authordir}')
            db.close()
            raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}&library={library}")
        logger.debug(f'ScanAuthor Invalid authorid [{authorid}]')
        db.close()
        raise cherrypy.HTTPError(404, f"AuthorID {authorid} not found")

    @cherrypy.expose
    @require_auth()
    def add_author(self, authorname):
        self.check_permitted(lazylibrarian.perm_search)
        threading.Thread(target=add_author_name_to_db, name='ADDAUTHOR',
                         args=[authorname, False, True, f'WebServer add_author {authorname}']).start()
        time.sleep(2)  # so we get some data before going to authorpage
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def add_author_id(self, authorid, authorname=''):
        self.check_permitted(lazylibrarian.perm_search)
        threading.Thread(target=add_author_to_db, name='ADDAUTHORID',
                         args=[authorname, False, authorid, True, f'WebServer add_author_id {authorid}']).start()
        time.sleep(2)  # so we get some data before going to authorpage
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    def toggle_auth(self):
        if lazylibrarian.IGNORED_AUTHORS:  # show ignored/paused ones, or active/wanted ones
            lazylibrarian.IGNORED_AUTHORS = False
        else:
            lazylibrarian.IGNORED_AUTHORS = True
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def toggle_primary(self, page=None, authorid=None):
        if lazylibrarian.PRIMARY_AUTHORS:  # show primary ones, or all
            lazylibrarian.PRIMARY_AUTHORS = False
        else:
            lazylibrarian.PRIMARY_AUTHORS = True
        if not page:
            page = 'home'
        if authorid:
            redirect = f"{page}?authorid={authorid}"
        else:
            redirect = page
        raise cherrypy.HTTPRedirect(redirect)

    @cherrypy.expose
    @require_auth()
    def toggle_my_auth(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_myauthors
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def toggle_my_series(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_myseries
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("series")

    @cherrypy.expose
    @require_auth()
    def toggle_my_feeds(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_myfeeds
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def toggle_my_a_feeds(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_myafeeds
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("audio")

    @cherrypy.expose
    @require_auth()
    def toggle_my_mags(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_mymags
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("magazines")

    @cherrypy.expose
    @require_auth()
    def toggle_my_comics(self):
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        userprefs = userprefs ^ lazylibrarian.pref_mycomics
        cherrypy.response.cookie['ll_prefs'] = userprefs
        raise cherrypy.HTTPRedirect("comics")

    # BOOKS #############################################################

    @cherrypy.expose
    @require_auth()
    def booksearch(self, author=None, title=None, bookid=None, action=''):
        self.check_permitted(lazylibrarian.perm_search)
        self.label_thread('BOOKSEARCH')
        if '_title' in action:
            searchterm = title
        elif '_author' in action:
            searchterm = author
        else:  # if '_full' in action: or legacy interface
            searchterm = f'{author} {title}'
            searchterm = searchterm.strip()

        if action == 'e_full':
            cat = 'book'
        elif action == 'a_full':
            cat = 'audio'
        elif action:
            cat = 'general'
        else:  # legacy interface
            cat = 'book'

        results = search_item(searchterm, bookid, cat)
        library = 'eBook'
        if action.startswith('a_'):
            library = 'AudioBook'
        return serve_template(templatename="manualsearch.html", title=library + ' Search Results: "' +
                              searchterm + '"', bookid=bookid, results=results, library=library)

    @cherrypy.expose
    @require_auth()
    def count_providers(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        count = CONFIG.total_active_providers()
        return f"Searching {count} providers, please wait..."

    @cherrypy.expose
    @require_auth()
    def snatch_book(self, bookid=None, mode=None, provider=None, url=None, size=None, library=None, title=''):
        self.check_permitted(lazylibrarian.perm_download)
        logger = logging.getLogger(__name__)
        logger.debug(f"snatch {library} bookid {bookid} mode={mode} from {provider} url=[{url}] {title}")
        db = database.DBConnection()
        bookdata = db.match('SELECT AuthorID, BookName from books WHERE BookID=?', (bookid,))
        if bookdata:
            size_temp = check_int(size, 1000)  # Need to cater for when this is NONE (Issue 35)
            size = round(float(size_temp) / 1048576, 2)
            control_value_dict = {"NZBurl": url}
            new_value_dict = {
                "NZBprov": provider,
                "BookID": bookid,
                "NZBdate": now(),  # when we asked for it
                "NZBsize": size,
                "NZBtitle": bookdata["BookName"],
                "NZBmode": mode,
                "AuxInfo": library,
                "Status": "Snatched"
            }
            db.upsert("wanted", new_value_dict, control_value_dict)
            author_id = bookdata["AuthorID"]
            dl_title = bookdata["BookName"]
            if provider in ['soulseek', 'annas']:
                dl_title = title
            if mode == 'direct':
                snatch, res = direct_dl_method(bookid, dl_title, url, library, provider)
            elif mode in ["torznab", "torrent", "magnet"]:
                snatch, res = tor_dl_method(bookid, bookdata["BookName"], url, library, provider=provider)
            elif mode == 'nzb':
                snatch, res = nzb_dl_method(bookid, bookdata["BookName"], url, library)
            elif mode == 'irc':
                if title:
                    snatch, res = irc_dl_method(bookid, title, url, library, provider)
                else:
                    snatch, res = irc_dl_method(bookid, bookdata["BookName"], url, library, provider)
            else:
                res = f'Unhandled NZBmode [{mode}] for {url}'
                logger.error(res)
                snatch = False
            if snatch:
                logger.info(f'Requested {library} {bookdata["BookName"]} from {provider}')
                custom_notify_snatch(f"{bookid} {library}")
                notify_snatch(
                    f"{unaccented(bookdata['BookName'], only_ascii=False)} from "
                    f"{CONFIG.disp_name(provider)} at {now()}")
                schedule_job(action=SchedulerCommand.START, target='PostProcessor')
            else:
                db.action("UPDATE wanted SET status='Failed',DLResult=? WHERE NZBurl=?", (res, url))
            db.close()
            raise cherrypy.HTTPRedirect(f"author_page?authorid={author_id}&library={library}")
        logger.debug(f'snatch_book Invalid bookid [{bookid}]')
        db.close()
        raise cherrypy.HTTPError(404, f"BookID {bookid} not found")

    @cherrypy.expose
    @require_auth()
    def audio(self, booklang=None, book_filter=''):
        self.check_permitted(lazylibrarian.perm_audio)
        user = 0
        email = ''
        db = database.DBConnection()
        try:
            cookie = cherrypy.request.cookie
            if cookie and 'll_uid' in list(cookie.keys()):
                user = cookie['ll_uid'].value
                res = db.match('SELECT SendTo from users where UserID=?', (user,))
                if res and res['SendTo']:
                    email = res['SendTo']
            if not booklang or booklang == 'None':
                booklang = None
            languages = db.select(
                "SELECT DISTINCT BookLang from books WHERE AUDIOSTATUS !='Skipped' AND AUDIOSTATUS !='Ignored'")
        finally:
            db.close()
        return serve_template(templatename="audio.html", title='AudioBooks', books=[],
                              languages=languages, booklang=booklang, user=user, email=email, book_filter=book_filter)

    @cherrypy.expose
    @require_auth()
    def books(self, booklang=None, book_filter=''):
        self.check_permitted(lazylibrarian.perm_ebook)
        user = 0
        email = ''
        db = database.DBConnection()
        cookie = cherrypy.request.cookie
        try:
            if cookie and 'll_uid' in list(cookie.keys()):
                user = cookie['ll_uid'].value
                res = db.match('SELECT SendTo from users where UserID=?', (user,))
                if res and res['SendTo']:
                    email = res['SendTo']
            if not booklang or booklang == 'None':
                booklang = None
            languages = db.select("SELECT DISTINCT BookLang from books WHERE STATUS !='Skipped' AND STATUS !='Ignored'")
        finally:
            db.close()
        return serve_template(templatename="books.html", title='eBooks', books=[],
                              languages=languages, booklang=booklang, user=user, email=email, book_filter=book_filter)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_books(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        rows = []
        filtered = []
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        db = database.DBConnection()
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            to_read = set()
            have_read = set()
            reading = set()
            abandoned = set()
            flag_to = 0
            flag_have = 0
            userid = None
            userprefs = 0
            if not CONFIG.get_bool('USER_ACCOUNTS'):
                perm = lazylibrarian.perm_admin
            else:
                perm = 0
                cookie = cherrypy.request.cookie
                if cookie and 'll_prefs' in list(cookie.keys()):
                    userprefs = check_int(cookie['ll_prefs'].value, 0)
                if cookie and 'll_uid' in list(cookie.keys()):
                    userid = cookie['ll_uid'].value
                    cmd = "SELECT UserName,Perms from users where UserID=?"
                    res = db.match(cmd, (userid,))
                    if res:
                        perm = check_int(res['Perms'], 0)
                        to_read = get_readinglist("ToRead", userid)
                        have_read = get_readinglist("HaveRead", userid)
                        reading = get_readinglist("Reading", userid)
                        abandoned = get_readinglist("Abandoned", userid)
                        serversidelogger.debug(
                            f"get_books userid {cookie['ll_uid'].value} read {len(to_read)},{len(have_read)},"
                            f"{len(reading)},{len(abandoned)}")

            cmd = ("SELECT bookimg,authorname,bookname,bookrate,bookdate,books.status,books.bookid,booklang, "
                   "booksub,booklink,workpage,bookauthors.authorid,seriesdisplay,booklibrary,audiostatus,audiolibrary, "
                   "group_concat(series.seriesid || '~' || series.seriesname || ' #' || member.seriesnum, '^') "
                   "as series, bookgenre,bookadded,scanresult,lt_workid, "
                   "group_concat(series.seriesname || ' #' || member.seriesnum, '; ') as altsub "
                   "FROM books,authors,bookauthors "
                   "LEFT OUTER JOIN member ON (bookauthors.BookID = member.BookID and bookauthors.bookid=books.bookid) "
                   "LEFT OUTER JOIN series ON (member.SeriesID = series.SeriesID) "
                   "WHERE bookauthors.authorid=authors.authorid and bookauthors.bookid=books.bookid ")
            serversidelogger.debug(
                f"ToRead {len(to_read)} Read {len(have_read)} Reading {len(reading)} Abandoned {len(abandoned)}")
            types = []
            if CONFIG.get_bool('EBOOK_TAB'):
                types.append('eBook')
            if CONFIG.get_bool('AUDIO_TAB'):
                types.append('AudioBook')
            if types:
                library = types[0]
                if 'library' in kwargs and kwargs['library'] in types:
                    library = kwargs['library']
            else:
                library = None

            status_type = 'books.status'
            if library == 'AudioBook':
                status_type = 'audiostatus'
            args = []

            if kwargs['source'] == "Manage":
                if kwargs['whichStatus'] == 'ToRead':
                    cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in to_read) + ")"
                elif kwargs['whichStatus'] == 'Read':
                    cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in have_read) + ")"
                elif kwargs['whichStatus'] == 'Reading':
                    cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in reading) + ")"
                elif kwargs['whichStatus'] == 'Abandoned':
                    cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in abandoned) + ")"
                elif kwargs['whichStatus'] != 'All':
                    cmd += " and " + status_type + "='" + kwargs['whichStatus'] + "'"

            elif kwargs['source'] == "Books":
                cmd += " and books.STATUS !='Skipped' AND books.STATUS !='Ignored'"
            elif kwargs['source'] == "Audio":
                cmd += " and AUDIOSTATUS !='Skipped' AND AUDIOSTATUS !='Ignored'"
            elif kwargs['source'] == "Author":
                cmd += " and bookauthors.AuthorID=?"
                args.append(kwargs['AuthorID'])
                if 'ignored' in kwargs and kwargs['ignored'] == "True":
                    cmd += f" and {status_type}='Ignored'"
                else:
                    cmd += f" and {status_type} != 'Ignored'"

            if (kwargs['source'] in ["Books", "Author", "Audio"] and 'booklang' in kwargs and
                    kwargs['booklang'] != '' and kwargs['booklang'] != 'None'):
                # for these we need to check and filter on BookLang if set
                cmd += " and BOOKLANG=?"
                args.append(kwargs['booklang'])

            if kwargs['source'] in ["Books", "Audio"] and userid and (userprefs & lazylibrarian.pref_myfeeds or
                                                                      userprefs & lazylibrarian.pref_myafeeds):
                serversidelogger.debug("Getting user booklist")
                mybooks = []
                res = db.select("SELECT WantID from subscribers WHERE Type='author' and UserID=?", (userid,))
                serversidelogger.debug(f"User subscribes to {len(res)} authors")
                for authorid in res:
                    bookids = db.select('SELECT BookID from bookauthors WHERE AuthorID=?', (authorid['WantID'],))
                    for bookid in bookids:
                        mybooks.append(bookid['BookID'])

                res = db.select("SELECT WantID from subscribers WHERE Type='series' and UserID=?", (userid,))
                serversidelogger.debug(f"User subscribes to {len(res)} series")
                for series in res:
                    sel = 'SELECT BookID from member,series WHERE series.seriesid=?'
                    sel += ' and member.seriesid=series.seriesid'
                    bookids = db.select(sel, (series['WantID'],))
                    for bookid in bookids:
                        mybooks.append(bookid['BookID'])

                res = db.select("SELECT WantID from subscribers WHERE Type='feed' and UserID=?", (userid,))
                serversidelogger.debug(f"User subscribes to {len(res)} feeds")
                for feed in res:
                    sel = "SELECT BookID from books WHERE instr(Requester, '?') > 0"
                    sel += "  or instr(AudioRequester, '?') > 0"
                    bookids = db.select(sel, (feed['WantID'], feed['WantID']))
                    for bookid in bookids:
                        mybooks.append(bookid['BookID'])

                mybooks = set(mybooks)
                serversidelogger.debug(f"User booklist length {len(mybooks)}")
                cmd += " and books.bookID in (" + ", ".join(f"'{w}'" for w in mybooks) + ")"

            if kwargs['source'] in ["Author", "Books", "Audio"] and lazylibrarian.PRIMARY_AUTHORS:
                # only show book for primary author
                cmd += " and books.bookid in (SELECT bookid FROM bookauthors where bookauthors.authorid=authors.authorid "
                cmd += f"and books.bookid=bookauthors.bookid and role={ROLE['PRIMARY']})"

            cmd += (" GROUP BY bookimg, authorname, bookname, bookrate, bookdate, books.status, books.bookid, "
                    "booklang, booksub, booklink, workpage, bookauthors.authorid, booklibrary, audiostatus, "
                    "audiolibrary, bookgenre, bookadded, scanresult, lt_workid")

            serversidelogger.debug(f"get_books {cmd}: {str(args)}")
            rowlist = db.select(cmd, tuple(args))
            serversidelogger.debug(f"get_books selected {len(rowlist)}")

            if library is None:
                rowlist = []
            # At his point we want to sort and filter _before_ adding the html as it's much quicker
            # turn the sqlite rowlist into a list of lists
            if len(rowlist):
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    entry = list(row)
                    for pos in [5, 14, 16]:
                        if entry[pos] is None:
                            entry[pos] = ""
                    if CONFIG.get_bool('SORT_SURNAME'):
                        entry[1] = surname_first(entry[1], postfixes=get_list(CONFIG.get_csv('NAME_POSTFIX')))
                    if CONFIG.get_bool('SORT_DEFINITE'):
                        entry[2] = sort_definite(entry[2], articles=get_list(CONFIG.get_csv('NAME_DEFINITE')))
                    rows.append(entry)  # add each rowlist to the masterlist
                serversidelogger.debug("get_books surname/definite completed")

                if sSearch:
                    serversidelogger.debug(f"filter [{sSearch}]")
                    if library is not None:
                        search_fields = ['AuthorName', 'BookName', 'BookDate', 'Status', 'BookID',
                                         'BookLang', 'BookSub', 'AuthorID', 'BookGenre',
                                         'ScanResult']
                        if library == 'AudioBook':
                            search_fields[3] = 'AudioStatus'

                        filtered = []
                        for row in rowlist:
                            _dict = dict(row)
                            for key in search_fields:
                                if _dict[key] and sSearch.lower() in _dict[key].lower():
                                    filtered.append(list(row))
                                    break
                    else:
                        filtered = [x for x in rows if sSearch.lower() in str(x).lower()]
                else:
                    filtered = rows

                # table headers and column headers do not match at this point
                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")
                if sortcolumn < 4:  # author, title
                    sortcolumn -= 1
                elif sortcolumn == 4:  # series
                    sortcolumn = -1
                elif sortcolumn == 8:  # status
                    if status_type == 'audiostatus':
                        sortcolumn = 14
                    else:
                        sortcolumn = 5
                elif sortcolumn == 7:  # added or listed
                    if kwargs['source'] == "Manage":
                        sortcolumn = 18
                    else:
                        if status_type == 'audiostatus':
                            sortcolumn = 15
                        else:
                            sortcolumn = 13
                else:  # rating, date
                    sortcolumn -= 2

                serversidelogger.debug(f"final sortcolumn {sortcolumn}")

                if sortcolumn in [12, 13, 15, 18]:  # series, dates
                    self.natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                elif sortcolumn in [2]:  # title
                    filtered.sort(key=lambda y: y[sortcolumn].lower() if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

                # now add html to the ones we want to display
                data = []  # the masterlist to be filled with the html data
                for row in rows:
                    title = row[2]
                    if not title:
                        continue
                    worklink = ''
                    sitelink = ''
                    if CONFIG.get_bool('RATESTARS'):
                        bookrate = int(round(check_float(row[3], 0.0)))
                        if bookrate > 5:
                            bookrate = 5
                    else:
                        bookrate = row[3]

                    if row[20]:  # is there a librarything workid
                        worklink = '<a href="' + CONFIG['LT_URL'] + '/' + 'work/' + \
                                   row[20] + '"><small><i>LibraryThing</i></small></a>'
                    elif row[10]:  # is there a workpage link
                        worklink = '<a href="' + row[10] + '" ><small><i>LibraryThing</i></small></a>'
                    else:
                        row[10] = ''
                        row[20] = ''

                    editpage = '<a href="edit_book?bookid=' + row[6] + '&library=' + library + \
                        '"><small><i>Manual</i></a>'

                    if not row[9]:
                        row[9] = ''
                    elif row[9].startswith('/works/OL'):
                        ref = CONFIG['OL_URL'] + row[9]
                        sitelink = f'<a href="{ref}"><small><i>OpenLibrary</i></small></a>'

                    elif 'goodreads' in row[9]:
                        sitelink = f'<a href="{row[9]}"><small><i>GoodReads</i></small></a>'
                    elif 'hardcover' in row[9]:
                        sitelink = f'<a href="{row[9]}"><small><i>HardCover</i></small></a>'
                    elif 'books.google.com' in row[9] or 'market.android.com' in row[9]:
                        sitelink = f'<a href="{row[9]}"><small><i>GoogleBooks</i></small></a>'

                    if row[8] and ' #' not in row[8] and row[8] != "None":  # is there a subtitle that's not series info
                        title = f'{title}<br><small><i>{row[8]}</i></small>'
                    # elif row[20]:  # series info
                    #     title = '%s<br><small><i>(%s)</i></small>' % (title, row[20])
                    title = title + '<br>' + sitelink + ' ' + worklink
                    bookgenre = row[17]

                    if perm & lazylibrarian.perm_edit:
                        title = title + ' ' + editpage

                    if CONFIG.get_bool('SHOW_GENRES') and bookgenre and bookgenre != 'Unknown':
                        arr = bookgenre.split(',')
                        genres = ''
                        for a in arr:
                            if kwargs['source'] == "Audio":
                                genres = genres + ' <a href=\'audio?book_filter=' + a.strip() + '\'">' + \
                                         a.strip() + '</a>'
                            elif kwargs['source'] == "Books":
                                genres = genres + ' <a href=\'books?book_filter=' + a.strip() + '\'">' + \
                                         a.strip() + '</a>'
                            elif kwargs['source'] in ["Author", "Manage"]:
                                genres = genres + ' <a href=\'author_page?authorid=' + row[11] + '&book_filter=' + \
                                         a.strip() + '\'">' + a.strip() + '</a>'
                            else:
                                genres + genres + ' ' + a.strip()
                        genres = genres.strip()
                        if genres:
                            title += ' [' + genres + ']'

                    if row[6] in to_read:
                        flag = '&nbsp;<i class="far fa-bookmark"></i>'
                        flag_to += 1
                    elif row[6] in have_read:
                        flag = '&nbsp;<i class="fas fa-bookmark"></i>'
                        flag_have += 1
                    elif row[6] in reading:
                        flag = '&nbsp;<i class="fas fa-play-circle"></i>'
                    elif row[6] in abandoned:
                        flag = '&nbsp;<i class="fas fa-ban"></i>'
                    else:
                        flag = ''

                    if status_type == 'audiostatus' and kwargs['source'] == 'Audio':
                        row[5] = row[14]
                        row[13] = row[15]

                    # Need to pass bookid and status twice for legacy as datatables modifies first one
                    thisrow = [row[6], row[0], row[1], title, row[12], bookrate,
                               date_format(row[4], context=row[6], datelang=CONFIG['DATE_LANG']),
                               row[5], row[11], row[6],
                               date_format(row[13], CONFIG['DATE_FORMAT'], context=row[6],
                                           datelang=CONFIG['DATE_LANG']),
                               row[5], row[16], flag]

                    if kwargs['source'] == "Manage":
                        cmd = "SELECT Time,Interval,Count from failedsearch WHERE Bookid=? AND Library='eBook'"
                        searches = db.match(cmd, (row[6],))
                        if searches:
                            thisrow.append(f"{searches['Count']}/{searches['Interval']}")
                            try:
                                thisrow.append(time.strftime("%d %b %Y", time.localtime(float(searches['Time']))))
                            except (ValueError, TypeError):
                                thisrow.append('')
                        else:
                            thisrow.append('0')
                            thisrow.append('')
                    elif kwargs['source'] == 'Author':
                        thisrow.append(row[14])
                        thisrow.append(date_format(row[15], CONFIG['DATE_FORMAT'], context=row[6],
                                                   datelang=CONFIG['DATE_LANG']))

                    thisrow.append(row[18])
                    thisrow.append(row[19])
                    data.append(thisrow)

                rows = data

            serversidelogger.debug(
                f"get_books {kwargs['source']} returning {displaystart} to {displaystart + displaylength}, "
                f"flagged {flag_to},{flag_have}")
            serversidelogger.debug(f"get_books filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")

        except Exception:
            logger.error(f'Unhandled exception in get_books: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  }
        if kwargs['source'] == 'Author':
            status = db.match("SELECT Status from authors WHERE authorid=?", (kwargs['AuthorID'],))
            mydict['loading'] = status['Status'] == 'Loading'
        elif kwargs['source'] == 'Books':
            mydict['loading'] = lazylibrarian.EBOOK_UPDATE
        elif kwargs['source'] == 'Audio':
            mydict['loading'] = lazylibrarian.AUDIO_UPDATE
        db.close()
        serversidelogger.debug(str(mydict))
        return mydict

    @staticmethod
    def natural_sort(lst, key=lambda s: s, reverse=False):
        """
        Sort the list into natural alphanumeric order.
        """

        def convert(text):
            return int(text) if text and text.isdigit() else text

        def get_alphanum_key_func(skey):
            return lambda s: [convert(c) for c in re.split('([0-9]+)', skey(s))]

        sort_key = get_alphanum_key_func(key)
        lst.sort(key=sort_key, reverse=reverse)

    @cherrypy.expose
    @require_auth()
    def add_book(self, bookid=None, authorid=None, library=None):
        self.check_permitted(lazylibrarian.perm_search)
        TELEMETRY.record_usage_data()
        if library == 'eBook':
            ebook_status = "Wanted"
            audio_status = "Skipped"
        elif library == 'AudioBook':
            audio_status = "Wanted"
            ebook_status = "Skipped"
        elif library == 'Both':
            audio_status = "Wanted"
            ebook_status = "Wanted"
        else:
            if CONFIG.get_bool('AUDIO_TAB'):
                audio_status = "Wanted"
            else:
                audio_status = "Skipped"
            if CONFIG.get_bool('EBOOK_TAB'):
                ebook_status = "Wanted"
            else:
                ebook_status = "Skipped"

        author_id = ''
        db = database.DBConnection()
        match = db.match('SELECT AuthorID from books WHERE BookID=?', (bookid,))
        if not match and authorid:
            _ = add_author_to_db(None, False, authorid, False, f'WebServer add_book {bookid}')
            match = db.match('SELECT AuthorID from books WHERE BookID=?', (bookid,))
        if match:
            db.upsert("books", {'Status': ebook_status, 'AudioStatus': audio_status},
                      {'BookID': bookid})
            author_id = match['AuthorID']
            update_totals(author_id)
        else:
            this_source = lazylibrarian.INFOSOURCES[CONFIG['BOOK_API']]
            api = this_source['api']
            api = api()
            t = threading.Thread(target=api.add_bookid_to_db,
                                 name=f"{this_source['src']}-BOOK",
                                 args=[bookid, ebook_status, audio_status, "Added by user"])
            t.start()
            t.join(timeout=10)  # 10 s to add book before redirect
        db.close()

        if CONFIG.get_bool('IMP_AUTOSEARCH'):
            books = [{"bookid": bookid}]
            self.start_book_search(books)

        if author_id:
            raise cherrypy.HTTPRedirect(f"author_page?authorid={author_id}")
        if ebook_status == 'Wanted':
            raise cherrypy.HTTPRedirect("books")
        if audio_status == 'Wanted':
            raise cherrypy.HTTPRedirect("audio")
        raise cherrypy.HTTPRedirect("authors")

    @cherrypy.expose
    @require_auth()
    def start_book_search(self, books=None, library=None, force=False):
        self.check_permitted(lazylibrarian.perm_search)
        logger = logging.getLogger(__name__)
        if books:
            if CONFIG.use_any():
                if force:
                    name = 'FORCE-SEARCHBOOK'
                else:
                    name = 'SEARCHBOOK'
                logger.debug("Starting search_book thread")
                threading.Thread(target=search_book, name=name, args=[books, library]).start()
                booktype = library
                if not booktype:
                    booktype = 'book'  # all types
                logger.debug(f"Searching for {booktype} with id: {books[0]['bookid']}")
            else:
                logger.warning("Not searching for book, no search methods set, check config.")
        else:
            logger.debug("BookSearch called with no books")

    @cherrypy.expose
    @require_auth()
    def search_for_book(self, bookid=None, library=None):
        TELEMETRY.record_usage_data()
        author_id = ''
        db = database.DBConnection()
        try:
            bookdata = db.match('SELECT AuthorID from books WHERE BookID=?', (bookid,))
        finally:
            db.close()
        if bookdata:
            author_id = bookdata["AuthorID"]

            # start searchthreads
            books = [{"bookid": bookid}]
            self.start_book_search(books, library=library, force=True)

        if author_id:
            raise cherrypy.HTTPRedirect(f"author_page?authorid={author_id}")
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def request_book(self, **kwargs):
        self.label_thread('REQUEST_BOOK')
        logger = logging.getLogger(__name__)
        prefix = ''
        title = 'Request Error'
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            db = database.DBConnection()
            res = db.match('SELECT Name,UserName,UserID,Email from users where UserID=?', (cookie['ll_uid'].value,))
            if res:
                cmd = ("SELECT BookFile,AudioFile,AuthorName,BookName from books,authors WHERE BookID=? and "
                       "books.AuthorID = authors.AuthorID")
                bookdata = db.match(cmd, (kwargs['bookid'],))
                kwargs.update(bookdata)
                kwargs.update(res)
                kwargs.update({'message': 'Request to Download'})

                remote_ip = cherrypy.request.remote.ip
                msg = f'IP: {remote_ip}\n'
                for itm in kwargs:
                    if kwargs[itm]:
                        line = f"{itm}: {unaccented(kwargs[itm], only_ascii=False)}\n"
                    else:
                        line = f"{itm}: \n"
                    msg += line

                types = []
                if CONFIG.get_bool('EBOOK_TAB'):
                    types.append('eBook')
                if CONFIG.get_bool('AUDIO_TAB'):
                    types.append('AudioBook')

                booktype = 'book'
                if types and 'library' in kwargs and kwargs['library'] in types:
                    booktype = kwargs['library']

                title = f"{booktype}: {bookdata['BookName']}"

                if 'Email' in kwargs and kwargs['Email']:
                    result = notifiers.email_notifier.notify_message('Request from LazyLibrarian User',
                                                                     msg, CONFIG['ADMIN_EMAIL'])
                    if result:
                        prefix = "Message sent"
                        msg = "You will receive a reply by email"
                    else:
                        logger.error(f"Unable to send message to: {msg}")
                        prefix = "Message not sent"
                        msg = "Please try again later"
                else:
                    prefix = "Unable to send message"
                    msg = "No email address supplied"
            else:
                msg = "Unknown user"
            db.close()
        else:
            msg = "Nobody logged in?"

        if prefix == "Message sent":
            timer = 5
        else:
            timer = 0
        return serve_template(templatename="response.html", prefix=prefix,
                              title=title, message=msg, timer=timer)

    @cherrypy.expose
    @require_auth()
    def serve_comic(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Comic [{feedid}]")
        return self.serve_item(feedid, "comic")

    @cherrypy.expose
    @require_auth()
    def serve_img(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Image [{feedid}]")
        return self.serve_item(feedid, "img")

    @cherrypy.expose
    @require_auth()
    def serve_book(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Book [{feedid}]")
        return self.serve_item(feedid, "book")

    @cherrypy.expose
    @require_auth()
    def serve_audio(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Audio [{feedid}]")
        return self.serve_item(feedid, "audio")

    @cherrypy.expose
    @require_auth()
    def serve_issue(self, feedid=None):
        logger = logging.getLogger(__name__)
        logger.debug(f"Serve Issue [{feedid}]")
        return self.serve_item(feedid, "issue")

    @cherrypy.expose
    @require_auth()
    def serve_item(self, feedid, ftype):
        logger = logging.getLogger(__name__)
        userid = feedid[:10]
        itemid = feedid[10:]
        itemid = itemid.split('.')[0]  # discard any extension
        if len(userid) != 10:
            logger.debug(f"Invalid userID [{userid}]")
            return None

        target = ''

        size = re.search(r'_w\d+$', itemid)
        if size:
            size = check_int(size.group()[2:], 0)
            itemid = itemid[:-5]
        else:
            size = 0

        db = database.DBConnection()
        res = db.match('SELECT UserName,Perms,BookType from users where UserID=?', (userid,))
        if res:
            perm = check_int(res['Perms'], 0)
            preftype = res['BookType']
        else:
            logger.debug(f"Invalid userID [{userid}]")
            return None

        if not perm & lazylibrarian.perm_download:
            logger.debug(f"Insufficient permissions for userID [{userid}]")
            return None

        if ftype == 'img':
            if itemid:
                res = db.match('SELECT BookName,BookImg from books WHERE BookID=?', (itemid,))
                if res:
                    logger.debug(f"Itemid {itemid} matches ebook")
                    if size:
                        target = createthumb(os.path.join(DIRS.DATADIR, res['BookImg']), size, False)
                    if not target:
                        target = os.path.join(DIRS.DATADIR, res['BookImg'])
                    if path_isfile(target):
                        return self.send_file(target, name=res['BookName'] + splitext(res['BookImg'])[1])
                else:
                    res = db.match('SELECT Title,Cover from issues WHERE IssueID=?', (itemid,))
                    if res:
                        logger.debug(f"Itemid {itemid} matches issue")
                        if size:
                            target = createthumb(os.path.join(DIRS.DATADIR, res['Cover']), size, False)
                        if not target:
                            target = os.path.join(DIRS.DATADIR, res['Cover'])
                        if path_isfile(target):
                            return self.send_file(target, name=res['Title'] + splitext(res['Cover'])[1])
                    else:
                        try:
                            comicid, issueid = itemid.split('_')
                            cmd = ("SELECT Title,Cover from comics,comicissues WHERE "
                                   "comics.ComicID=comicissues.ComicID and comics.ComicID=? and IssueID=?")
                            res = db.match(cmd, (comicid, issueid))
                        except (IndexError, ValueError):
                            res = None
                        if res:
                            logger.debug(f"Itemid {itemid} matches comicid")
                            if size:
                                target = createthumb(os.path.join(DIRS.DATADIR, res['Cover']), size, False)
                            if not target:
                                target = os.path.join(DIRS.DATADIR, res['Cover'])
                            if path_isfile(target):
                                return self.send_file(target, name=res['Title'] + splitext(res['Cover'])[1])

            logger.debug(f"Itemid {itemid} no match")
            target = os.path.join(DIRS.PROG_DIR, 'data', 'images', 'll192.png')
            if path_isfile(target):
                return self.send_file(target, name='lazylibrarian.png')

        elif ftype == 'comic':
            try:
                comicid, issueid = itemid.split('_')
                cmd = ("SELECT Title,IssueFile from comics,comicissues WHERE comics.ComicID=comicissues.ComicID "
                       "and comics.ComicID=? and IssueID=?")
                res = db.match(cmd, (comicid, issueid))
            except (IndexError, ValueError):
                res = None
                issueid = 0

            if res:
                target = res['IssueFile']
                if target and path_isfile(target):
                    logger.debug(f'Opening {ftype} {target}')
                    return self.send_file(target, name=f"{res['Title']} {issueid}{splitext(target)[1]}")

        elif ftype == 'audio':
            res = db.match('SELECT AudioFile,BookName from books WHERE BookID=?', (itemid,))
            if res:
                cnt = 0
                myfile = res['AudioFile']
                # count the audiobook parts
                if myfile and path_isfile(myfile):
                    parentdir = os.path.dirname(myfile)
                    for _, _, filenames in os.walk(parentdir):
                        for filename in filenames:
                            if CONFIG.is_valid_booktype(filename, 'audiobook'):
                                cnt += 1

                if cnt > 1 and not CONFIG.get_bool('RSS_PODCAST'):
                    target = zip_audio(os.path.dirname(myfile), res['BookName'], itemid)
                    if target and path_isfile(target):
                        logger.debug(f'Opening {ftype} {target}')
                        return self.send_file(target, name=res['BookName'] + '.zip')

                if myfile and path_isfile(myfile):
                    logger.debug(f'Opening {ftype} {myfile}')
                    return self.send_file(myfile)

        elif ftype == 'book':
            res = db.match('SELECT BookFile,BookName from books WHERE BookID=?', (itemid,))
            if res:
                myfile = res['BookFile']
                fname, extn = splitext(myfile)
                types = []
                for itm in get_list(CONFIG['EBOOK_TYPE']):
                    target = fname + '.' + itm
                    if path_isfile(target):
                        types.append(itm)

                # serve user preferred type if available, or system preferred type
                if preftype and preftype in types:
                    extn = preftype
                else:
                    extn = types[0]
                myfile = fname + '.' + extn
                if path_isfile(myfile):
                    logger.debug(f'Opening {ftype} {myfile}')
                    return self.send_file(myfile)

        elif ftype == 'issue':
            res = db.match('SELECT Title,IssueFile from issues WHERE IssueID=?', (itemid,))
            if res:
                myfile = res['IssueFile']
                if myfile and path_isfile(myfile):
                    logger.debug(f'Opening {ftype} {myfile}')
                    return self.send_file(myfile, name=f"{res['Title']} {itemid}{splitext(myfile)[1]}")
        db.close()
        logger.warning(f"No file found for {ftype} {itemid}")
        return None

    @cherrypy.expose
    @require_auth()
    def send_book(self, bookid=None, library=None, redirect=None, booktype=None):
        return self.open_book(bookid=bookid, library=library, redirect=redirect, booktype=booktype, email=True)

    @cherrypy.expose
    @require_auth()
    def open_book(self, bookid=None, library=None, redirect=None, booktype=None, email=False):
        logger = logging.getLogger(__name__)
        adminlogger = logging.getLogger('special.admin')
        adminlogger.debug(f"{bookid} {library} {redirect} {booktype} {email}")
        self.label_thread('OPEN_BOOK')
        # we need to check the user priveleges and see if they can download the book
        db = database.DBConnection()
        if not CONFIG.get_bool('USER_ACCOUNTS'):
            perm = lazylibrarian.perm_admin
            preftype = ''
        else:
            perm = 0
            preftype = ''
            cookie = cherrypy.request.cookie
            if cookie and 'll_uid' in list(cookie.keys()):
                res = db.match('SELECT UserName,Perms,BookType from users where UserID=?',
                               (cookie['ll_uid'].value,))
                if res:
                    perm = check_int(res['Perms'], 0)
                    preftype = res['BookType']

        if booktype is not None:
            preftype = booktype

        bookid_key = 'BookID'
        for itm in api_sources:
            if CONFIG['BOOK_API'] == itm[0]:
                bookid_key = itm[2]
                break

        cmd = (f"SELECT BookFile,AudioFile,AuthorName,BookName from books,authors WHERE books.{bookid_key}=? or "
               "BookID=? and books.AuthorID = authors.AuthorID")
        bookdata = db.match(cmd, (bookid, bookid))
        db.close()
        if not bookdata:
            logger.warning(f'Missing bookid: {bookid}')
        else:
            if perm & lazylibrarian.perm_download:
                author_name = bookdata["AuthorName"]
                book_name = bookdata["BookName"]
                if library == 'AudioBook':
                    bookfile = bookdata["AudioFile"]
                    if bookfile and path_isfile(bookfile):
                        parentdir = os.path.dirname(bookfile)
                        namevars = name_vars(bookid)
                        singlename = namevars['AudioSingleFile']
                        singlefile = ''
                        # noinspection PyBroadException
                        try:
                            for fname in listdir(parentdir):
                                if CONFIG.is_valid_booktype(fname, booktype='audio'):
                                    bname, extn = splitext(fname)
                                    if bname == singlename:
                                        # found name matching the AudioSingleFile
                                        singlefile = os.path.join(parentdir, fname)
                                        break
                        except Exception:
                            pass

                        if booktype == 'whole' and singlefile and path_isfile(singlefile):
                            if email:
                                logger.debug(f'Emailing {library} {singlefile}')
                            else:
                                logger.debug(f'Opening {library} {singlefile}')
                            return self.send_file(singlefile, name=os.path.basename(singlefile), email=email)

                        index = os.path.join(parentdir, 'playlist.ll')
                        if path_isfile(index):
                            if booktype == 'zip':
                                zipfile = zip_audio(parentdir, book_name, bookid)
                                if zipfile and path_isfile(zipfile):
                                    if email:
                                        logger.debug(f'Emailing {library} {zipfile}')
                                    else:
                                        logger.debug(f'Opening {library} {zipfile}')
                                    return self.send_file(zipfile, name=f'{book_name}.zip', email=email)
                            idx = check_int(booktype, 0)
                            if idx:
                                with open(syspath(index)) as f:
                                    part = f.read().splitlines()[idx - 1]
                                bookfile = os.path.join(parentdir, part)
                                if bookfile and path_isfile(bookfile):
                                    if email:
                                        logger.debug(f'Emailing {library} {bookfile}')
                                    else:
                                        logger.debug(f'Opening {library} {bookfile}')
                                    return self.send_file(bookfile, name=f"{book_name} "
                                                                         f"part{idx}{splitext(bookfile)[1]}",
                                                          email=email)
                            with open(index) as fp:
                                cnt = sum(1 for _ in fp)
                            if cnt <= 1:
                                if email:
                                    logger.debug(f'Emailing {library} {bookfile}')
                                else:
                                    logger.debug(f'Opening {library} {bookfile}')
                                return self.send_file(bookfile, email=email)
                            msg = "Please select which part to "
                            if email:
                                msg += "email"
                            else:
                                msg += "download"
                            itm = 1
                            partlist = ''
                            while itm <= cnt:
                                if partlist:
                                    partlist += ' '
                                partlist += str(itm)
                                itm += 1
                                partlist += ' zip'
                                if singlefile and path_isfile(singlefile):
                                    partlist += ' whole'
                            safetitle = book_name.replace('&', '&amp;').replace("'", "")

                            return serve_template(templatename="choosetype.html",
                                                  title=safetitle, pop_message=msg,
                                                  pop_types=partlist, bookid=bookid,
                                                  valid=get_list(partlist.replace(' ', ',')),
                                                  email=email)
                        if email:
                            logger.debug(f'Emailing {library} {bookfile}')
                        else:
                            logger.debug(f'Opening {library} {bookfile}')
                        return self.send_file(bookfile, email=email)

                library = 'eBook'
                bookfile = bookdata["BookFile"]
                if bookfile and path_isfile(bookfile):
                    fname, _ = splitext(bookfile)
                    types = []
                    for itm in get_list(CONFIG['EBOOK_TYPE']):
                        target = fname + '.' + itm
                        if path_isfile(target):
                            types.append(itm)
                    logger.debug(f'Preftype:{preftype} Available:{str(types)}')
                    if preftype and len(types):
                        if preftype in types:
                            bookfile = fname + '.' + preftype
                        else:
                            msg = f"{book_name}<br> Not available as {preftype}, only "
                            typestr = ''
                            for itm in types:
                                if typestr:
                                    typestr += ' '
                                typestr += itm
                            msg += typestr
                            return serve_template(templatename="choosetype.html",
                                                  title="Not Available", pop_message=msg,
                                                  pop_types=typestr, bookid=bookid,
                                                  valid=get_list(CONFIG['EBOOK_TYPE']),
                                                  email=email)
                    elif len(types) > 1:
                        msg = "Please select format to "
                        if email:
                            msg += "email"
                        else:
                            msg += "download"
                        typestr = ''
                        for itm in types:
                            if typestr:
                                typestr += ' '
                            typestr += itm
                        return serve_template(templatename="choosetype.html",
                                              title="Choose Type", pop_message=msg,
                                              pop_types=typestr, bookid=bookid,
                                              valid=get_list(CONFIG['EBOOK_TYPE']),
                                              email=email)
                    if len(types) and bookfile and path_isfile(bookfile):
                        if email:
                            logger.debug(f'Emailing {library} {bookfile}')
                            return self.send_file(bookfile, name=book_name, email=email)
                        logger.debug(f'Opening {library} {bookfile}')
                        return self.send_file(bookfile, email=email)
                    logger.debug(f'Unable to send {library} {book_name}, no valid types?')

                logger.info(f'Missing {library} {author_name}, {book_name} [{bookfile}]')
                if library == 'AudioBook':
                    raise cherrypy.HTTPRedirect("audio")
                raise cherrypy.HTTPRedirect("books")
            return self.request_book(library=library, bookid=bookid, redirect=redirect)

        if library == 'AudioBook':
            raise cherrypy.HTTPRedirect("audio")
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def edit_author(self, authorid=None, images=False):
        self.label_thread('EDIT_AUTHOR')
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            data = db.match('SELECT * from authors WHERE AuthorID=?', (authorid,))
        finally:
            db.close()
        if data:
            photos = []
            if images:
                res = get_author_image(authorid=authorid, refresh=False, max_num=5)
                if res and path_isdir(res):
                    basedir = res.replace(DIRS.DATADIR, '').lstrip('/')
                    for itm in listdir(res):
                        photos.append([itm, os.path.join(basedir, itm)])
            return serve_template(templatename="editauthor.html", title="Edit Author", config=data,
                                  images=photos)
        logger.info(f'Missing author {authorid}')
        return None

    # noinspection PyUnusedLocal
    # kwargs needed for passing utf8 hidden input
    @cherrypy.expose
    @require_auth()
    def author_update(self, authorid='', authorname='', authorborn='', authordeath='', authorimg='',
                      editordata='', manual='0', aka='', **kwargs):
        self.check_permitted(lazylibrarian.perm_edit)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        authdata = db.match('SELECT * from authors WHERE AuthorID=?', (authorid,))
        if authdata:
            edited = ""
            if not authorborn or authorborn == 'None':
                authorborn = None
            if not authordeath or authordeath == 'None':
                authordeath = None
            if authorimg == 'None':
                authorimg = ''
            manual = bool(check_int(manual, 0))

            if authdata["AuthorBorn"] != authorborn:
                edited += "Born "
            if authdata["AKA"] != aka:
                edited += "AKA "
            if authdata["AuthorDeath"] != authordeath:
                edited += "Died "
            if 'cover' in kwargs:
                if kwargs['cover'] == "manual":
                    if authorimg and (authdata["AuthorImg"] != authorimg):
                        edited += "Image manual"
                elif kwargs['cover'] != "current":
                    authorimg = os.path.join(DIRS.DATADIR, kwargs['cover'])
                    edited += f"Image {kwargs['cover']} "

            if authdata["About"] != editordata:
                edited += "Description "
            if bool(check_int(authdata['Manual'], 0)) != manual:
                edited += "Manual "

            if authdata["AuthorName"] != authorname:
                match = db.match('SELECT AuthorName from authors where AuthorName=?', (authorname,))
                if match:
                    logger.debug(f"Unable to rename, new author name {authorname} already exists")
                    authorname = authdata["AuthorName"]
                else:
                    edited += "Name "

            if edited:
                # Check dates, format to yyyy/mm/dd
                # use None to clear date
                # Leave unchanged if fails datecheck
                if authorborn is not None:
                    ab = date_format(authorborn, context=authorname, datelang=CONFIG['DATE_LANG'])
                    if len(ab) == 10:
                        authorborn = ab
                    else:
                        logger.warning(f"Author Born date [{authorborn}] rejected")
                        authorborn = authdata["AuthorBorn"]  # leave unchanged
                        edited = edited.replace('Born ', '')

                if authordeath is not None:
                    ab = date_format(authordeath, context=authorname, datelang=CONFIG['DATE_LANG'])
                    if len(ab) == 10:
                        authordeath = ab
                    else:
                        logger.warning(f"Author Died date [{authordeath}] rejected")
                        authordeath = authdata["AuthorDeath"]  # leave unchanged
                        edited = edited.replace('Died ', '')

                if not authorimg:
                    authorimg = authdata["AuthorImg"]
                else:
                    if authorimg == 'none':
                        authorimg = os.path.join(DIRS.PROG_DIR, 'data', 'images', 'nophoto.png')

                    rejected = True

                    if authorimg.startswith('http'):
                        # cache image from url
                        authorimg, success, _ = cache_img(ImageType.AUTHOR, img_id(), authorimg, refresh=True)
                        if success:
                            rejected = False
                    else:
                        # Cache file image
                        if not path_isfile(authorimg):
                            logger.warning(f"Failed to find file {authorimg}")
                        else:
                            extn = splitext(authorimg)[1].lower()
                            if extn and extn in ['.jpg', '.jpeg', '.png', '.webp']:
                                image_id = img_id()
                                destfile = os.path.join(DIRS.CACHEDIR, 'author', image_id + '.jpg')
                                try:
                                    copyfile(authorimg, destfile)
                                    logger.debug(f"{authorimg}->{destfile}")
                                    setperm(destfile)
                                    authorimg = 'cache/author/' + image_id + '.jpg'
                                    rejected = False
                                except Exception as why:
                                    logger.warning(
                                        f"Failed to copy file {authorimg}, {type(why).__name__} {str(why)}")
                            else:
                                logger.warning(f"Invalid extension on [{authorimg}]")

                    if rejected:
                        logger.warning(f"Author Image [{authorimg}] rejected")
                        authorimg = authdata["AuthorImg"]
                        edited = edited.replace('Image ', '')

                control_value_dict = {'AuthorID': authorid}
                new_value_dict = {
                    'AuthorName': authorname,
                    'AuthorBorn': authorborn,
                    'AuthorDeath': authordeath,
                    'AuthorImg': authorimg,
                    'About': editordata,
                    'AKA': aka,
                    'Manual': bool(manual)
                }
                db.upsert("authors", new_value_dict, control_value_dict)
                logger.info(f'Updated [ {edited}] for {authorname}')

            else:
                logger.debug(f'Author [{authorname}] has not been changed')
        db.close()

        icrawlerdir = os.path.join(DIRS.CACHEDIR, 'icrawler', authorid)
        rmtree(icrawlerdir, ignore_errors=True)
        raise cherrypy.HTTPRedirect(f"author_page?authorid={authorid}")

    @cherrypy.expose
    @require_auth()
    def edit_book(self, bookid=None, library='eBook', images=False):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        self.label_thread('EDIT_BOOK')
        TELEMETRY.record_usage_data()
        db = database.DBConnection()
        authors = db.select(
            "SELECT AuthorName from authors WHERE Status !='Ignored' ORDER by AuthorName COLLATE NOCASE")
        cmd = ("SELECT BookName,BookID,BookSub,BookGenre,BookLang,BookDesc,books.Manual,AuthorName,books.AuthorID,"
               "BookDate,ScanResult,BookAdded,BookIsbn,WorkID,LT_WorkID,Narrator,BookFile,books.gr_id,"
               "books.gb_id,books.ol_id, books.hc_id from books,authors WHERE books.AuthorID = authors.AuthorID"
               " and BookID=?")
        bookdata = db.match(cmd, (bookid,))
        cmd = "SELECT SeriesName, SeriesNum from member,series where series.SeriesID=member.SeriesID and BookID=?"
        seriesdict = db.select(cmd, (bookid,))
        if bookdata:
            cmd = ("SELECT SeriesName from series,seriesauthors WHERE series.seriesid = seriesauthors.seriesid and "
                   "authorid=? ORDER by SeriesName COLLATE NOCASE")
            series = db.select(cmd, (bookdata['AuthorID'],))
        else:
            series = db.select("SELECT SeriesName from series WHERE Status !='Ignored' "
                               "ORDER by SeriesName COLLATE NOCASE")
        db.close()
        if bookdata:
            bookdata = dict(bookdata)
            bookdata['library'] = library
            if library != "AudioBook":
                bookdata.pop('Narrator', None)
            covers = []
            if images:
                # flickr needs an apikey and doesn't seem to have authors or book covers
                # baidu doesn't like bots, message: "Forbid spider access"
                sources = ['current', 'cover', 'goodreads', 'librarything', 'openlibrary',
                           'googleisbn', 'bing', 'googleimage']
                if CONFIG['HC_API']:
                    sources.append('hardcover')
                for source in sources:
                    cover, _ = get_book_cover(bookid, source)
                    if cover:
                        covers.append([source, cover])

            bookfile = bookdata['BookFile']
            if bookfile and path_isfile(bookfile):
                opffile = opf_file(os.path.dirname(bookfile))
            else:
                opffile = ''
            if opffile and path_isfile(opffile):
                opf_template, replaces = opf_read(opffile)
                remove_file(opf_template)  # we don't need the template file yet
            else:
                replaces = []
            subs = []

            for itm in replaces:
                # remove ones that are duplicated in bookdata, don't want two fields editing the same item
                # can't modify replaces list while iterating so make a new list
                if itm[0] not in ['title', 'creator', 'ISBN', 'date', 'description']:
                    subs.append(itm)
            return serve_template(templatename="editbook.html", title="Edit Book", config=bookdata,
                                  seriesdict=seriesdict, authors=authors, covers=covers, replaces=subs, series=series)
        logger.info(f'Missing book {bookid}')
        return None

    @cherrypy.expose
    @require_auth()
    def book_update(self, bookname='', bookid='', booksub='', bookgenre='', booklang='', bookdate='',
                    manual='0', authorname='', cover='', newid='', editordata='', bookisbn='', workid='',
                    **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.check_permitted(lazylibrarian.perm_edit)
        logger = logging.getLogger(__name__)
        if bookid:
            db = database.DBConnection()
            try:
                scanresult = ''
                if kwargs.get('importfrom'):
                    source = kwargs['importfrom']
                    folder = ''
                    library = ''
                    if path_isfile(source):
                        folder = os.path.dirname(source)
                    elif path_isdir(source):
                        folder = source
                    if folder:
                        if book_file(folder, booktype='audiobook', config=CONFIG):
                            library = 'Audio'
                        elif book_file(folder, booktype='ebook', config=CONFIG):
                            library = 'eBook'
                    if library:
                        res = process_book_from_dir(folder, library, bookid)
                        if res:
                            scanresult = f'Imported manually from {folder}'
                        else:
                            logger.debug(f"Failed to import {bookid} from {source}")
                            raise cherrypy.HTTPRedirect(f"edit_book?bookid={bookid}")
                    else:
                        logger.debug(f"No {library} found in {source}")

                cmd = ("SELECT BookName,BookSub,BookGenre,BookLang,BookImg,BookDate,BookDesc,books.Manual,"
                       "AuthorName,books.AuthorID, BookIsbn, WorkID, ScanResult, BookFile from books,authors "
                       "WHERE books.AuthorID = authors.AuthorID and BookID=?")
                bookdata = db.match(cmd, (bookid,))
                if bookdata:
                    edited = ''
                    moved = False
                    if bookgenre == 'None':
                        bookgenre = ''
                    manual = bool(check_int(manual, 0))

                    if newid and bookid != newid:
                        cmd = ("SELECT BookName,Authorname from books,authors WHERE "
                               "books.AuthorID = authors.AuthorID and BookID=?")
                        match = db.match(cmd, (newid,))
                        if match:
                            logger.warning(
                                f"Cannot change bookid to {newid}, in use by {match['BookName']}/{match['AuthorName']}")
                        else:
                            logger.warning("Updating bookid is not supported yet")
                            # edited += "BookID "
                    if scanresult and bookdata['ScanResult'] != scanresult:
                        edited += "ScanResult "
                    if bookdata['BookName'] != bookname:
                        edited += "Title "
                    if bookdata['BookSub'] != booksub:
                        edited += "Subtitle "
                    if bookdata['BookDesc'] != editordata:
                        edited += "Description "
                    if bookdata['BookGenre'] != bookgenre:
                        edited += "Genre "
                    if bookdata['BookLang'] != booklang:
                        edited += "Language "
                    if bookdata['BookIsbn'] != bookisbn:
                        edited += "ISBN "
                    if bookdata['WorkID'] != workid:
                        edited += "WorkID "
                    if bookdata['BookDate'] != bookdate:
                        if bookdate == '0000':
                            edited += "Date "
                        else:
                            # googlebooks sometimes gives yyyy, sometimes yyyy-mm, sometimes yyyy-mm-dd
                            if len(bookdate) == 4:
                                y = check_year(bookdate)
                            elif len(bookdate) in [7, 10]:
                                y = check_year(bookdate[:4])
                                if y and len(bookdate) == 7:
                                    try:
                                        _ = datetime.date(int(bookdate[:4]), int(bookdate[5:7]), 1)
                                    except ValueError:
                                        y = 0
                                elif y and len(bookdate) == 10:
                                    try:
                                        _ = datetime.date(int(bookdate[:4]), int(bookdate[5:7]), int(bookdate[8:]))
                                    except ValueError:
                                        y = 0
                            else:
                                y = 0
                            if y:
                                edited += "Date "
                            else:
                                bookdate = bookdata["BookDate"]
                    if bool(check_int(bookdata['Manual'], 0)) != manual:
                        edited += "Manual "
                    if bookdata['AuthorName'] != authorname:
                        moved = True

                    covertype = ''
                    if cover == 'librarything':
                        covertype = '_lt'
                    elif cover == 'goodreads':
                        covertype = '_gr'
                    elif cover == 'openlibrary':
                        covertype = '_ol'
                    elif cover == 'googleisbn':
                        covertype = '_gi'
                    elif cover == 'googleimage':
                        covertype = '_go'
                    elif cover == 'bing':
                        covertype = '_bi'
                    elif cover == 'cover':
                        covertype = '_cover'
                    if covertype:
                        cachedir = DIRS.CACHEDIR
                        coverid = uuid.uuid4().hex
                        coverlink = 'cache/book/' + coverid + '.jpg'
                        coverfile = os.path.join(cachedir, "book", coverid + '.jpg')
                        newcoverfile = os.path.join(cachedir, "book", bookid + covertype + '.jpg')
                        if not path_exists(newcoverfile):
                            logger.error(f"Coverfile {newcoverfile} for {bookid} is missing")
                        else:
                            try:
                                edited += f'Cover ({cover})'
                                dest = copyfile(newcoverfile, coverfile)
                                logger.debug(f"{newcoverfile} {coverlink} {dest}")
                            except Exception as e:
                                logger.error(str(e))
                    else:
                        coverlink = bookdata['BookImg']

                    if edited:
                        control_value_dict = {'BookID': bookid}
                        new_value_dict = {
                            'BookName': bookname,
                            'BookSub': booksub,
                            'BookGenre': bookgenre,
                            'BookLang': booklang,
                            'BookDate': bookdate,
                            'BookDesc': editordata,
                            'BookIsbn': bookisbn,
                            'WorkID': workid,
                            'BookImg': coverlink,
                            'ScanResult': scanresult,
                            'Manual': bool(manual)
                        }
                        db.upsert("books", new_value_dict, control_value_dict)

                    cmd = ("SELECT SeriesName, SeriesNum, series.SeriesID from member,series where "
                           "series.SeriesID=member.SeriesID and BookID=?")
                    old_series = db.select(cmd, (bookid,))
                    old_list = []
                    new_list = []
                    dict_counter = 0
                    while f"series[{dict_counter}][name]" in kwargs:
                        s_name = kwargs[f"series[{dict_counter}][name]"]
                        s_name = clean_name(s_name, '&/')
                        s_num = kwargs[f"series[{dict_counter}][number]"]
                        match = db.match('SELECT SeriesID from series WHERE SeriesName=?', (s_name,))
                        if match:
                            new_list.append([match['SeriesID'], s_num, s_name])
                        else:
                            new_list.append(['', s_num, s_name])
                        dict_counter += 1
                    if ('series[new][name]' in kwargs and 'series[new][number]' in kwargs and
                            kwargs['series[new][name]']):
                        s_name = kwargs["series[new][name]"]
                        s_name = clean_name(s_name, '&/')
                        s_num = kwargs['series[new][number]']
                        new_list.append(['', s_num, s_name])
                    for itm in old_series:
                        old_list.append([itm['SeriesID'], itm['SeriesNum'], itm['SeriesName']])

                    debug_msg = f"Old series list for {bookid}: {old_list}"
                    logger.debug(debug_msg)
                    clean_list = []
                    for itm in new_list:
                        if itm[1]:
                            clean_list.append(itm)
                    new_list = clean_list

                    debug_msg = f"New series list for {bookid}: {new_list}"
                    logger.debug(debug_msg)
                    series_changed = False
                    for itm in old_list:
                        if itm[1:] not in [i[1:] for i in new_list]:
                            series_changed = True
                    for itm in new_list:
                        if itm[1:] not in [i[1:] for i in old_list]:
                            series_changed = True
                    if not series_changed:
                        logger.debug("No series changes")
                    if series_changed:
                        set_series(new_list, bookid, reason=scanresult)
                        delete_empty_series()
                        edited += "Series "

                    bookfile = bookdata['BookFile']
                    if bookfile and path_isfile(bookfile):
                        opffile = opf_file(os.path.dirname(bookfile))
                    else:
                        opffile = ''
                    if opffile and path_isfile(opffile):
                        opf_template, replaces = opf_read(opffile)
                    else:
                        opf_template = ''
                        replaces = []

                    if opf_template:
                        subs = []
                        for itm in replaces:
                            if itm[0] == 'title':
                                subs.append((itm[0], bookname))
                            elif itm[0] == 'creator':
                                subs.append((itm[0], authorname))
                            elif itm[0] == 'ISBN':
                                subs.append((itm[0], bookisbn))
                            elif itm[0] == 'date':
                                subs.append((itm[0], bookdate))
                            elif itm[0] == 'description':
                                subs.append((itm[0], editordata))
                            elif itm[0] in kwargs:
                                if itm[1] != kwargs[itm[0]]:
                                    edited += itm[0] + ' '
                                    subs.append((itm[0], kwargs[itm[0]]))
                                else:
                                    subs.append((itm[0], itm[1]))
                            else:
                                subs.append((itm[0], itm[1]))

                        if edited:
                            new_opf = opf_write(opf_template, subs)
                            remove_file(opf_template)
                            remove_file(opffile)
                            try:
                                safe_move(new_opf, opffile)
                            except Exception as e:
                                logger.warning(f"Failed to move file: {str(e)}")
                                moved = False
                    if edited:
                        logger.info(f'Updated [ {edited}] for {bookname}')
                    else:
                        logger.debug(f'Book [{bookname}] has not been changed')

                    if moved:
                        authordata = db.match('SELECT AuthorID from authors WHERE AuthorName=?', (authorname,))
                        if authordata:
                            control_value_dict = {'BookID': bookid}
                            new_value_dict = {'AuthorID': authordata['AuthorID']}
                            db.upsert("books", new_value_dict, control_value_dict)
                            update_totals(bookdata["AuthorID"])  # we moved from here
                            update_totals(authordata['AuthorID'])  # to here

                        logger.info(f'Book [{bookname}] has been moved')
                    else:
                        logger.debug(f'Book [{bookname}] has not been moved')
                    if edited or moved:
                        data = db.match("SELECT * from books,authors WHERE "
                                        "books.authorid=authors.authorid and BookID=?", (bookid,))
                        if data['BookFile'] and path_isfile(data['BookFile']):
                            dest_path = os.path.dirname(data['BookFile'])
                            global_name = splitext(os.path.basename(data['BookFile']))[0]
                            if opf_template:  # we already have a valid (new) opffile
                                dest_opf = os.path.join(dest_path, global_name + '.opf')
                                if opffile != dest_opf:
                                    try:
                                        safe_copy(opffile, dest_opf)
                                    except Exception as e:
                                        logger.warning(f"Failed to copy opf file: {str(e)}")
                            else:
                                create_opf(dest_path, data, global_name, overwrite=True)

                    raise cherrypy.HTTPRedirect(f"edit_book?bookid={bookid}")
            finally:
                db.close()
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_results_ajax(self, **args):
        action = args.get('action', 'unknown action')
        redirect = args.get('redirect', '')
        passed = 0
        failed = 0

        for arg in ['action']:
            args.pop(arg, None)

        this_source = lazylibrarian.INFOSOURCES[CONFIG['BOOK_API']]
        api = this_source['api']
        api = api()
        ids = set(args.keys())
        if action in ['AddBook', 'AddAudio', 'AddBoth']:
            wantbook = "Wanted" if action in ['AddBook', 'AddBoth'] else 'Skipped'
            wantaudio = "Wanted" if action in ['AddAudio', 'AddBoth'] else 'Skipped'
            for itm in ids:
                if api.add_bookid_to_db(itm, wantbook, wantaudio,
                                        f"Added by User from resultlist {wantbook}:{wantaudio}"):
                    passed += 1
                else:
                    failed += 1
        elif action in ['AddAuthor']:
            books = bool(CONFIG['NEWAUTHOR_STATUS'] != 'Ignored') or bool(CONFIG['NEWAUTHOR_AUDIO'] != 'Ignored')
            for itm in ids:
                if add_author_to_db(refresh=False, authorid=itm, addbooks=books,
                                    reason=f"User add_author_id {itm}"):
                    passed += 1
                else:
                    failed += 1

        total = passed + failed
        summary = f"Mark Results '{action}' completed."
        if total > 0:
            summary += f" {passed} successful"
            if failed > 0:
                summary += f", {failed} failed"
            summary += f" out of {total} total items."
        else:
            summary += " No items were processed."

        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'summary': summary,
            'redirect': redirect
        }

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_books_ajax(self, authorid=None, seriesid=None, action=None, redirect=None, **args):
        book_filter = None
        if 'bookfilter' in args:
            book_filter = args['bookfilter']
        self.check_permitted(lazylibrarian.perm_status)
        logger = logging.getLogger(__name__)
        if 'library' in args:
            library = args['library']
        else:
            library = 'eBook'
            if redirect == 'audio':
                library = 'AudioBook'

        if 'marktype' in args:
            library = args['marktype']

        if 'AuthorID' in args and authorid is None:
            authorid = args['AuthorID']

        for arg in ['book_table_length', 'ignored', 'library', 'booklang', 'marktype', 'AuthorID', 'bookfilter']:
            args.pop(arg, None)

        passed = 0
        failed = 0
        to_read = []
        have_read = []
        reading = []
        abandoned = []
        userid = ''
        wantedbooks = []
        wantedaudio = []

        db = database.DBConnection()
        if not self.valid_source(redirect):
            redirect = "books"
        check_totals = []
        if redirect == 'author':
            check_totals = [authorid]
        reading_lists = ["Unread", "Read", "ToRead", "Reading", "Abandoned"]
        if action:
            if action in reading_lists:
                cookie = cherrypy.request.cookie
                if cookie and 'll_uid' in list(cookie.keys()):
                    userid = cookie['ll_uid'].value
                    to_read = set(get_readinglist("ToRead", userid))
                    have_read = set(get_readinglist("HaveRead", userid))
                    reading = set(get_readinglist("Reading", userid))
                    abandoned = set(get_readinglist("Abandoned", userid))

            for bookid in args:
                if action in reading_lists:
                    to_read.discard(bookid)
                    have_read.discard(bookid)
                    reading.discard(bookid)
                    abandoned.discard(bookid)

                    if action == "Read":
                        have_read.add(bookid)
                    elif action == "ToRead":
                        to_read.add(bookid)
                    elif action == "Reading":
                        reading.add(bookid)
                    elif action == "Abandoned":
                        abandoned.add(bookid)
                    logger.debug(f'Status set to {action} for {bookid}')
                    passed += 1

                elif action in ["Skipped", "Have", "Ignored", "IgnoreBoth",
                                "Wanted", "WantEbook", "WantAudio", "WantBoth"]:
                    bookdata = db.match('SELECT AuthorID,BookName,Status,AudioStatus from books WHERE BookID=?',
                                        (bookid,))
                    if bookdata:
                        authorid = bookdata['AuthorID']
                        bookname = bookdata['BookName']
                        if authorid not in check_totals:
                            check_totals.append(authorid)
                        if (action == "Wanted" and library == "eBook") or action in ["WantEbook", "WantBoth"]:
                            if bookdata['Status'] in ["Open", "Have"]:
                                logger.debug(f'eBook "{bookname}" is already marked Open')
                                failed += 1
                            else:
                                db.upsert("books", {'Status': 'Wanted'}, {'BookID': bookid})
                                logger.debug(f'Status set to "Wanted" for "{bookname}"')
                                wantedbooks.append({"bookid": bookid})
                                passed += 1
                        if (action == "Wanted" and library == "AudioBook") or action in ["WantAudio", "WantBoth"]:
                            if bookdata['AudioStatus'] in ["Open", "Have"]:
                                logger.debug(f'AudioBook "{bookname}" is already marked Open')
                                failed += 1
                            else:
                                db.upsert("books", {'AudioStatus': 'Wanted'}, {'BookID': bookid})
                                logger.debug(f'AudioStatus set to "Wanted" for "{bookname}"')
                                wantedaudio.append({"bookid": bookid})
                                passed += 1
                        if (action == "Ignored" and library == 'eBook') or action == "IgnoreBoth":
                            db.upsert("books", {'Status': "Ignored", 'ScanResult': f'User {action}'},
                                      {'BookID': bookid})
                            logger.debug(f'Status set to "Ignored" for "{bookname}"')
                            passed += 1
                        if (action == "Ignored" and library == 'AudioBook') or action == "IgnoreBoth":
                            db.upsert("books", {'AudioStatus': "Ignored", 'ScanResult': f'User {action}'},
                                      {'BookID': bookid})
                            logger.debug(f'AudioStatus set to "Ignored" for "{bookname}"')
                            passed += 1
                        if action in ["Skipped", "Have"]:
                            if library == 'eBook':
                                db.upsert("books", {'Status': action, 'ScanResult': f'User {action}'},
                                          {'BookID': bookid})
                                logger.debug(f'Status set to "{action}" for "{bookname}"')
                                passed += 1
                            if library == 'AudioBook':
                                db.upsert("books", {'AudioStatus': action, 'ScanResult': f'User {action}'},
                                          {'BookID': bookid})
                                logger.debug(f'AudioStatus set to "{action}" for "{bookname}"')
                                passed += 1
                    else:
                        logger.warning(f"Unable to set status {action} for {bookid}")
                        failed += 1
                elif action == "NoDelay":
                    db.action("delete from failedsearch WHERE BookID=? AND Library=?", (bookid, library))
                    logger.debug(f'{library} delay set to zero for {bookid}')
                    passed += 1
                elif action in ["Remove", "Delete"]:
                    cmd = ("SELECT AuthorName,Bookname,BookFile,AudioFile,books.AuthorID from books,authors "
                           "WHERE BookID=? and books.AuthorID = authors.AuthorID")
                    bookdata = db.match(cmd, (bookid,))
                    if bookdata:
                        authorid = bookdata['AuthorID']
                        bookname = bookdata['BookName']
                        if authorid not in check_totals:
                            check_totals.append(authorid)
                        if action == "Delete":
                            if 'Audio' in library:
                                bookfile = bookdata['AudioFile']
                                if bookfile and path_isfile(bookfile):
                                    try:
                                        rmtree(os.path.dirname(bookfile), ignore_errors=True)
                                        logger.info(f'AudioBook {bookname} deleted from disc')
                                        passed += 1
                                    except Exception as e:
                                        logger.warning(f'rmtree failed on {bookfile}, {type(e).__name__} {str(e)}')
                                        failed += 1
                            if 'eBook' in library:
                                bookfile = bookdata['BookFile']
                                if bookfile and path_isfile(bookfile):
                                    try:
                                        rmtree(os.path.dirname(bookfile), ignore_errors=True)
                                        deleted = True
                                        passed += 1
                                    except Exception as e:
                                        logger.warning(f'rmtree failed on {bookfile}, {type(e).__name__} {str(e)}')
                                        deleted = False
                                        failed += 1

                                    if deleted:
                                        logger.info(f'eBook {bookname} deleted from disc')
                                        if CONFIG['IMP_CALIBREDB'] and \
                                                CONFIG.get_bool('IMP_CALIBRE_EBOOK'):
                                            self.delete_from_calibre(bookdata)

                        authorcheck = db.match('SELECT Status from authors WHERE AuthorID=?', (authorid,))
                        if authorcheck:
                            if authorcheck['Status'] not in ['Active', 'Wanted']:
                                for table in ['books', 'wanted', 'readinglists']:
                                    db.action(f"DELETE from {table} WHERE BookID=?", (bookid,))
                                logger.info(f'Removed "{bookname}" from database')
                                passed += 1
                            elif 'eBook' in library:
                                db.upsert("books", {"Status": "Ignored", "ScanResult": "User deleted"},
                                          {"BookID": bookid})
                                logger.debug(f'Status set to Ignored for "{bookname}"')
                                passed += 1
                            elif 'Audio' in library:
                                db.upsert("books", {"AudioStatus": "Ignored", "ScanResult": "User deleted"},
                                          {"BookID": bookid})
                                logger.debug(f'AudioStatus set to Ignored for "{bookname}"')
                                passed += 1
                        else:
                            for table in ['books', 'wanted', 'readinglists']:
                                db.action(f"DELETE from {table} WHERE BookID=?", (bookid,))
                            logger.info(f'Removed "{bookname}" from database')
                            passed += 1

            if action in reading_lists and userid:
                set_readinglist("ToRead", userid, to_read)
                set_readinglist("HaveRead", userid, have_read)
                set_readinglist("Reading", userid, reading)
                set_readinglist("Abandoned", userid, abandoned)
        db.close()

        if check_totals:
            for author in check_totals:
                update_totals(author)

        # start searchthreads
        if CONFIG.use_any() and check_int(CONFIG['SEARCH_BOOKINTERVAL'], 0):
            if wantedbooks:
                logger.debug(f"Starting ebook search thread, library={library}, action={action}")
                threading.Thread(target=search_book, name='SEARCHBOOK',
                                 args=[wantedbooks, 'eBook']).start()
            if wantedaudio:
                logger.debug(f"Starting audio search thread, library={library}, action={action}")
                threading.Thread(target=search_book, name='SEARCHBOOK',
                                 args=[wantedaudio, 'AudioBook']).start()

        if redirect == "author":
            if 'eBook' in library:
                redirect = f"author_page?authorid={authorid}&library=eBook"
            if 'Audio' in library:
                redirect = f"author_page?authorid={authorid}&library=AudioBook"
        elif redirect in ["books", "audio"]:
            redirect = redirect
        elif redirect == "members":
            redirect = f"series_members?seriesid={seriesid}&ignored=False"
        elif 'Audio' in library:
            redirect = "manage?library=AudioBook"
        else:
            redirect = "manage?library=eBook"
        if book_filter:
            redirect = f"{redirect}&book_filter={book_filter}"
        # Return JSON response instead of redirect
        total = passed + failed
        summary = f"Mark Books '{action}' completed."
        if total > 0:
            summary += f" {passed} successful"
            if failed > 0:
                summary += f", {failed} failed"
            summary += f" out of {total} total items."
        else:
            summary += " No items were processed."
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'summary': summary,
            'redirect': redirect
        }

    # WALL #########################################################

    @cherrypy.expose
    @require_auth()
    def mag_wall(self, title=''):
        self.label_thread('MAGWALL')
        cmd = "SELECT IssueFile,IssueID,IssueDate,Title,Cover from issues"
        args = None
        if title:
            title = title.replace('&amp;', '&')
            cmd += " WHERE Title=?"
            args = (title,)
        cmd += " order by IssueAcquired DESC"
        db = database.DBConnection()
        try:
            issues = db.select(cmd, args)
        finally:
            db.close()
        if not len(issues):
            raise cherrypy.HTTPRedirect("magazines")
        mod_issues = []
        maxcount = CONFIG.get_int('MAX_WALL')
        for count, issue in enumerate(issues, start=1):
            this_issue = dict(issue)
            if not this_issue.get('Cover') or not this_issue['Cover'].startswith('cache/'):
                this_issue['Cover'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(this_issue['Cover'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    this_issue['Cover'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, this_issue['Cover'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        this_issue['Cover'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            this_issue['Title'] = issue['Title'].replace('&amp;', '&')
            mod_issues.append(this_issue)
            if maxcount and count >= maxcount:
                title = f"{title} (Top {count})"
                break

        return serve_template(
            templatename="coverwall.html", title=title, results=mod_issues, redirect="magazines",
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def comic_wall(self, comicid=None):
        self.label_thread('COMICWALL')
        cmd = ("SELECT IssueFile,IssueID,comics.ComicID,Title,Cover from comicissues,comics WHERE "
               "comics.ComicID = comicissues.ComicID")
        args = None
        if comicid:
            cmd += " AND comics.ComicID=?"
            args = (comicid,)
        cmd += " order by IssueAcquired DESC"
        db = database.DBConnection()
        try:
            issues = db.select(cmd, args)
        finally:
            db.close()
        title = ''
        if not len(issues):
            raise cherrypy.HTTPRedirect("comics")
        mod_issues = []
        maxcount = CONFIG.get_int('MAX_WALL')
        for count, issue in enumerate(issues, start=1):
            this_issue = dict(issue)
            if not this_issue.get('Cover') or not this_issue['Cover'].startswith('cache/'):
                this_issue['Cover'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(this_issue['Cover'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    this_issue['Cover'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, this_issue['Cover'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        this_issue['Cover'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            mod_issues.append(this_issue)
            if maxcount and count >= maxcount:
                title = f"{title} (Top {count})"
                break

        return serve_template(
            templatename="coverwall.html", title=title, results=mod_issues, redirect="comic",
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def book_wall(self, have='0'):
        self.label_thread('BOOKWALL')
        if have == '1':
            cmd = "SELECT BookLink,BookImg,BookID,BookName from books where Status='Open' order by BookLibrary DESC"
            title = 'Recently Downloaded Books'
        else:
            cmd = "SELECT BookLink,BookImg,BookID,BookName from books where Status != 'Ignored' order by BookAdded DESC"
            title = 'Recently Added Books'
        db = database.DBConnection()
        try:
            results = db.select(cmd)
        finally:
            db.close()
        if not len(results):
            raise cherrypy.HTTPRedirect("books")
        maxcount = CONFIG.get_int('MAX_WALL')
        if maxcount and len(results) > maxcount:
            results = results[:maxcount]
            title = f"{title} (Top {len(results)})"
        ret = []
        for result in results:
            itm = dict(result)
            if not itm['BookLink']:
                itm['BookLink'] = ''
            elif itm['BookLink'].startswith('/works/OL'):
                itm['BookLink'] = CONFIG['OL_URL'] + itm['BookLink']

            if not itm.get('BookImg') or not itm['BookImg'].startswith('cache/'):
                itm['BookImg'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(itm['BookImg'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    itm['BookImg'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, itm['BookImg'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        itm['BookImg'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            ret.append(itm)
        return serve_template(
            templatename="coverwall.html", title=title, results=ret, redirect="books", have=have,
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def author_wall(self, have='1'):
        self.label_thread('AUTHORWALL')
        cmd = "SELECT Status,AuthorImg,AuthorID,AuthorName,HaveBooks,TotalBooks from authors "
        if have == '1':
            cmd += "where Status='Active' or Status='Wanted' order by AuthorName ASC"
            title = 'Active/Wanted Authors'
        else:
            cmd += "where Status !='Active' and Status != 'Wanted' order by AuthorName ASC"
            title = 'Inactive Authors'
        db = database.DBConnection()
        try:
            results = db.select(cmd)
        finally:
            db.close()
        if not len(results):
            raise cherrypy.HTTPRedirect("authors")

        ret = []
        for result in results:
            itm = dict(result)
            if not itm.get('AuthorImg') or not itm['AuthorImg'].startswith('cache/'):
                itm['AuthorImg'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(itm['AuthorImg'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    itm['AuthorImg'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, itm['AuthorImg'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        itm['AuthorImg'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            ret.append(itm)
        return serve_template(
            templatename="coverwall.html", title=title, results=ret, redirect="authors", have=have,
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def audio_wall(self):
        self.label_thread('AUDIOWALL')
        db = database.DBConnection()
        try:
            results = db.select(
                'SELECT AudioFile,BookImg,BookID,BookName from books '
                'where AudioStatus="Open" order by AudioLibrary DESC')
        finally:
            db.close()
        if not len(results):
            raise cherrypy.HTTPRedirect("audio")
        title = "Recent AudioBooks"
        maxcount = CONFIG.get_int('MAX_WALL')
        if maxcount and len(results) > maxcount:
            results = results[:maxcount]
            title = f"{title} (Top {len(results)})"
        ret = []
        for result in results:
            itm = dict(result)
            if not itm.get('BookImg') or not itm['BookImg'].startswith('cache/'):
                itm['BookImg'] = 'images/nocover.jpg'
            else:
                fname, extn = splitext(itm['BookImg'])
                imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                if path_isfile(imgfile):
                    itm['BookImg'] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                else:
                    imgfile = os.path.join(DIRS.CACHEDIR, itm['BookImg'][6:])
                    imgthumb = createthumb(imgfile, 200, False)
                    if imgthumb:
                        itm['BookImg'] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
            ret.append(itm)
        return serve_template(
            templatename="coverwall.html", title=title, results=ret, redirect="audio",
            columns=CONFIG.get_int('WALL_COLUMNS'))

    @cherrypy.expose
    @require_auth()
    def wall_columns(self, redirect=None, count=None, have='', title=''):
        title = title.split(' (')[0].replace(' ', '+')
        if not have:
            have = '1' if 'Wanted' in title else '0'
        columns = check_int(CONFIG.get_int('WALL_COLUMNS'), 6)
        if count == 'up' and columns <= 12:
            columns += 1
        elif count == 'down' and columns > 1:
            columns -= 1
        CONFIG.set_int('WALL_COLUMNS', columns)
        if redirect == 'audio':
            raise cherrypy.HTTPRedirect('audio_wall')
        if redirect == 'books':
            raise cherrypy.HTTPRedirect(f'book_wall?have={have}')
        if redirect == 'magazines':
            if title:
                raise cherrypy.HTTPRedirect(f'mag_wall?title={title}')
            raise cherrypy.HTTPRedirect('mag_wall')
        if redirect == 'comic':
            if title:
                raise cherrypy.HTTPRedirect(f'comic_wall?comicid={title}')
            raise cherrypy.HTTPRedirect('comic_wall')
        if redirect == 'authors':
            raise cherrypy.HTTPRedirect(f'author_wall?have={have}')
        raise cherrypy.HTTPRedirect('home')

    # COMICS #########################################################

    @cherrypy.expose
    @require_auth()
    def edit_comic(self, comicid=None):
        self.label_thread('EDIT_COMIC')
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            data = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
        finally:
            db.close()
        if data:
            return serve_template(templatename="editcomic.html", title="Edit Comic", config=data)
        logger.info(f'Missing comic {comicid}:')
        raise cherrypy.HTTPError(404, f"Comic ID {comicid} not found")

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    def comic_update(self, comicid='', new_name='', new_id='', aka='', editordata='', **kwargs):
        logger = logging.getLogger(__name__)
        self.check_permitted(lazylibrarian.perm_edit)
        db = database.DBConnection()
        comicdata = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
        if comicdata:
            edited = ""
            if comicdata["Title"] != new_name:
                edited += "Title "
            if comicdata["aka"] != aka:
                edited += "aka "
            if comicdata["Description"] != editordata:
                edited += "Description "

            if comicid != new_id:
                match = db.match('SELECT ComicID from comics where ComicID=?', (new_id,))
                if match:
                    logger.debug(f"Unable to use new ID, {new_id} already exists")
                else:
                    db.action('PRAGMA foreign_keys = OFF')
                    db.action("UPDATE comics SET comicid=? WHERE comicid=?", (new_id, comicid))
                    db.action("UPDATE comicissues SET comicid=? WHERE comicid=?", (new_id, comicid))
                    db.action('PRAGMA foreign_keys = ON')
                    logger.debug(f"Updated comicid {comicid} to {new_id}")
                    comicid = new_id

            if edited:
                control_value_dict = {'ComicID': comicid}
                new_value_dict = {
                    'Title': new_name,
                    'aka': aka,
                    'Description': editordata
                }
                db.upsert("comics", new_value_dict, control_value_dict)
                logger.info(f'Updated [ {edited}] for {comicdata["Title"]}')
            else:
                logger.debug(f'Comic [{comicdata["Title"]}] has not been changed')
            db.close()
            raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")
        logger.warning(f"Invalid comicid [{comicid}]")
        db.close()
        raise cherrypy.HTTPError(404, f"Comic ID {comicid} not found")

    @cherrypy.expose
    @require_auth()
    def search_for_comic(self, comicid=None):
        self.check_permitted(lazylibrarian.perm_search)
        TELEMETRY.record_usage_data()
        db = database.DBConnection()
        try:
            bookdata = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
        finally:
            db.close()
        if bookdata:
            # start searchthreads
            self.start_comic_search(comicid)
            raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def start_comic_search(self, comicid=None):
        self.check_permitted(lazylibrarian.perm_search)
        logger = logging.getLogger(__name__)
        if comicid:
            if CONFIG.use_any():
                threading.Thread(target=search_comics, name='SEARCHCOMIC', args=[comicid]).start()
                logger.debug(f"Searching for comic ID {comicid}")
            else:
                logger.warning("Not searching for comic, no download methods set, check config")
        else:
            logger.debug("ComicSearch called with no comic ID")

    @cherrypy.expose
    @require_auth()
    def comics(self, comic_filter=''):
        self.check_permitted(lazylibrarian.perm_comics)
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            user = cookie['ll_uid'].value
        else:
            user = 0
        # use server-side processing
        covers = 1
        if not CONFIG['TOGGLES']:
            covers = 0
        return serve_template(templatename="comics.html", title="Comics", comics=[],
                              covercount=covers, user=user, comic_filter=comic_filter)

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_comics(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        filtered = []
        rowlist = []
        userid = None
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            userid = cookie['ll_uid'].value
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            db = database.DBConnection()
            try:
                cmd = ("select comics.*,(select count(*) as counter from comicissues where "
                       "comics.comicid = comicissues.comicid) as Iss_Cnt from comics")

                mycomics = []
                if userid and userprefs & lazylibrarian.pref_mycomics:
                    res = db.select("SELECT WantID from subscribers WHERE Type='comic' and UserID=?", (userid,))
                    serversidelogger.debug(f"User subscribes to {len(res)} comics")
                    for mag in res:
                        mycomics.append(mag['WantID'])
                    cmd += " WHERE comics.comicid in (" + ", ".join(f"'{w}'" for w in mycomics) + ")"
                cmd += " order by Title"
                rowlist = db.select(cmd)
            finally:
                db.close()

            if len(rowlist):
                newrowlist = []
                for mag in rowlist:
                    mag = dict(mag)  # turn sqlite objects into dicts
                    entry = [mag['ComicID'], mag['LatestCover'], mag['Title'], mag['Iss_Cnt'], mag['LastAcquired'],
                             mag['LatestIssue'], mag['Status'], mag['IssueStatus'], mag['Start'],
                             mag['Publisher'], mag['Link'], mag['Genre']]
                    newrowlist.append(entry)  # add each rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    filtered = [x for x in newrowlist if sSearch.lower() in str(x).lower()]
                else:
                    filtered = newrowlist

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                if sortcolumn in [4, 5]:  # dates
                    self.natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                elif sortcolumn == 2:  # title
                    filtered.sort(key=lambda y: y[sortcolumn].lower() if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

                for row in rows:
                    if not row[1] or not row[1].startswith('cache/'):
                        row[1] = 'images/nocover.jpg'
                    else:
                        fname, extn = splitext(row[1])
                        imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                        if path_isfile(imgfile):
                            row[1] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                        else:
                            imgfile = os.path.join(DIRS.CACHEDIR, row[1][6:])
                            imgthumb = createthumb(imgfile, 200, False)
                            if imgthumb:
                                row[1] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                    row[4] = date_format(row[4], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                    if row[5] and row[5].isdigit():
                        if len(row[5]) == 8:
                            if check_year(row[5][:4]):
                                row[5] = f'Issue {int(row[5][4:])} {row[5][:4]}'
                            else:
                                row[5] = f'Vol {int(row[5][:4])} #{int(row[5][4:])}'
                        elif len(row[5]) == 12:
                            row[5] = f'Vol {int(row[5][4:8])} #{int(row[5][8:])} {row[5][:4]}'
                    else:
                        row[5] = date_format(row[5], CONFIG['ISS_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])

            serversidelogger.debug(f"get_comics returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_comics filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_comics: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  'loading': lazylibrarian.COMIC_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def comic_scan(self, **kwargs):
        self.check_permitted(lazylibrarian.perm_force)
        TELEMETRY.record_usage_data()
        logger = logging.getLogger(__name__)
        comicid = kwargs.get('comicid')

        name = 'COMICSCAN'
        if comicid:
            name = f'{name}_{comicid}'
        if name not in [n.name for n in list(threading.enumerate())]:
            try:
                if comicid:
                    threading.Thread(target=comicscan.comic_scan, name=name, args=[comicid]).start()
                else:
                    threading.Thread(target=comicscan.comic_scan, name=name, args=[]).start()
            except Exception as e:
                logger.error(f'Unable to complete the scan: {type(e).__name__} {str(e)}')
        else:
            logger.debug(f'{name} already running')
        if comicid:
            raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def comicissue_page(self, comicid):
        global lastcomic
        logger = logging.getLogger(__name__)
        self.check_permitted(lazylibrarian.perm_comics)
        db = database.DBConnection()
        try:
            mag_data = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
        finally:
            db.close()
        if not mag_data:
            logger.warning(f"Invalid comic ID: {comicid}")
            raise cherrypy.HTTPError(404, f"Comic ID {comicid} not found")

        title = mag_data['Title']
        if title and '&' in title and '&amp;' not in title:
            safetitle = title.replace('&', '&amp;')
        else:
            safetitle = title

        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            user = cookie['ll_uid'].value
        else:
            user = 0
        # use server-side processing
        if not CONFIG['TOGGLES']:
            covercount = 0
        else:
            covercount = 1

        # if we've changed comic, reset to first page of new comics issues
        if comicid == lastcomic:
            firstpage = 'false'
        else:
            lastcomic = comicid
            firstpage = 'true'

        return serve_template(templatename="comicissues.html", comicid=comicid,
                              title=safetitle, issues=[], covercount=covercount, user=user,
                              firstpage=firstpage)

    @cherrypy.expose
    @require_auth()
    def open_comic(self, comicid=None, issueid=None):
        self.check_permitted(lazylibrarian.perm_download)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            if comicid and '_' in comicid:
                comicid = comicid.split('_')[0]

            # we may want to open an issue with an issueid
            if comicid and issueid:
                cmd = ("SELECT Title,IssueFile from comics,comicissues WHERE comics.ComicID=comicissues.ComicID and "
                       "comics.ComicID=? and IssueID=?")
                iss_data = db.match(cmd, (comicid, issueid))
                if iss_data:
                    issue_file = iss_data["IssueFile"]
                    if issue_file and path_isfile(issue_file):
                        logger.debug(f'Opening file {issue_file}')
                        return self.send_file(issue_file, name=f"{iss_data['Title']} {issueid}"
                                                               f"{splitext(issue_file)[1]}")

            # or we may just have a comicid to find comic in comicissues table
            cmd = ("SELECT Title,IssueFile,IssueID from comics,comicissues WHERE comics.ComicID=comicissues.ComicID "
                   "and comics.ComicID=?")
            iss_data = db.select(cmd, (comicid,))
        finally:
            db.close()
        if len(iss_data) == 0:
            logger.warning(f"No issues for comic {comicid}")
            raise cherrypy.HTTPRedirect("comics")

        if len(iss_data) == 1 and CONFIG.get_bool('COMIC_SINGLE'):  # we only have one issue, get it
            title = iss_data[0]["Title"]
            issue_id = iss_data[0]["IssueID"]
            issue_file = iss_data[0]["IssueFile"]
            if issue_file and path_isfile(issue_file):
                logger.debug(f'Opening {comicid} - {issue_id}')
                return self.send_file(issue_file, name=f"{title} {issue_id}{splitext(issue_file)[1]}")
            logger.warning(f"No issue {issue_id} for comic {title}")
            raise cherrypy.HTTPError(404, f"Comic Issue {issue_id} not found for {title}")

        # multiple issues, show a list
        logger.debug(f"{comicid} has {len(iss_data)} {plural(len(iss_data), 'issue')}")
        raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_comic_issues(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0,
                         sSortDir_0="desc", sSearch="", **kwargs):
        rows = []
        filtered = []
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')

        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            comicid = kwargs['comicid']
            db = database.DBConnection()
            try:
                mag_data = db.match('SELECT * from comics WHERE ComicID=?', (comicid,))
                title = mag_data['Title']
                rowlist = db.select('SELECT * from comicissues WHERE ComicID=? order by IssueID DESC', (comicid,))
            finally:
                db.close()
            if len(rowlist):
                newrowlist = []
                for mag in rowlist:
                    mag = dict(mag)  # turn sqlite objects into dicts
                    entry = [title, mag['Cover'], mag['IssueID'], mag['IssueAcquired'], f"{comicid}_{mag['IssueID']}"]
                    newrowlist.append(entry)  # add each rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    filtered = [x for x in newrowlist if sSearch.lower() in str(x).lower()]
                else:
                    filtered = newrowlist

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                if sortcolumn in [2, 3]:  # dates
                    self.natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

            for row in rows:
                if not row[1] or not row[1].startswith('cache/'):
                    row[1] = 'images/nocover.jpg'
                else:
                    fname, extn = splitext(row[1])
                    imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                    if path_isfile(imgfile):
                        row[1] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                    else:
                        imgfile = os.path.join(DIRS.CACHEDIR, row[1][6:])
                        imgthumb = createthumb(imgfile, 200, False)
                        if imgthumb:
                            row[1] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                row[3] = date_format(row[3], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                row[2] = date_format(row[2], CONFIG['ISS_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])

            serversidelogger.debug(f"get_comic_issues returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_comic_issues filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_comic_issues: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  'loading': lazylibrarian.COMIC_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def find_comic(self, title=None, **kwargs):
        # search for a comic title and produce a list of likely matches
        # noinspection PyGlobalUndefined
        global comicresults
        logger = logging.getLogger(__name__)
        self.check_permitted(lazylibrarian.perm_search)
        TELEMETRY.record_usage_data()
        comicresults = []
        if not title or title == 'None':
            raise cherrypy.HTTPRedirect("comics")
        title = strip_quotes(title)
        db = database.DBConnection()
        exists = db.match('SELECT Title from comics WHERE Title=?', (title,))
        if exists:
            logger.debug(f"Comic {title} already exists ({exists['Title']})")
        else:
            cvres = cv_identify(title, best=False)
            if title.startswith('CV'):
                for itm in cvres:
                    itm['fuzz'] = fuzz.token_sort_ratio(title, itm['seriesid'])
                    comicresults.append(itm)
            else:
                cxres = cx_identify(title, best=False)
                words = name_words(title)
                titlewords = ' '.join(title_words(words))
                for itm in cvres:
                    itm['fuzz'] = fuzz.token_sort_ratio(titlewords, itm['title'])
                    comicresults.append(itm)
                for itm in cxres:
                    itm['fuzz'] = fuzz.token_sort_ratio(titlewords, itm['title'])
                    comicresults.append(itm)
                comicresults = sorted(comicresults, key=lambda x: -(check_int(x["fuzz"], 0)))
            comicids = db.select("SELECT ComicID from comics")
            comiclist = []
            for itm in comicids:
                comiclist.append(itm['ComicID'])
            return serve_template(templatename="comicresults.html", title="Comics",
                                  results=comicresults, comicids=comiclist)
        db.close()

        if kwargs.get('comicfilter'):
            raise cherrypy.HTTPRedirect("comics?comic_filter=" + kwargs.get('comicfilter'))
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def add_comic(self, comicid=None, **kwargs):
        # add a comic from a list in comicresults.html
        global comicresults
        logger = logging.getLogger(__name__)
        self.check_permitted(lazylibrarian.perm_comics)
        TELEMETRY.record_usage_data()
        apikey = CONFIG['CV_APIKEY']
        if not comicid or comicid == 'None':
            raise cherrypy.HTTPRedirect("comics")
        if comicid.startswith('CV') and not apikey:
            msg = "Please obtain an apikey from https://comicvine.gamespot.com/api/"
            logger.warning(msg)
            raise cherrypy.HTTPError(403, msg)

        self.validate_param("comicid", comicid, ['<', '&', '>', '=', '"', "'", '+', '(', ')'], 404)
        db = database.DBConnection()
        match = False
        exists = db.match('SELECT Title from comics WHERE ComicID=?', (comicid,))
        if exists:
            logger.debug(f"Comic {exists['Title']} already exists ({exists['comicid']})")
        else:
            try:
                for itm in comicresults:
                    if itm['seriesid'] == comicid:
                        aka = ''
                        akares = cv_identify(itm['title'])
                        if not akares:
                            akares = cx_identify(itm['title'])
                        if akares and akares[3]['seriesid'] != comicid:
                            aka = akares[3]['seriesid']
                        db.action('INSERT INTO comics (ComicID, Title, Status, Added, LastAcquired, ' +
                                  'Updated, LatestIssue, IssueStatus, LatestCover, SearchTerm, Start, ' +
                                  'First, Last, Publisher, Link, aka) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                  (comicid, itm['title'], 'Active', now(), None,
                                   now(), None, 'Wanted', None, itm['searchterm'], itm['start'],
                                   itm['first'], itm['last'], itm['publisher'], itm['link'], aka))
                        match = True
                        break
            except NameError:
                match = False
            if not match:
                msg = f"Failed to get data for {comicid}"
                logger.warning(msg)
                raise cherrypy.HTTPError(404, msg)

        if match and CONFIG.get_bool('IMP_AUTOSEARCH'):
            self.start_comic_search(comicid)
        db.close()
        if kwargs.get('comicfilter'):
            raise cherrypy.HTTPRedirect("comics?comic_filter=" + kwargs.get('comicfilter'))
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def mark_comics(self, action=None, **args):
        self.check_permitted(lazylibrarian.perm_status)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        args.pop('book_table_length', None)
        for itm in args:
            if action == "Paused" or action == "Active":
                control_value_dict = {"ComicID": itm}
                new_value_dict = {"Status": action}
                db.upsert("comics", new_value_dict, control_value_dict)
                logger.info(f'Status of comic {itm} changed to {action}')
            if action == "Delete":
                issues = db.select('SELECT IssueFile from comicissues WHERE ComicID=?', (itm,))
                logger.debug(f'Deleting comic {itm} from disc')
                issuedir = ''
                for issue in issues:  # delete all issues of this comic
                    result = self.delete_issue(issue['IssueFile'])
                    if result:
                        logger.debug(f'Issue {issue["IssueFile"]} deleted from disc')
                        issuedir = os.path.dirname(issue['IssueFile'])
                    else:
                        logger.debug(f'Failed to delete {issue["IssueFile"]}')

                # if the directory is now empty, delete that too
                if issuedir and CONFIG.get_bool('COMIC_DELFOLDER'):
                    magdir = os.path.dirname(issuedir)
                    try:
                        os.rmdir(syspath(magdir))
                        logger.debug(f'Comic directory {magdir} deleted from disc')
                    except OSError:
                        logger.debug(f'Comic directory {magdir} is not empty')
                    logger.info(f'Comic {itm} deleted from disc')

            if action == "Remove" or action == "Delete":
                db.action('DELETE from comics WHERE ComicID=?', (itm,))
                db.action('DELETE from wanted where BookID=?', (itm,))
                logger.info(f'Comic {itm} removed from database')
            if action == "Reset":
                control_value_dict = {"ComicID": itm}
                new_value_dict = {
                    "LastAcquired": '',
                    "LatestIssue": '',
                    "LatestCover": '',
                    "IssueStatus": "Wanted"
                }
                db.upsert("comics", new_value_dict, control_value_dict)
                logger.info(f'Comic {itm} details reset')

            if action == 'Subscribe':
                cookie = cherrypy.request.cookie
                if cookie and 'll_uid' in list(cookie.keys()):
                    userid = cookie['ll_uid'].value
                    res = db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                                   (userid, 'comic', itm))
                    if res:
                        logger.debug(f"User {userid} is already subscribed to {itm}")
                    else:
                        db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                                  (userid, 'comic', itm))
                        logger.debug(f"Subscribe {userid} to comic {itm}")
            if action == 'Unsubscribe':
                cookie = cherrypy.request.cookie
                if cookie and 'll_uid' in list(cookie.keys()):
                    userid = cookie['ll_uid'].value
                    db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                              (userid, 'comic', itm))
                    res = db.select('SELECT issueid from comicissues where comicid=?', (itm,))
                    for iss in res:
                        db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                  (userid, 'comic', iss['issueid']))
                    logger.debug(f"Unsubscribe {userid} to comic {itm}")
        db.close()
        raise cherrypy.HTTPRedirect("comics")

    @cherrypy.expose
    @require_auth()
    def mark_comic_issues(self, action=None, **args):
        self.check_permitted(lazylibrarian.perm_status)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        args.pop('book_table_length', None)
        comicid = None
        for itm in args:
            comicid, issueid = itm.split('_')
            cmd = ("SELECT IssueFile,Title,comics.ComicID from comics,comicissues WHERE "
                   "comics.ComicID = comicissues.ComicID and comics.ComicID=? and IssueID=?")
            issue = db.match(cmd, (comicid, issueid))
            if issue:
                if action == "Delete":
                    result = self.delete_issue(issue['IssueFile'])
                    if result:
                        logger.info(f'Issue {issueid} of {issue["Title"]} deleted from disc')
                if action == "Remove" or action == "Delete":
                    db.action('DELETE from comicissues WHERE ComicID=? and IssueID=?', (comicid, issueid))
                    logger.info(f'Issue {issueid} of {issue["Title"]} removed from database')
                    # Set issuedate to issuedate of most recent issue we have
                    # Set latestcover to most recent issue cover
                    # Set lastacquired to acquired date of most recent issue we have
                    # Set added to acquired date of the earliest issue we have
                    cmd = ("select IssueID,IssueAcquired,IssueFile from comicissues where ComicID=?"
                           " order by IssueID ")
                    newest = db.match(cmd + 'DESC', (comicid,))
                    oldest = db.match(cmd + 'ASC', (comicid,))
                    control_value_dict = {'ComicID': comicid}
                    if newest and oldest:
                        old_acquired = ''
                        new_acquired = ''
                        cover = ''
                        issuefile = newest['IssueFile']
                        if path_exists(issuefile):
                            cover = splitext(issuefile)[0] + '.jpg'
                            mtime = os.path.getmtime(syspath(issuefile))
                            new_acquired = datetime.date.isoformat(datetime.date.fromtimestamp(mtime))
                        issuefile = oldest['IssueFile']
                        if path_exists(issuefile):
                            mtime = os.path.getmtime(syspath(issuefile))
                            old_acquired = datetime.date.isoformat(datetime.date.fromtimestamp(mtime))

                        new_value_dict = {
                            'LatestIssue': newest['IssueID'],
                            'LatestCover': cover,
                            'LastAcquired': new_acquired,
                            'Added': old_acquired
                        }
                    else:
                        new_value_dict = {
                            'LatestIssue': '',
                            'LastAcquired': '',
                            'LatestCover': '',
                            'Added': ''
                        }
                    db.upsert("comics", new_value_dict, control_value_dict)
        db.close()
        if comicid:
            raise cherrypy.HTTPRedirect(f"comicissue_page?comicid={comicid}")

        raise cherrypy.HTTPRedirect("comics")

    # MAGAZINES #########################################################

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_mags(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        filtered = []
        rowlist = []
        userid = None
        userprefs = 0
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            userid = cookie['ll_uid'].value
        if cookie and 'll_prefs' in list(cookie.keys()):
            userprefs = check_int(cookie['ll_prefs'].value, 0)
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            db = database.DBConnection()
            try:
                cmd = ("select magazines.*,(select count(*) as counter from issues where "
                       "magazines.title = issues.title) as Iss_Cnt from magazines")

                if userid and userprefs & lazylibrarian.pref_mymags:
                    res = db.select("SELECT WantID from subscribers WHERE Type='magazine' and UserID=?", (userid,))
                    serversidelogger.debug(f"User subscribes to {len(res)} magazines")
                    maglist = ''
                    for mag in res:
                        if maglist:
                            maglist += ', '
                        maglist += f'"{mag["WantID"]}"'
                    cmd += " WHERE Title in (" + maglist + ")"
                cmd += " order by Title"

                serversidelogger.debug(cmd)
                rowlist = db.select(cmd)
            finally:
                db.close()

            if len(rowlist):
                newrowlist = []
                for mag in rowlist:
                    mag = dict(mag)  # turn sqlite objects into dicts
                    entry = [mag['Title'], mag['LatestCover'], quote(mag['Title']), mag['Iss_Cnt'], mag['LastAcquired'],
                             mag['IssueDate'], mag['Status'], mag['IssueStatus'], mag['Genre']]

                    newrowlist.append(entry)  # add each rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    filtered = [x for x in newrowlist if sSearch.lower() in str(x).lower()]
                else:
                    filtered = newrowlist

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                if sortcolumn in [4, 5]:  # dates
                    self.natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                elif sortcolumn == 2:  # title
                    filtered.sort(key=lambda y: y[sortcolumn].lower() if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

                for row in rows:
                    row[4] = date_format(row[4], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                    if row[5] and row[5].isdigit():
                        if len(row[5]) == 8:
                            if check_year(row[5][:4]):
                                row[5] = f'Issue {int(row[5][4:])} {row[5][:4]}'
                            else:
                                row[5] = f'Vol {int(row[5][:4])} #{int(row[5][4:])}'
                        elif len(row[5]) == 12:
                            row[5] = f'Vol {int(row[5][4:8])} #{int(row[5][8:])} {row[5][:4]}'
                    else:
                        row[5] = date_format(row[5], CONFIG['ISS_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])

                    if not row[1] or not row[1].startswith('cache/'):
                        row[1] = 'images/nocover.jpg'
                    else:
                        fname, extn = splitext(row[1])
                        imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                        fullsize = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}{extn}')
                        if path_isfile(imgfile):
                            row[1] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                        else:
                            imgfile = os.path.join(DIRS.CACHEDIR, row[1][6:])
                            imgthumb = createthumb(imgfile, 200, False)
                            if imgthumb:
                                row[1] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                        row.append(f"cache/{fullsize[len(DIRS.CACHEDIR):].lstrip(os.sep)}")

            serversidelogger.debug(f"get_mags returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_mags filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_mags: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  'loading': lazylibrarian.MAG_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def magazines(self, mag_filter=''):
        self.check_permitted(lazylibrarian.perm_magazines)
        db = database.DBConnection()
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            user = cookie['ll_uid'].value
            res = db.match('SELECT SendTo from users where UserID=?', (user,))
            if res and res['SendTo']:
                email = res['SendTo']
            else:
                email = ''
        else:
            user = 0
            email = ''
        db.close()
        # use server-side processing
        covers = 1
        if not CONFIG['TOGGLES']:
            covers = 0
        return serve_template(templatename="magazines.html", title="Magazines", magazines=[],
                              covercount=covers, user=user, email=email, mag_filter=mag_filter)

    @cherrypy.expose
    @require_auth()
    def edit_mag(self, mag=None):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('EDIT_MAG')
        TELEMETRY.record_usage_data()
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        try:
            magdata = db.match("SELECT Title from magazines WHERE Title=? COLLATE NOCASE", (mag,))
        finally:
            db.close()

        if magdata:
            return serve_template(templatename="editmag.html", title=f"Rename Magazine {magdata['Title']}",
                                  config=magdata)
        logger.error(f'Missing magazine {mag}')
        raise cherrypy.HTTPRedirect("magazines")

    # noinspection PyBroadException
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def magazine_update_ajax(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.check_permitted(lazylibrarian.perm_edit)
        logger = logging.getLogger(__name__)
        summary = ''
        passed = 0
        failed = 0
        new_title = kwargs.get('new_title')
        old_title = kwargs.get('old_title')
        if not old_title and not new_title:
            summary = 'Insufficient information, need Old and New Title'
        if not summary and old_title == new_title:
            summary = f'Title for {old_title} unchanged'
        if not summary:
            valid = self.validate_param("magazine title", new_title, ['<', '>', '='], None)
            if not valid:
                summary = 'Invalid new title, unable to rename'
        if not summary:
            db = database.DBConnection()
            res = db.match("SELECT Title from magazines WHERE Title=? COLLATE NOCASE", (new_title,))
            if res:
                summary = f'Title {new_title} already exists, unable to rename'
            db.close()
        if not summary:
            logger.debug(f"Changing title [{old_title}] to [{new_title}]")
            db = database.DBConnection()
            try:
                db.action('PRAGMA foreign_keys = OFF')
                db.action("UPDATE magazines SET Title=? WHERE Title=? COLLATE NOCASE", (new_title, old_title))
                db.action("UPDATE issues SET Title=? WHERE Title=? COLLATE NOCASE", (new_title, old_title))
                db.action('PRAGMA foreign_keys = ON')
                db.commit()

                summary = f'Renamed {old_title} to {new_title}'

                # rename files/folders to match, and issuefile to match new location
                issues = db.select("SELECT IssueDate,IssueFile,IssueID from issues WHERE Title=?", (new_title,))
                total_items = len(issues)
                current_item = 0
                for issue in issues:
                    current_item += 1
                    current_percent = int(current_item * 100 / total_items)
                    self.issues_data = f"{current_item}/{total_items}/{current_percent}"
                    calibre_id = None
                    if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                        dbentry = db.match('SELECT * from issues WHERE IssueID=?', (issue['IssueID'],))
                        data = dict(dbentry)
                        data['Title'] = old_title
                        calibre_id = get_calibre_id(data, try_filename=False)
                        if calibre_id:
                            logger.debug(f"Found calibre ID {calibre_id} for {old_title} {issue['IssueDate']}")
                    fname, err = rename_issue(issue['IssueID'])
                    if err:
                        logger.warning(f"Failed to move file {issue['IssueFile']}: {err}")
                        failed += 1
                        continue
                    logger.debug(f"Renamed {issue['IssueDate']} to {os.path.basename(fname)}")
                    passed += 1
                    if calibre_id:
                        res, err, rc = calibredb('remove', [calibre_id])
                        logger.debug(f"Remove result: {res} [{err}] {rc}")
                        dbentry = db.match('SELECT * from issues WHERE IssueID=?', (issue['IssueID'],))
                        data = dict(dbentry)
                        magentry = db.match('SELECT Genre from magazines WHERE Title=?', (data['Title'],))
                        data['mag_genres'] = magentry['Genre']
                        res, filename, pp_path = send_mag_issue_to_calibre(data)
                        logger.debug(f"Add result: {res}")
                        if res and filename:
                            # calibre may have renamed it
                            db.action("UPDATE issues SET IssueFile=? WHERE IssueID=?", (filename, issue['IssueID']))
            except Exception:
                logger.error(f'Unhandled exception in magazine_update: {traceback.format_exc()}')
            finally:
                db.close()
        self.issues_data = ''
        # Return JSON response instead of redirect
        total = passed + failed
        if not summary:
            summary = "Rename completed. "
        return {
            'success': True,
            'passed': passed,
            'failed': failed,
            'total': total,
            'title': new_title,
            'summary': summary
        }

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_issues(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        rows = []
        filtered = []
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            if not CONFIG.get_bool('USER_ACCOUNTS'):
                perm = lazylibrarian.perm_admin
            else:
                perm = 0
                cookie = cherrypy.request.cookie
                if cookie and 'll_uid' in list(cookie.keys()):
                    db = database.DBConnection()
                    res = db.match('SELECT Perms from users where UserID=?', (cookie['ll_uid'].value,))
                    if res:
                        perm = check_int(res['Perms'], 0)
                    db.close()

            title = kwargs['title'].replace('&amp;', '&')
            db = database.DBConnection()
            rowlist = db.select('SELECT * from issues WHERE Title=? order by IssueDate DESC', (title,))
            db.close()
            if len(rowlist):
                newrowlist = []
                for mag in rowlist:
                    mag = dict(mag)  # turn sqlite objects into dicts
                    entry = [mag['Title'], mag['Cover'], mag['IssueDate'], mag['IssueAcquired'],
                             mag['IssueID']]
                    newrowlist.append(entry)  # add each rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    filtered = [x for x in newrowlist if sSearch.lower() in str(x).lower()]
                else:
                    filtered = newrowlist

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                if sortcolumn in [2, 3]:  # dates
                    self.natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

            for row in rows:
                if not row[1] or not row[1].startswith('cache/'):
                    row[1] = 'images/nocover.jpg'
                else:
                    fname, extn = splitext(row[1])
                    imgfile = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}_w200{extn}')
                    fullsize = os.path.join(DIRS.CACHEDIR, f'{fname[6:]}{extn}')
                    if path_isfile(imgfile):
                        row[1] = f"cache/{imgfile[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                    else:
                        imgfile = os.path.join(DIRS.CACHEDIR, row[1][6:])
                        imgthumb = createthumb(imgfile, 200, False)
                        if imgthumb:
                            row[1] = f"cache/{imgthumb[len(DIRS.CACHEDIR):].lstrip(os.sep)}"
                    row.append(f"cache/{fullsize[len(DIRS.CACHEDIR):].lstrip(os.sep)}")
                row[3] = date_format(row[3], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                if row[2] and row[2].isdigit():
                    if len(row[2]) == 8:
                        # Year/Issue or Volume/Issue with no year
                        if check_year(row[2][:4]):
                            row[2] = f'{row[2][:4]} Issue {int(row[2][4:])}'
                        else:
                            row[2] = f'Vol {int(row[2][:4])} #{int(row[2][4:])}'
                    elif len(row[2]) == 12:
                        row[2] = f'{row[2][:4]} Vol {int(row[2][4:8])} #{int(row[2][8:])}'
                else:
                    row[2] = date_format(row[2], CONFIG['ISS_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])
                if perm & lazylibrarian.perm_edit:
                    row[2] = row[2] + '<br><a href="edit_issue?issueid=' + row[4] + '"><small><i>Edit</i></a>'

            serversidelogger.debug(f"get_issues returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_issues filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_issues: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  'loading': lazylibrarian.MAG_UPDATE,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def edit_issue(self, issueid=None):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        self.label_thread('EDIT_ISSUE')
        TELEMETRY.record_usage_data()
        db = database.DBConnection()
        try:
            issuedata = db.match("SELECT Title,IssueDate,IssueID,IssueFile from issues WHERE IssueID=?", (issueid,))
        finally:
            db.close()

        if issuedata:
            tagdict = read_pdf_tags(issuedata['IssueFile'])
            return serve_template(templatename="editissue.html", title="Edit Issue", config=issuedata, tags=tagdict)
        logger.error(f"Missing issue {issueid}")
        return None

    @cherrypy.expose
    @require_auth()
    def issue_update(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.check_permitted(lazylibrarian.perm_edit)
        logger = logging.getLogger(__name__)
        issueid = kwargs.get('issueid')
        if not issueid:
            logger.debug('Invalid or missing IssueID')
            raise cherrypy.HTTPRedirect("magazines")

        magtitle = kwargs.get('magtitle')
        issuenum = kwargs.get('issuenum')
        db = database.DBConnection()
        magazine = db.match("SELECT DateType,IssueDate from magazines WHERE Title=? COLLATE NOCASE", (magtitle,))
        datetype = magazine['DateType']
        mostrecentissue = magazine['IssueDate']
        issue = db.match("SELECT Title,IssueDate,IssueFile,Cover,IssueID from issues WHERE IssueID=?", (issueid,))
        redirect = issue['Title']
        dateparts = get_dateparts(issuenum, datetype=datetype)
        if not dateparts['style']:
            datetype_ok = False
        else:
            datetype_ok = True
            if datetype:
                # check all wanted parts are in the regex result
                # Day Month Year Vol Iss (MM needs two months)

                if 'M' in datetype and dateparts['style'] not in [1, 2, 3, 4, 5, 6, 7, 12]:
                    datetype_ok = False
                if 'D' in datetype and dateparts['style'] not in [3, 5, 6]:
                    datetype_ok = False
                if 'MM' in datetype and dateparts['style'] not in [1]:  # bi monthly
                    datetype_ok = False
                if 'V' in datetype and dateparts['style'] not in [2, 8, 9, 10, 11, 12, 13, 14, 17, 18]:
                    datetype_ok = False
                if 'I' in datetype and dateparts['style'] not in [2, 10, 11, 12, 13, 14, 16, 17, 18]:
                    datetype_ok = False
                if 'Y' in datetype and dateparts['style'] not in [1, 2, 3, 4, 5, 6, 7, 8, 10,
                                                                  12, 13, 15, 16, 18]:
                    datetype_ok = False

        if not datetype_ok:
            response = f'Date {issuenum} not in a recognised date format [{datetype}]'
            logger.debug(response)
            db.close()
            raise cherrypy.HTTPRedirect(f"issue_page?title={quote(redirect)}&response={response}")

        if not magtitle and issuenum:
            response = (f"Issue {issue['IssueDate']} of {issue['Title']} is unchanged. "
                        f"Insufficient information, need Title and valid IssueNum/Date")
            logger.debug(response)
            db.close()
            raise cherrypy.HTTPRedirect(f"issue_page?title={quote(redirect)}&response={response}")

        old_path = os.path.dirname(issue['IssueFile'])
        edited = ''
        if issue["Title"] != magtitle:
            edited = 'Title '
        if issue["IssueDate"] != issuenum:
            edited += 'Date/Num '
        new_tags = {}
        for itm in kwargs:
            if itm.startswith('tags_/'):
                new_tags[itm[5:]] = kwargs[itm]
        try:
            old_tags = eval(kwargs['tagdata'])
        except SyntaxError:
            old_tags = None
        if not isinstance(old_tags, dict):
            logger.warning("Invalid old_tags dictionary")
            old_tags = {}
        if old_tags == new_tags:
            logger.debug("No tag changes")
        else:
            edited += 'Tags '
        if edited:
            if issue["Title"] != magtitle:
                if not magazine:
                    if not magtitle:
                        logger.warning("Missing magazine title")
                        raise cherrypy.HTTPError(404, "Magazine title missing")

                    self.validate_param("magazine title", magtitle, ['<', '>', '='], 404)
                    logger.debug(f"Magazine title [{magtitle}] not found, adding it")
                    control_value_dict = {"Title": magtitle}
                    new_value_dict = {"LastAcquired": today(),
                                      "IssueStatus": CONFIG['FOUND_STATUS'],
                                      "IssueDate": "", "LatestCover": ""}
                    db.upsert("magazines", new_value_dict, control_value_dict)
                db.action("UPDATE issues SET Title=? WHERE IssueID=?", (magtitle, issue['IssueID']))
            db.action("UPDATE issues SET IssueDate=? WHERE IssueID=?", (issuenum, issue['IssueID']))

            fname, err = rename_issue(issue['IssueID'], tags=new_tags)
            response = (f'Issue {issue["IssueDate"]} of {issue["Title"]}, changed to '
                        f'{os.path.basename(fname)} {edited}')
            if err:
                raise cherrypy.HTTPError(404, f"Magazine IssueFile {issue['IssueFile']} move failed: {err}")

            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                calibre_id = get_calibre_id(issue, try_filename=False)
                if calibre_id:
                    logger.debug(f"Found calibre ID {calibre_id} for {issue['Title']} {issue['IssueDate']}")
                    res, err, rc = calibredb('remove', [calibre_id])
                    logger.debug(f"Remove result: {res} [{err}] {rc}")
                    dbentry = db.match('SELECT * from issues WHERE IssueID=?', (issue['IssueID'],))
                    data = dict(dbentry)
                    magentry = db.match('SELECT Genre from magazines WHERE Title=?', (data['Title'],))
                    data['mag_genres'] = magentry['Genre']
                    res, filename, pp_path = send_mag_issue_to_calibre(data)
                    logger.debug(f"Add result: {res}")
                    if res and filename:
                        db.action("UPDATE issues SET IssueFile=? WHERE IssueID=?", (filename, issue['IssueID']))

            # if no magazine issues left in the folder, delete it
            # (removes any trailing cover images, opf etc)
            remove_if_empty(old_path)

            if mostrecentissue:
                if mostrecentissue.isdigit() and str(issuenum).isdigit():
                    older = (int(mostrecentissue) > int(issuenum))  # issuenumber
                else:
                    older = (mostrecentissue > issuenum)  # YYYY-MM-DD
            else:
                older = False

            control_value_dict = {"Title": magtitle}
            if older:
                new_value_dict = {"LastAcquired": today(),
                                  "IssueStatus": CONFIG['FOUND_STATUS']}
            else:
                new_value_dict = {"LastAcquired": today(),
                                  "IssueStatus": CONFIG['FOUND_STATUS'],
                                  "IssueDate": issuenum,
                                  "LatestCover": issue['Cover']}
            db.upsert("magazines", new_value_dict, control_value_dict)
            if self.mag_set_latest(issue['Title']):
                # update latest issue of old mag title, if any issues left, redirect to there
                redirect = issue['Title']
            else:
                # no issues under old title, redirect to new title
                redirect = magtitle
        else:
            response = f'Issue {issue["IssueDate"]} of {issue["Title"]} is unchanged'
            logger.debug(response)
        db.close()
        raise cherrypy.HTTPRedirect(f"issue_page?title={quote(redirect)}&response={response}")

    @cherrypy.expose
    @require_auth()
    def issue_page(self, title, response=''):
        global lastmagazine
        self.check_permitted(lazylibrarian.perm_magazines)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        res = db.match('SELECT Title from magazines where Title=? COLLATE NOCASE', (title,))
        if res:
            title = res['Title']
        db.close()
        if not res:
            logger.warning(f"Unknown magazine title: {title}")
            raise cherrypy.HTTPError(404, f"Magazine title {title} not found")

        if title and '&' in title and '&amp;' not in title:  # could use htmlparser but seems overkill for just '&'
            safetitle = title.replace('&', '&amp;')
        else:
            safetitle = title

        # if we've changed magazine, reset to first page of new magazines issues
        if title == lastmagazine:
            firstpage = 'false'
        else:
            lastmagazine = title
            firstpage = 'true'

        # use server-side processing
        if not CONFIG['TOGGLES']:
            covercount = 0
        else:
            covercount = 1

        user = 0
        email = ''
        cookie = cherrypy.request.cookie
        if cookie and 'll_uid' in list(cookie.keys()):
            user = cookie['ll_uid'].value
            db = database.DBConnection()
            try:
                res = db.match('SELECT SendTo from users where UserID=?', (user,))
            finally:
                db.close()
            if res and res['SendTo']:
                email = res['SendTo']
        self.issues_data = ''
        return serve_template(templatename="issues.html", title=safetitle, issues=[], covercount=covercount,
                              user=user, email=email, firstpage=firstpage, response=response)

    @cherrypy.expose
    def abort_progress(self):
        logger = logging.getLogger(__name__)
        lazylibrarian.MARK_ISSUES = False
        logger.warning('Mark Issues/Magazines Aborted by user')
        return False

    @cherrypy.expose
    def test_progress(self):
        return lazylibrarian.test_data

    @cherrypy.expose
    def issues_progress(self):
        current = '0'
        total = '0'
        percent = '0'
        try:
            current, total, percent = self.issues_data.split('/')
        except ValueError:
            with contextlib.suppress(ValueError):
                current, total, percent = lazylibrarian.magazinescan_data.split('/')
        bar = ('<div class="progress center-block" style="width: 70%;"><div class="progress-bar-info'
               f' progress-bar progress-bar-striped" role="progressbar aria-valuenow="{percent}"'
               f' aria-valuemin="0" aria-valuemax="100" style="width:{percent}%;">'
               f'<span class="progressbar-front-text">{current}/{total}</span></div></div>')
        return bar

    @cherrypy.expose
    def magazinescan_progress(self):
        try:
            current, total, percent = lazylibrarian.magazinescan_data.split('/')
        except ValueError:
            return lazylibrarian.magazinescan_data

        bar = ('<div class="text-center">Scanning Library ...<br></div>'
               '<div class="progress center-block" style="width: 90%;"><div class="progress-bar-info'
               f' progress-bar progress-bar-striped" role="progressbar aria-valuenow="{percent}"'
               f' aria-valuemin="0" aria-valuemax="100" style="width:{percent}%;">'
               f'<span class="progressbar-front-text">{current}/{total}</span></div></div>')
        return bar

    @cherrypy.expose
    def libraryscan_progress(self):
        try:
            current, total, percent = lazylibrarian.libraryscan_data.split('/')
        except ValueError:
            return lazylibrarian.libraryscan_data

        bar = ('<div class="text-center">Scanning Library Folders<br></div>'
               '<div class="progress center-block" style="width: 90%;"><div class="progress-bar-info'
               f' progress-bar progress-bar-striped" role="progressbar aria-valuenow="{percent}"'
               f' aria-valuemin="0" aria-valuemax="100" style="width:{percent}%;">'
               f'<span class="progressbar-front-text">{current}/{total}</span></div></div>')
        return bar

    @cherrypy.expose
    @require_auth()
    def past_issues(self, mag=None, **kwargs):
        self.check_permitted(lazylibrarian.perm_magazines)
        if not mag or mag == 'None':
            title = "Past Issues"
        else:
            title = mag
        which_status = kwargs.get('whichStatus', '')
        if not which_status or which_status == 'None':
            which_status = "Skipped"
        return serve_template(
            templatename="manageissues.html", title=title, issues=[], whichStatus=which_status, mag=mag)

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_past_issues(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc",
                        sSearch="", **kwargs):
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        # kwargs is used by datatables to pass params
        rows = []
        filtered = []
        db = database.DBConnection()
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            # need to filter on whichStatus and optional mag title
            cmd = "SELECT NZBurl, NZBtitle, NZBdate, Auxinfo, NZBprov from pastissues WHERE Status=?"
            args = [kwargs['whichStatus']]
            if 'mag' in kwargs and kwargs['mag'] != 'None':
                cmd += " AND BookID=?"
                args.append(kwargs['mag'].replace('&amp;', '&'))

            serversidelogger.debug(f"get_past_issues {cmd}: {str(args)}")
            rowlist = db.select(cmd, tuple(args))
            if len(rowlist):
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    entry = list(row)  # turn sqlite objects into lists
                    rows.append(entry)  # add the rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    filtered = [x for x in rows if sSearch.lower() in str(x).lower()]
                else:
                    filtered = rows

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                              reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    rows = filtered
                else:
                    rows = filtered[displaystart:(displaystart + displaylength)]

                for row in rows:  # iterate through the sqlite3.Row objects
                    # title needs spaces for column resizing
                    title = row[1]
                    title = title.replace('.', ' ')
                    row[1] = title
                    # make this shorter and with spaces for column resizing
                    provider = row[4]
                    if len(provider) > 20:
                        while len(provider) > 20 and '/' in provider:
                            provider = provider.split('/', 1)[1]
                        provider = provider.replace('/', ' ')
                        row[4] = provider

            serversidelogger.debug(f"get_past_issues returning {displaystart} to {displaystart + displaylength}")
            serversidelogger.debug(f"get_past_issues filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_past_issues: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        db.close()
        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  }
        serversidelogger.debug(str(mydict))
        return mydict

    @cherrypy.expose
    @require_auth()
    def send_mag(self, bookid=None):
        return self.open_mag(bookid=bookid, email=True)

    @cherrypy.expose
    @require_auth()
    def open_mag(self, bookid=None, email=False):
        logger = logging.getLogger(__name__)
        self.check_permitted(lazylibrarian.perm_download)
        db = database.DBConnection()
        try:
            # we may want to open an issue with a hashed bookid
            mag_data = db.match('SELECT * from issues WHERE IssueID=?', (bookid,))
            if mag_data:
                issue_file = mag_data["IssueFile"]
                if issue_file and path_isfile(issue_file):
                    if email:
                        logger.debug(f'Emailing file {issue_file}')
                    else:
                        logger.debug(f'Opening file {issue_file}')
                    return self.send_file(issue_file, name=f"{mag_data['Title']} {mag_data['IssueDate']}"
                                                           f"{splitext(issue_file)[1]}", email=email)

            # or we may just have a title to find magazine in issues table
            mag_data = db.match('SELECT * from magazines WHERE Title=? COLLATE NOCASE', (unquote(bookid),))
            if not mag_data:
                logger.warning(f"Unknown magazine title: {bookid}")
                raise cherrypy.HTTPError(404, f"Magazine {bookid} not found")
            bookid = mag_data['Title']
            mag_data = db.select('SELECT * from issues WHERE Title=? COLLATE NOCASE', (bookid,))
        finally:
            db.close()

        if len(mag_data) == 1 and CONFIG.get_bool('MAG_SINGLE'):  # we only have one issue, get it
            issue_date = mag_data[0]["IssueDate"]
            issue_file = mag_data[0]["IssueFile"]
            if issue_file and path_isfile(issue_file):
                if email:
                    logger.debug(f'Emailing {bookid} - {issue_date}')
                else:
                    logger.debug(f'Opening {bookid} - {issue_date}')
                return self.send_file(issue_file, name=f"{bookid} {issue_date}{splitext(issue_file)[1]}",
                                      email=email)
            logger.warning(f"No issue {issue_date} for magazine {bookid}")
            raise cherrypy.HTTPRedirect("magazines")
        if len(mag_data) == 0:
            logger.warning(f"No issues found for magazine {bookid}")
            raise cherrypy.HTTPRedirect("magazines")
        # multiple issues, show a list
        logger.debug(f"{bookid} has {len(mag_data)} {plural(len(mag_data), 'issue')}")
        raise cherrypy.HTTPRedirect(f"issue_page?title={quote(bookid)}")

    @cherrypy.expose
    @require_auth()
    def mark_past_issues(self, action=None, **args):
        self.check_permitted(lazylibrarian.perm_status)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        maglist = []
        args.pop('book_table_length', None)

        for nzburl in args:
            nzburl = make_unicode(nzburl)
            # some NZBurl have &amp;  some have just & so need to try both forms
            if '&' in nzburl and '&amp;' not in nzburl:
                nzburl2 = nzburl.replace('&', '&amp;')
            elif '&amp;' in nzburl:
                nzburl2 = nzburl.replace('&amp;', '&')
            else:
                nzburl2 = ''

            if not nzburl2:
                title = db.select('SELECT * from pastissues WHERE NZBurl=?', (nzburl,))
            else:
                title = db.select('SELECT * from pastissues WHERE NZBurl=? OR NZBurl=?', (nzburl, nzburl2))

            for itm in title:
                nzburl = itm['NZBurl']
                if action == 'Remove':
                    db.action('DELETE from pastissues WHERE NZBurl=?', (nzburl,))
                    logger.debug(f'Item {itm["NZBtitle"]} removed from past issues')
                    maglist.append({'nzburl': nzburl})
                elif action == 'Wanted':
                    bookid = itm['BookID']
                    nzbprov = itm['NZBprov']
                    nzbtitle = itm['NZBtitle']
                    nzbmode = itm['NZBmode']
                    nzbsize = itm['NZBsize']
                    auxinfo = itm['AuxInfo']
                    maglist.append({
                        'bookid': bookid,
                        'nzbprov': nzbprov,
                        'nzbtitle': nzbtitle,
                        'nzburl': nzburl,
                        'nzbmode': nzbmode
                    })
                    # copy into wanted table
                    control_value_dict = {'NZBurl': nzburl}
                    new_value_dict = {
                        'BookID': bookid,
                        'NZBtitle': nzbtitle,
                        'NZBdate': now(),
                        'NZBprov': nzbprov,
                        'Status': action,
                        'NZBsize': nzbsize,
                        'AuxInfo': auxinfo,
                        'NZBmode': nzbmode
                    }
                    db.upsert("wanted", new_value_dict, control_value_dict)

                elif action in ['Ignored', 'Skipped']:
                    db.action('UPDATE pastissues set status=? WHERE NZBurl=?', (action, nzburl))
                    logger.debug(f'Item {itm["NZBtitle"]} marked {action} in past issues')
                    maglist.append({'nzburl': nzburl})
        db.close()

        if action == 'Remove':
            logger.info(f'Removed {len(maglist)} {plural(len(maglist), "item")} from past issues')
        else:
            logger.info(f'Status set to {action} for {len(maglist)} past {plural(len(maglist), "issue")}')
        # start searchthreads
        if action == 'Wanted':
            threading.Thread(target=download_maglist, name='DL-MAGLIST', args=[maglist, 'wanted']).start()
        raise cherrypy.HTTPRedirect("past_issues")

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_issues_ajax(self, action=None, **args):
        self.check_permitted(lazylibrarian.perm_status)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        passed = 0
        failed = 0
        title = ''
        args.pop('book_table_length', None)
        lazylibrarian.MARK_ISSUES = True
        if action:
            total_items = len(args)
            for current_item, itm in enumerate(args, start=1):
                if not lazylibrarian.MARK_ISSUES:
                    break
                current_percent = int(current_item * 100 / total_items)
                self.issues_data = f"{current_item}/{total_items}/{current_percent}"
                issue = db.match('SELECT IssueFile,Title,IssueDate,Cover from issues WHERE IssueID=?', (itm,))
                if issue:
                    issue = dict(issue)
                    title = issue['Title']
                    issuefile = issue['IssueFile']
                    if not issuefile or not path_exists(issuefile):
                        logger.error(f"No IssueFile found for IssueID {itm}")
                        issuefile = None

                    if 'reCover' in action and issuefile:
                        coverfile = create_mag_cover(issuefile, refresh=True,
                                                     pagenum=check_int(action[-1], 1))
                        if coverfile:
                            myhash = uuid.uuid4().hex
                            hashname = os.path.join(DIRS.CACHEDIR, 'magazine', f'{myhash}.jpg')
                            copyfile(coverfile, hashname)
                            setperm(hashname)
                            control_value_dict = {"IssueFile": issue['IssueFile']}
                            newcover = f'cache/magazine/{myhash}.jpg'
                            new_value_dict = {"Cover": newcover}
                            db.upsert("Issues", new_value_dict, control_value_dict)
                            latest = db.match("select Title,LatestCover,IssueDate from magazines "
                                              "where title=? COLLATE NOCASE", (title,))
                            if latest:
                                title = latest['Title']
                                if latest['IssueDate'] == issue['IssueDate'] and latest['LatestCover'] != newcover:
                                    db.action("UPDATE magazines SET LatestCover=? "
                                              "WHERE Title=? COLLATE NOCASE", (newcover, title))
                            issue['Cover'] = newcover
                            issue['CoverFile'] = coverfile  # for updating calibre cover
                            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                                self.update_calibre_issue_cover(issue)
                            passed += 1
                        else:
                            failed += 1
                            logger.warning(f"No coverfile created for IssueID {itm} {issuefile}")

                    if action == 'tag' and issuefile:
                        logger.debug(f"Tagging {issuefile}")
                        entry = db.match('SELECT Language,Genre FROM magazines where Title=?', (title,))
                        genres = entry[1]
                        tags = {}
                        cnt = 1
                        for itm in get_list(genres):
                            tags[f'/Genre_{cnt}'] = itm
                            cnt += 1
                        try:
                            res = write_pdf_tags(issuefile, title, issue['IssueDate'], tags)
                        except Exception as e:
                            logger.error(f"Failed to tag {issuefile}: {e}")
                            res = False
                        if not res:
                            failed += 1
                        else:
                            passed += 1
                            if CONFIG.get_bool('IMP_MAGOPF'):
                                logger.debug(f"Writing opf for {issuefile}")
                                _, _ = lazylibrarian.metadata_opf.create_mag_opf(issuefile, title,
                                                                                 issue['IssueDate'], itm,
                                                                                 language=entry[0],
                                                                                 genres=genres,
                                                                                 overwrite=True)
                    if action == 'coverswap' and issuefile:
                        coverfile = None
                        if CONFIG['MAG_COVERSWAP']:
                            params = [CONFIG['MAG_COVERSWAP'], issuefile]
                            logger.debug(f"Coverswap {params}")
                            try:
                                res = subprocess.check_output(params, stderr=subprocess.STDOUT)
                                logger.info(res)
                                coverfile = create_mag_cover(issuefile, refresh=True, pagenum=1)
                            except subprocess.CalledProcessError as e:
                                logger.warning(e.output)
                        else:
                            res = coverswap(issuefile, 2)  # cover from page 2 (counted from 1)
                            if res:
                                coverfile = create_mag_cover(issuefile, refresh=True, pagenum=1)
                        if coverfile:
                            myhash = uuid.uuid4().hex
                            hashname = os.path.join(DIRS.CACHEDIR, 'magazine', f'{myhash}.jpg')
                            copyfile(coverfile, hashname)
                            setperm(hashname)
                            control_value_dict = {"IssueFile": issuefile}
                            newcover = f'cache/magazine/{myhash}.jpg'
                            new_value_dict = {"Cover": newcover}
                            db.upsert("Issues", new_value_dict, control_value_dict)
                            latest = db.match("select Title,LatestCover,IssueDate from magazines "
                                              "where title=? COLLATE NOCASE", (title,))
                            if latest:
                                title = latest['Title']
                                if latest['IssueDate'] == issue['IssueDate'] and latest['LatestCover'] != newcover:
                                    db.action("UPDATE magazines SET LatestCover=? "
                                              "WHERE Title=? COLLATE NOCASE", (newcover, title))
                            issue['Cover'] = newcover
                            issue['CoverFile'] = coverfile  # for updating calibre cover
                            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                                self.update_calibre_issue_cover(issue)
                            passed += 1
                        else:
                            failed += 1
                            logger.warning(f"No coverfile created for IssueID {itm} {issuefile}")

                    if action == "Delete" and issuefile:
                        result = self.delete_issue(issuefile)
                        if result:
                            passed += 1
                            logger.info(f'Issue {issue["IssueDate"]} of {issue["Title"]} deleted from disc')
                            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                                self.delete_from_calibre(issue)
                        else:
                            failed += 1
                    if action == "Remove" or action == "Delete":
                        db.action('DELETE from issues WHERE IssueID=?', (itm,))
                        logger.info(f'Issue {issue["IssueDate"]} of {issue["Title"]} removed from database')
                        _ = self.mag_set_latest(title)
                        passed += 1
        db.close()

        logger.debug(f"{action.title()}: Pass {passed}, Fail {failed}")

        # Return JSON response instead of redirect
        total = passed + failed
        summary = f"Operation '{action}' completed."
        if total > 0:
            summary += f" {passed} successful"
            if failed > 0:
                summary += f", {failed} failed"
            summary += f" out of {total} total items."
        else:
            summary += " No items were processed."

        self.issues_data = ''
        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'title': title,
            'summary': summary
        }

    @staticmethod
    def mag_set_latest(title):
        # Set magazine_issuedate to issuedate of most recent issue we have
        # Set latestcover to most recent issue cover
        # Set magazine_lastacquired to acquired date of most recent issue we have
        # Set magazine_added to acquired date of the earliest issue we have
        # Return the latest issue date, or empty if no issues
        db = database.DBConnection()
        cmd = ("select IssueDate,IssueAcquired,IssueFile,Cover from issues where title=? "
               "order by IssueDate ")
        newest = db.match(cmd + 'DESC', (title,))
        oldest = db.match(cmd + 'ASC', (title,))
        control_value_dict = {'Title': title}
        if newest and oldest:
            old_acquired = ''
            new_acquired = ''
            cover = newest['Cover']
            issuefile = newest['IssueFile']
            if path_exists(issuefile):
                mtime = os.path.getmtime(syspath(issuefile))
                new_acquired = datetime.date.isoformat(datetime.date.fromtimestamp(mtime))
            issuefile = oldest['IssueFile']
            if path_exists(issuefile):
                mtime = os.path.getmtime(syspath(issuefile))
                old_acquired = datetime.date.isoformat(datetime.date.fromtimestamp(mtime))

            new_value_dict = {
                'IssueDate': newest['IssueDate'],
                'LatestCover': cover,
                'LastAcquired': new_acquired,
                'MagazineAdded': old_acquired
            }
        else:  # there are no issues
            new_value_dict = {
                'IssueDate': '',
                'LastAcquired': '',
                'LatestCover': '',
                'MagazineAdded': ''
            }
        db.upsert("magazines", new_value_dict, control_value_dict)
        db.close()
        return new_value_dict['IssueDate']

    @staticmethod
    def delete_from_calibre(data):
        logger = logging.getLogger(__name__)
        calibre_id = get_calibre_id(data)
        if calibre_id:
            res, err, rc = calibredb('remove', [calibre_id])
            logger.debug(f"Delete result: {res} [{err}] {rc}")

    @staticmethod
    def update_calibre_issue_cover(issue):
        logger = logging.getLogger(__name__)
        calibre_id = get_calibre_id(issue)
        if calibre_id:
            res, err, rc = calibredb('set_metadata', ['--field', f'cover:{issue["CoverFile"]}'], [calibre_id])
            logger.debug(f"Update result: {res} [{err}] {rc}")

    def delete_issue(self, issuefile):
        self.check_permitted(lazylibrarian.perm_edit)
        logger = logging.getLogger(__name__)
        try:
            # delete the magazine file and any cover image / opf
            remove_file(issuefile)
            fname, extn = splitext(issuefile)
            for extn in ['.opf', '.jpg']:
                remove_file(fname + extn)
            # if the directory is now empty, delete that too
            if CONFIG.get_bool('MAG_DELFOLDER'):
                parent_dir = syspath(os.path.dirname(issuefile))
                files = os.listdir(parent_dir)
                try:
                    if len(files) == 1 and '.ll_ignore' in files:
                        remove_file('.ll_ignore')
                    os.rmdir(parent_dir)
                except OSError as e:
                    logger.debug(f'Directory {parent_dir} not deleted: {str(e)}')
            return True
        except Exception as e:
            logger.warning(f'delete issue failed on {issuefile}, {type(e).__name__} {str(e)}')
            return False

    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def mark_magazines_ajax(self, action=None, **args):
        self.check_permitted(lazylibrarian.perm_status)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        total_items = 0
        current_item = 0
        args.pop('book_table_length', None)
        lazylibrarian.MARK_ISSUES = True
        passed = 0
        failed = 0
        title = ''
        for itm in args:
            try:
                if not lazylibrarian.MARK_ISSUES:
                    break
                title = itm
                if action == "Paused" or action == "Active":
                    control_value_dict = {"Title": title}
                    new_value_dict = {"Status": action}
                    db.upsert("magazines", new_value_dict, control_value_dict)
                    logger.info(f'Status of magazine {title} changed to {action}')
                    passed += 1

                if action == "Delete":
                    issues = db.select('SELECT * from issues WHERE Title=?', (title,))
                    logger.debug(f'Deleting magazine {title} from disc')
                    issuedir = ''
                    for issue in issues:  # delete all issues of this magazine
                        result = self.delete_issue(issue['IssueFile'])
                        if result:
                            passed += 1
                            logger.debug(f'Issue {issue["IssueFile"]} deleted from disc')
                            if CONFIG['IMP_CALIBREDB'] and CONFIG.get_bool('IMP_CALIBRE_MAGAZINE'):
                                self.delete_from_calibre(issue)
                            issuedir = os.path.dirname(issue['IssueFile'])
                        else:
                            failed += 1
                            logger.debug(f'Failed to delete {issue["IssueFile"]}')

                    # if the directory is now empty, delete that too
                    if issuedir and CONFIG.get_bool('MAG_DELFOLDER'):
                        magdir = os.path.dirname(issuedir)
                        try:
                            os.rmdir(syspath(magdir))
                            logger.debug(f'Magazine directory {magdir} deleted from disc')
                        except OSError:
                            logger.debug(f'Magazine directory {magdir} is not empty')
                            failed += 1
                        logger.info(f'Magazine {title} deleted from disc')

                if action == 'tag':
                    issues = db.select('SELECT * from issues WHERE Title=?', (title,))
                    mag = db.match('SELECT Language,Genre FROM magazines where Title=?', (title,))
                    total_items += len(issues)
                    for issue in issues:
                        logger.debug(f"Tagging {issue['IssueFile']}")
                        current_item += 1
                        current_percent = int(current_item * 100 / total_items)
                        lazylibrarian.magazinescan_data = f"{current_item}/{total_items}/{current_percent}"
                        genres = mag[1]
                        tags = {}
                        cnt = 1
                        for itm in get_list(genres):
                            tags[f'/Genre_{cnt}'] = itm
                            cnt += 1
                        try:
                            res = write_pdf_tags(issue['IssueFile'], title, issue["IssueDate"], tags)
                        except Exception as e:
                            logger.error(f"Failed to tag {issue['IssueFile']}: {e}")
                            res = False
                        if not res:
                            failed += 1
                        else:
                            passed += 1
                            if CONFIG.get_bool('IMP_MAGOPF'):
                                logger.debug(f"Writing opf for {issue['IssueFile']}")
                                _, _ = lazylibrarian.metadata_opf.create_mag_opf(issue['IssueFile'], title,
                                                                                 issue["IssueDate"],
                                                                                 issue["IssueID"],
                                                                                 language=mag[0],
                                                                                 genres=genres,
                                                                                 overwrite=True)

                if action == 'Scan':
                    magazine_scan(title)
                    passed += 1

                if action == 'Search':
                    if CONFIG.use_any():
                        logger.debug(f"Searching for magazine: {title}")
                        search_magazines([{"bookid": title}], False, False)
                        passed += 1
                    else:
                        logger.warning("Not searching for magazine, no download methods set, check config")

                if action == "Remove" or action == "Delete":
                    db.action('DELETE from magazines WHERE Title=? COLLATE NOCASE', (title,))
                    db.action('DELETE from pastissues WHERE BookID=? COLLATE NOCASE', (title,))
                    db.action('DELETE from wanted where BookID=? COLLATE NOCASE', (title,))
                    logger.info(f'Magazine {title} removed from database')
                    passed += 1
                elif action == "Reset":
                    control_value_dict = {"Title": title}
                    new_value_dict = {
                        "LastAcquired": '',
                        "IssueDate": '',
                        "LatestCover": '',
                        "IssueStatus": "Wanted"
                    }
                    db.upsert("magazines", new_value_dict, control_value_dict)
                    logger.info(f'Magazine {title} details reset')
                    passed += 1
                elif action == 'Subscribe':
                    cookie = cherrypy.request.cookie
                    if cookie and 'll_uid' in list(cookie.keys()):
                        userid = cookie['ll_uid'].value
                        res = db.match("SELECT * from subscribers WHERE UserID=? and Type=? and WantID=?",
                                       (userid, 'magazine', title))
                        if res:
                            logger.debug(f"User {userid} is already subscribed to {title}")
                            failed += 1
                        else:
                            db.action('INSERT into subscribers (UserID, Type, WantID) VALUES (?, ?, ?)',
                                      (userid, 'magazine', title))
                            logger.debug(f"Subscribe {userid} to magazine {title}")
                            passed += 1
                elif action == 'Unsubscribe':
                    cookie = cherrypy.request.cookie
                    if cookie and 'll_uid' in list(cookie.keys()):
                        userid = cookie['ll_uid'].value
                        db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                  (userid, 'magazine', title))
                        res = db.select('SELECT issueid from issues where title=?', (title, ))
                        for iss in res:
                            db.action('DELETE from subscribers WHERE UserID=? and Type=? and WantID=?',
                                      (userid, 'magazine', iss['issueid']))
                        logger.debug(f"Unsubscribe {userid} to magazine {title}")
                    passed += 1

            except Exception as e:
                logger.error(f'Unable to {action} {title}: {type(e).__name__} {str(e)}')

        logger.debug(f"{action}:{title}: Pass {passed}, Fail {failed}")
        db.close()

        # Return JSON response instead of redirect
        total = passed + failed
        summary = f"Operation '{action}' completed."
        if total > 0:
            summary += f" {passed} successful"
            if failed > 0:
                summary += f", {failed} failed"
            summary += f" out of {total} total items."
        else:
            summary += " No items were processed."

        return {
            'success': True,
            'action': action,
            'passed': passed,
            'failed': failed,
            'total': total,
            'summary': summary
        }

    @cherrypy.expose
    @require_auth()
    def search_for_mag(self, bookid=None):
        self.check_permitted(lazylibrarian.perm_search)
        TELEMETRY.record_usage_data()
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        bookdata = db.match('SELECT * from magazines WHERE Title=? COLLATE NOCASE', (bookid,))
        db.close()
        if bookdata:
            # start searchthreads
            mags = [{"bookid": bookdata['Title']}]
            self.start_magazine_search(mags)
            raise cherrypy.HTTPRedirect("magazines")
        logger.warning(f"Magazine {bookid} was not found in the library")
        raise cherrypy.HTTPError(404, f"Magazine {bookid} not found")

    @cherrypy.expose
    @require_auth()
    def start_magazine_search(self, mags=None):
        self.check_permitted(lazylibrarian.perm_search)
        logger = logging.getLogger(__name__)
        if mags:
            if CONFIG.use_any():
                threading.Thread(target=search_magazines, name='SEARCHMAG', args=[mags, False, False]).start()
                logger.debug(f"Searching for magazine with title: {mags[0]['bookid']}")
            else:
                logger.warning("Not searching for magazine, no download methods set, check config")
        else:
            logger.debug("MagazineSearch called with no magazines")

    @cherrypy.expose
    @require_auth()
    def add_magazine(self, title=None, **kwargs):
        self.check_permitted(lazylibrarian.perm_magazines)
        TELEMETRY.record_usage_data()
        logger = logging.getLogger(__name__)
        if not title or title == 'None':
            raise cherrypy.HTTPRedirect("magazines")

        self.validate_param("magazine title", title, ['<', '>', '='], 404)
        db = database.DBConnection()
        reject = None
        if '~' in title:  # separate out the "reject words" list
            reject = title.split('~', 1)[1].strip()
            title = title.split('~', 1)[0].strip()

        # replace any non-ascii quotes/apostrophes with ascii ones eg "Collector's"
        title = replace_all(title, lazylibrarian.DICTS.get('apostrophe_dict', {}))
        title_exploded = title.split()
        # replace symbols by words
        new_title = []
        for word in title_exploded:
            if word == '&' or word == '+':
                word = 'and'
            new_title.append(word)
        title = ' '.join(new_title)
        exists = db.match('SELECT * from magazines WHERE Title=? COLLATE NOCASE', (title,))
        if exists:
            logger.debug(f"Magazine {title} already exists ({exists['Title']})")
        else:
            control_value_dict = {"Title": title}
            new_value_dict = {
                "Reject": reject,
                "Genre": "",
                "DateType": "",
                "Status": "Active",
                "MagazineAdded": today(),
                "LastAcquired": None,
                "LatestCover": None,
                "IssueDate": None,
                "IssueStatus": "Wanted",
                "Regex": None,
                "CoverPage": 1,
                "Language": CONFIG['PREF_MAGLANG'],
            }
            db.upsert("magazines", new_value_dict, control_value_dict)
            mags = [{"bookid": title}]
            if CONFIG.get_bool('IMP_AUTOSEARCH'):
                self.start_magazine_search(mags)
        db.close()
        if kwargs.get('magfilter'):
            raise cherrypy.HTTPRedirect("magazines?mag_filter=" + kwargs.get('magfilter'))
        raise cherrypy.HTTPRedirect("magazines")

    # UPDATES ###########################################################

    @cherrypy.expose
    @require_auth()
    def check_for_updates(self):
        self.check_permitted(lazylibrarian.perm_force)
        self.label_thread('UPDATES')
        versioncheck.check_for_updates()
        if CONFIG.get_int('COMMITS_BEHIND') == 0:
            if lazylibrarian.COMMIT_LIST:
                message = "unknown status"
                messages = lazylibrarian.COMMIT_LIST.replace('\n', '<br>')
                message = message + '<br><small>' + messages
            else:
                message = "up to date"
        elif CONFIG.get_int('COMMITS_BEHIND') > 0:
            message = (f"behind by {CONFIG.get_int('COMMITS_BEHIND')} "
                       f"{plural(CONFIG.get_int('COMMITS_BEHIND'), 'commit')}")
            messages = lazylibrarian.COMMIT_LIST.replace('\n', '<br>')
            message = message + '<br><small>' + messages

            if '** MANUAL **' in lazylibrarian.COMMIT_LIST:
                message += "Update needs manual installation"
        else:
            message = "unknown version"
            messages = (f"Your version ({CONFIG['CURRENT_VERSION']}) is not recognized at<br>https://"
                        f"{CONFIG['GIT_HOST']}/{CONFIG['GIT_USER']}/{CONFIG['GIT_REPO']}  "
                        f"Branch: {CONFIG['GIT_BRANCH']}")
            message = message + '<br><small>' + messages

        return f"LazyLibrarian is {message}"

    @cherrypy.expose
    @require_auth()
    def force_update(self):
        self.check_permitted(lazylibrarian.perm_force)
        logger = logging.getLogger(__name__)
        if 'AAUPDATE' not in [n.name for n in list(threading.enumerate())]:
            threading.Thread(target=all_author_update, name='AAUPDATE', args=[False]).start()
        else:
            logger.debug('AAUPDATE already running')
        raise cherrypy.HTTPRedirect("home")

    @cherrypy.expose
    @require_auth()
    def update(self):
        self.check_permitted(lazylibrarian.perm_force)
        logger = logging.getLogger(__name__)
        self.label_thread('UPDATING')
        logger.debug('(webServe-Update) - Performing update')
        remove_file(os.path.join(DIRS.CACHEDIR, 'alive.png'))
        lazylibrarian.SIGNAL = 'update'
        message = 'Updating...'
        return serve_template(templatename="shutdown.html", prefix='LazyLibrarian is ', title="Updating",
                              message=message, timer=90)

    # IMPORT/EXPORT #####################################################

    @cherrypy.expose
    @require_auth()
    def library_scan(self, **kwargs):
        self.check_permitted(lazylibrarian.perm_force)
        logger = logging.getLogger(__name__)
        types = []
        if CONFIG.get_bool('EBOOK_TAB'):
            types.append('eBook')
        if CONFIG.get_bool('AUDIO_TAB'):
            types.append('AudioBook')
        if not types:
            raise cherrypy.HTTPRedirect('authors')
        library = types[0]
        if 'library' in kwargs and kwargs['library'] in types:
            library = kwargs['library']

        removed = CONFIG.get_bool('FULL_SCAN')
        threadname = f"{library.upper()}_SCAN"
        if threadname not in [n.name for n in list(threading.enumerate())]:
            try:
                threading.Thread(target=library_scan, name=threadname, args=[None, library, None, removed]).start()
            except Exception as e:
                logger.error(f'Unable to complete the scan: {type(e).__name__} {str(e)}')
        else:
            logger.debug(f'{threadname} already running')
        if library == 'AudioBook':
            raise cherrypy.HTTPRedirect("audio")
        raise cherrypy.HTTPRedirect("books")

    @cherrypy.expose
    @require_auth()
    def clean_magazine_library(self):
        self.check_permitted(lazylibrarian.perm_force)
        magazinescan.clean_maglibrary()
        raise cherrypy.HTTPRedirect("magazines")

    @cherrypy.expose
    @require_auth()
    def magazine_scan(self, **kwargs):
        self.check_permitted(lazylibrarian.perm_force)
        logger = logging.getLogger(__name__)
        if 'title' in kwargs:
            title = kwargs['title']
            title = title.replace('&amp;', '&')
        else:
            title = ''

        threadname = "MAGAZINE_SCAN"
        if title:
            threadname = f'{threadname}_{title}'
        if threadname not in [n.name for n in list(threading.enumerate())]:
            try:
                if title:
                    threading.Thread(target=magazinescan.magazine_scan, name=threadname, args=[title]).start()
                else:
                    threading.Thread(target=magazinescan.magazine_scan, name=threadname, args=[]).start()
            except Exception as e:
                logger.error(f'Unable to complete the scan: {type(e).__name__} {str(e)}')
        else:
            logger.debug(f'{threadname} already running')
        if title:
            raise cherrypy.HTTPRedirect(f"issue_page?title={quote(title)}")
        raise cherrypy.HTTPRedirect("magazines")

    @cherrypy.expose
    @require_auth()
    def include_alternate(self, library='eBook'):
        self.check_permitted(lazylibrarian.perm_force)
        logger = logging.getLogger(__name__)
        if 'ALT-LIBRARYSCAN' not in [n.name for n in list(threading.enumerate())]:
            try:
                threading.Thread(target=library_scan, name='ALT-LIBRARYSCAN',
                                 args=[CONFIG['ALTERNATE_DIR'], library, None, False]).start()
            except Exception as e:
                logger.error(f'Unable to complete the libraryscan: {type(e).__name__} {str(e)}')
        else:
            logger.debug('ALT-LIBRARYSCAN already running')
        raise cherrypy.HTTPRedirect(f"manage?library={library}")

    @cherrypy.expose
    @require_auth()
    def import_issues(self, title=None):
        self.check_permitted(lazylibrarian.perm_force)
        logger = logging.getLogger(__name__)
        if not title:
            logger.error("No title to import")
            raise cherrypy.HTTPRedirect("magazines")
        threadname = f"IMPORTISSUES_{title}"
        if threadname not in [n.name for n in list(threading.enumerate())]:
            try:
                threading.Thread(target=process_issues, name=threadname,
                                 args=[CONFIG['ALTERNATE_DIR'], title]).start()
            except Exception as e:
                logger.error(f'Unable to complete the import: {type(e).__name__} {str(e)}')
        else:
            logger.debug(f'{threadname} already running')
        raise cherrypy.HTTPRedirect(f"issue_page?title={quote(title)}")

    @cherrypy.expose
    @require_auth()
    def import_alternate(self, library='eBook'):
        self.check_permitted(lazylibrarian.perm_force)
        self.validate_param("library name", library, ['<', '>', '='], 404)
        logger = logging.getLogger(__name__)
        if f'IMPORTALT_{library}' not in [n.name for n in list(threading.enumerate())]:
            try:
                threading.Thread(target=process_alternate, name=f'IMPORTALT_{library}',
                                 args=[CONFIG['ALTERNATE_DIR'], library]).start()
            except Exception as e:
                logger.error(f'Unable to complete the import: {type(e).__name__} {str(e)}')
        else:
            logger.debug('IMPORTALT already running')
        raise cherrypy.HTTPRedirect(f"manage?library={library}")

    @cherrypy.expose
    def rss_feed(self, **kwargs):
        logger = logging.getLogger(__name__)
        self.label_thread('RSSFEED')
        if 'type' in kwargs:
            ftype = kwargs['type']
        else:
            return ''

        limit = kwargs.get('limit', '10')
        authorid = kwargs.get('authorid')
        onetitle = kwargs.get('onetitle')

        # url might end in .xml
        if not limit.isdigit():
            try:
                limit = int(limit.split('.')[0])
            except (IndexError, ValueError):
                limit = 10

        userid = 0
        if 'user' in kwargs:
            userid = kwargs['user']
        else:
            cookie = cherrypy.request.cookie
            if cookie and 'll_uid' in list(cookie.keys()):
                userid = cookie['ll_uid'].value

        scheme, netloc, path, qs, anchor = urlsplit(cherrypy.url())

        my_ip = CONFIG['RSS_HOST']
        if not my_ip:
            my_ip = cherrypy.request.headers.get('X-Forwarded-Host')
        if not my_ip:
            my_ip = cherrypy.request.headers.get('Host')
        if not my_ip:
            my_ip = netloc
        path = path.replace('rss_feed', '').rstrip('/')

        baseurl = urlunsplit((scheme, my_ip, path, qs, anchor))

        remote_ip = cherrypy.request.headers.get('X-Forwarded-For')  # apache2
        if not remote_ip:
            remote_ip = cherrypy.request.headers.get('X-Host')  # lighthttpd
        if not remote_ip:
            remote_ip = cherrypy.request.headers.get('Remote-Addr')
        if not remote_ip:
            remote_ip = cherrypy.request.remote.ip
        remote_ip = remote_ip.split(',')[0]

        if onetitle:
            filename = f'LazyLibrarian_RSS_{onetitle.replace("&amp;", "&")}.xml'
        else:
            filename = f'LazyLibrarian_RSS_{ftype}.xml'
        logger.debug(f"rss Feed request {limit} {ftype}{plural(limit)}: {remote_ip} {userid}")
        cherrypy.response.headers["Content-Type"] = 'application/rss+xml'
        cherrypy.response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        res = gen_feed(ftype, limit=limit, user=userid, baseurl=baseurl, authorid=authorid, onetitle=onetitle)
        return res.encode('UTF-8')

    @cherrypy.expose
    @require_auth()
    def import_csv(self, library=''):
        self.check_permitted(lazylibrarian.perm_force)
        self.validate_param("library name", library, ['<', '>', '='], 404)
        logger = logging.getLogger(__name__)
        if f'IMPORTCSV_{library}' not in [n.name for n in list(threading.enumerate())]:
            self.label_thread('IMPORTCSV')
            try:
                csvfile = csv_file(CONFIG['ALTERNATE_DIR'], library=library)
                if path_exists(csvfile):
                    message = f"Importing csv (background task) from {csvfile}"
                    threading.Thread(target=import_csv, name=f'IMPORTCSV_{library}',
                                     args=[CONFIG['ALTERNATE_DIR'], 'Wanted', library]).start()
                else:
                    message = f"No {library} CSV file in [{CONFIG['ALTERNATE_DIR']}]"
            except Exception as e:
                message = f'Unable to complete the import: {type(e).__name__} {str(e)}'
                logger.error(message)
        else:
            message = 'IMPORTCSV already running'
            logger.debug(message)
        return message

    @cherrypy.expose
    @require_auth()
    def export_csv(self, library=''):
        self.check_permitted(lazylibrarian.perm_force)
        self.validate_param("library name", library, ['<', '>', '='], 404)
        self.label_thread('EXPORTCSV')
        message = export_csv(CONFIG['ALTERNATE_DIR'], library=library)
        message = message.replace('\n', '<br>')
        return message

    # JOB CONTROL #######################################################

    @cherrypy.expose
    @require_auth()
    def shutdown(self):
        self.check_permitted(lazylibrarian.perm_admin)
        self.label_thread('SHUTDOWN')
        # lazylibrarian.config_write()
        remove_file(os.path.join(DIRS.CACHEDIR, 'alive.png'))
        lazylibrarian.SIGNAL = 'shutdown'
        message = 'closed'
        return serve_template(templatename="shutdown.html", prefix='LazyLibrarian is ', title="Close library",
                              message=message, timer=0)

    @cherrypy.expose
    @require_auth()
    def restart(self):
        self.check_permitted(lazylibrarian.perm_admin)
        self.label_thread('RESTART')
        remove_file(os.path.join(DIRS.CACHEDIR, 'alive.png'))
        lazylibrarian.SIGNAL = 'restart'
        message = 'reopening ...'
        return serve_template(templatename="shutdown.html", prefix='LazyLibrarian is ', title="Reopen library",
                              message=message, timer=50)

    @cherrypy.expose
    @require_auth()
    def show_jobs(self):
        self.check_permitted(lazylibrarian.perm_admin)
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        # show the current status of LL cron jobs
        resultlist = show_jobs()
        result = ''
        for line in resultlist:
            result = result + line + '\n'
        return result

    @cherrypy.expose
    @require_auth()
    def show_apprise(self):
        self.check_permitted(lazylibrarian.perm_admin)
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # show the available notifiers
        apprise_list = lazylibrarian.notifiers.apprise_notify.AppriseNotifier.notify_types()
        result = ''
        results = []
        try:
            for entry in apprise_list:
                if isinstance(entry, str):
                    results.append(entry)
            results.sort(key=str.casefold)
            result = "\n".join(results)
        except Exception as e:
            logger.debug(str(e))
        return result

    @cherrypy.expose
    @require_auth()
    def show_stats(self):
        self.check_permitted(lazylibrarian.perm_admin)
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        # show some database status info
        resultlist = show_stats()
        result = ''
        for line in resultlist:
            result = result + line + '\n'
        return result

    @cherrypy.expose
    @require_auth()
    def restart_jobs(self):
        self.check_permitted(lazylibrarian.perm_admin)
        restart_jobs(command=SchedulerCommand.RESTART)

    @cherrypy.expose
    @require_auth()
    def stop_jobs(self):
        self.check_permitted(lazylibrarian.perm_admin)
        restart_jobs(command=SchedulerCommand.STOP)

    # LOGGING ###########################################################

    @cherrypy.expose
    @require_auth()
    def clear_log(self):
        self.check_permitted(lazylibrarian.perm_admin)
        logger = logging.getLogger(__name__)
        LOGCONFIG.clear_ui_log()
        logger.info('Screen log cleared')
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def toggle_detailed_logs(self):
        detail = CONFIG.get_bool('DETAILEDUILOG')
        CONFIG.set_bool('DETAILEDUILOG', not detail)
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def delete_logs(self):
        self.check_permitted(lazylibrarian.perm_admin)
        logger = logging.getLogger(__name__)
        result = LOGCONFIG.delete_log_files(CONFIG['LOGDIR'])
        logger.info(result)
        raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def get_support_zip(self):
        # Save the redacted log and config to a zipfile
        self.label_thread('SAVELOG')
        logger = logging.getLogger(__name__)
        msg, zipfile = create_support_zip()
        logger.info(msg)
        return cherrypy.lib.static.serve_file(zipfile, 'application/x-download', 'attachment',
                                              os.path.basename(zipfile))
        # raise cherrypy.HTTPRedirect("logs")

    @cherrypy.expose
    @require_auth()
    def log_header(self):
        # Return the log header info
        result = log_header()
        return result

    @cherrypy.expose
    @require_auth()
    def logs(self):
        self.check_permitted(lazylibrarian.perm_logs)
        return serve_template(templatename="logs.html", title="Log", lineList=[])  # lazylibrarian.LOGLIST)

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_log(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        # kwargs is used by datatables to pass params
        logger = logging.getLogger(__name__)
        rows = filtered = []
        total = 0

        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)

            filtered, total = LOGCONFIG.get_ui_logrows(sSearch)

            sortcolumn = int(iSortCol_0)
            filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                          reverse=sSortDir_0 == "desc")
            rows = filtered if displaylength < 0 else filtered[displaystart:(displaystart + displaylength)]
        except Exception:
            logger.error(f'Unhandled exception in get_log: {traceback.format_exc()}')
            rows = filtered = []

        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': total,
                  'aaData': rows,
                  }
        return mydict

    # HISTORY ###########################################################

    @cherrypy.expose
    @require_auth()
    def history(self):
        self.check_permitted(lazylibrarian.perm_history)
        return serve_template(templatename="history.html", title="History", history=[])

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    @cherrypy.tools.json_out()
    def get_history(self, iDisplayStart=0, iDisplayLength=100, iSortCol_0=0, sSortDir_0="desc", sSearch="", **kwargs):
        rows = []
        filtered = []
        rowlist = []
        self.label_thread('WEBSERVER')
        logger = logging.getLogger(__name__)
        serversidelogger = logging.getLogger('special.serverside')
        db = database.DBConnection()
        # noinspection PyBroadException
        try:
            displaystart = int(iDisplayStart)
            displaylength = int(iDisplayLength)
            CONFIG.set_int('DISPLAYLENGTH', displaylength)
            snatching = 0
            cmd = "SELECT NZBTitle,AuxInfo,BookID,NZBProv,NZBDate,NZBSize,Status,Source,DownloadID,rowid from wanted "
            cmd += "where BookID is not null and AuxInfo is not null"
            rowlist = db.select(cmd)
            # turn the sqlite rowlist into a list of dicts
            if len(rowlist):
                # the masterlist to be filled with the row data
                for row in rowlist:  # iterate through the sqlite3.Row objects
                    entry = list(row)  # turn sqlite objects into lists
                    rows.append(entry)  # add the rowlist to the masterlist

                if sSearch:
                    serversidelogger.debug(f"filter {sSearch}")
                    filtered = [x for x in rows if sSearch.lower() in str(x).lower()]
                else:
                    filtered = rows

                sortcolumn = int(iSortCol_0)
                serversidelogger.debug(f"sortcolumn {sortcolumn}")

                # use rowid to get most recently added first (monitoring progress)
                if sortcolumn == 6:
                    sortcolumn = 9

                if sortcolumn == 5:
                    self.natural_sort(filtered, key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                      reverse=sSortDir_0 == "desc")
                else:
                    filtered.sort(key=lambda y: y[sortcolumn] if y[sortcolumn] is not None else '',
                                  reverse=sSortDir_0 == "desc")

                if displaylength < 0:  # display = all
                    nrows = filtered
                else:
                    nrows = filtered[displaystart:(displaystart + displaylength)]

                lazylibrarian.HIST_REFRESH = 0
                rows = []
                for row in nrows:
                    row = list(row)
                    row[8] = make_unicode(row[8])  # delugerpc returns bytes
                    # title needs spaces, not dots, for column resizing
                    title = row[0]  # type: str
                    if title:
                        title = title.replace('.', ' ')
                        row[0] = title
                    # provider name needs to be shorter and with spaces for column resizing
                    if row[3]:
                        row[3] = CONFIG.disp_name(row[3].strip('/'))
                    # separate out rowid and other additions, so we don't break legacy interface
                    rowid = row[9]
                    row = row[:9]
                    if row[6] == 'Snatched':
                        snatching += 1
                        if snatching <= 5:
                            progress, _ = get_download_progress(row[7], row[8])
                            row.append(progress)
                            if progress < 100:
                                lazylibrarian.HIST_REFRESH = CONFIG.get_int('HIST_REFRESH')
                        else:
                            row.append(-1)
                    else:
                        row.append(-1)
                    row.append(rowid)
                    row.append(row[4])  # keep full datetime for tooltip
                    row[4] = date_format(row[4], CONFIG['DATE_FORMAT'], context=row[0], datelang=CONFIG['DATE_LANG'])

                    if row[1] in ['eBook', 'AudioBook']:
                        btn = '<button onclick="bookinfo(\'' + row[2]
                        btn += '\')" class="button btn-link text-left" type="button" '
                        btn += '>' + row[1] + '</button>'
                        row[1] = btn
                        auth = db.match('SELECT authorid from books where bookid=?', (row[2],))
                        if auth:
                            # noinspection PyBroadException
                            try:
                                btn = '<a href=\'author_page?authorid='
                                btn += auth['authorid']
                                btn += '\'">' + row[2] + '</a>'
                                row[2] = btn
                            except Exception:
                                logger.debug(f"Unexpected authorid [{auth}]")
                    elif row[1] == 'comic':
                        btn = '<a href=\'open_comic?comicid=' + row[2].split('_')[0] + '\'">' + row[2] + '</a>'
                        row[2] = btn
                    else:
                        # noinspection PyBroadException
                        try:
                            if row[1] and re.match(r"^[0-9.-]+$", row[1]) is not None:  # Magazine
                                btn = '<a href=\'open_mag?bookid=' + row[2] + '\'">' + row[2] + '</a>'
                                row[2] = btn
                        except Exception:
                            logger.debug(f"Unexpected auxinfo [{row[1]}] {row[2]}")
                            continue
                    rows.append(row)

            serversidelogger.debug(
                f"get_history returning {displaystart} to {displaystart + displaylength}, snatching {snatching}")
            serversidelogger.debug(f"get_history filtered {len(filtered)} from {len(rowlist)}:{len(rows)}")
        except Exception:
            logger.error(f'Unhandled exception in get_history: {traceback.format_exc()}')
            rows = []
            rowlist = []
            filtered = []

        db.close()
        mydict = {'iTotalDisplayRecords': len(filtered),
                  'iTotalRecords': len(rowlist),
                  'aaData': rows,
                  }
        serversidelogger.debug(str(mydict))
        return mydict


    @cherrypy.expose
    @require_auth()
    def show_running(self):
        """ return a list of currently running tasks """
        return lazylibrarian.scheduling.show_running()


    @cherrypy.expose
    @require_auth()
    def bookdesc(self, bookid=None):
        # noinspection PyGlobalUndefined
        global lastauthor
        img = None
        title = None
        text = None
        if bookid:
            db = database.DBConnection()
            if bookid.startswith('A_'):
                cmd = "SELECT AuthorName,About,AuthorImg from authors WHERE authorid=?"
                res = db.match(cmd, (bookid[2:],))
            elif bookid.startswith(('CV', 'CX')):
                try:
                    comicid, issueid = bookid.split('_')
                    cmd = ("SELECT Title as BookName,comicissues.Description as BookDesc,Cover as BookImg,"
                           "Contributors from comics,comicissues where comics.comicid = comicissues.comicid "
                           "and comics.comicid=? and issueid=?")
                    res = db.match(cmd, (comicid, issueid))
                except ValueError:
                    cmd = ("SELECT Title as BookName,Description as BookDesc,LatestCover as BookImg from comics "
                           "where comicid=?")
                    res = db.match(cmd, (bookid,))
            else:
                cmd = "SELECT BookName,BookDesc,BookImg,AuthorID from books WHERE bookid=?"
                res = db.match(cmd, (bookid,))
            if res:
                res = dict(res)
                text = res.get('BookDesc')
                if not text:
                    text = res.get('About')
                contributors = res.get('Contributors')
                if contributors:
                    text += '<br><br>' + contributors
                img = res.get('BookImg')
                if not img:
                    img = res.get('AuthorImg')
                title = res.get('BookName')
                if not title:
                    title = res.get('AuthorName')
                if 'AuthorID' in res:
                    lastauthor = res['AuthorID']
            db.close()
        if not img:
            img = 'images/nocover.jpg'
        if not title:
            title = 'BookID not found'
        if not text:
            text = 'No Description'
        return img + '^' + title + '^' + text

    @cherrypy.expose
    @require_auth()
    def dlinfo(self, target=None):
        if '^' not in target:
            return ''
        db = database.DBConnection()
        status, rowid = target.split('^')
        if status == 'Ignored':
            match = db.match('select ScanResult from books WHERE bookid=?', (rowid,))
            message = f'Reason: {match["ScanResult"]}<br>'
        else:
            cmd = ("select NZBurl,NZBtitle,NZBdate,NZBprov,Status,NZBsize,AuxInfo,NZBmode,DLResult,Source,"
                   "DownloadID from wanted where rowid=?")
            match = db.match(cmd, (rowid,))
            dltype = match['AuxInfo']
            if dltype not in ['eBook', 'AudioBook']:
                if not dltype:
                    dltype = 'eBook'
                else:
                    dltype = 'Magazine'
            message = f"Title: {match['NZBtitle']}<br>"
            message += f"Type: {match['NZBmode']} {dltype}<br>"
            message += f"Date: {match['NZBdate']}<br>"
            message += f"Size: {match['NZBsize']} Mb<br>"
            message += f"Provider: {CONFIG.disp_name(match['NZBprov'])}<br>"
            message += f"Downloader: {match['Source']}<br>"
            message += f"DownloadID: {match['DownloadID']}<br>"
            message += f"URL: {match['NZBurl']}<br>"
            if status == 'Processed':
                message += f"File: {match['DLResult']}<br>"
            elif status == 'Seeding':
                message += status
            else:
                message += f"Error: {match['DLResult']}<br>"
        db.close()
        return message

    @cherrypy.expose
    @require_auth()
    def deletehistory(self, rowid=None):
        self.check_permitted(lazylibrarian.perm_edit)
        logger = logging.getLogger(__name__)
        if not rowid:
            logger.warning("No rowid in deletehistory")
        else:
            db = database.DBConnection()
            try:
                match = db.match('SELECT NZBtitle,Status from wanted WHERE rowid=?', (rowid,))
                if match:
                    logger.debug(f'Deleting {match["Status"]} history item {match["NZBtitle"]}')
                    db.action('DELETE from wanted WHERE rowid=?', (rowid,))
                else:
                    logger.warning(f"No rowid {rowid} in history")
            finally:
                db.close()

    @cherrypy.expose
    @require_auth()
    def markhistory(self, rowid=None):
        self.check_permitted(lazylibrarian.perm_status)
        logger = logging.getLogger(__name__)
        if not rowid:
            return
        db = database.DBConnection()
        match = db.match('SELECT NZBtitle,Status,BookID,AuxInfo from wanted WHERE rowid=?', (rowid,))
        logger.debug(f'Marking {match["Status"]} history item {match["NZBtitle"]} as Failed')
        db.action("UPDATE wanted SET Status='Failed' WHERE rowid=?", (rowid,))
        book_type = match['AuxInfo']
        if book_type not in ['AudioBook', 'eBook']:
            if not book_type:
                book_type = 'eBook'
            else:
                book_type = 'Magazine'
        if book_type == 'AudioBook':
            db.action("UPDATE books SET audiostatus='Wanted' WHERE BookID=?", (match["BookID"],))
        else:
            db.action("UPDATE books SET status='Wanted' WHERE BookID=?", (match["BookID"],))
        db.close()

    @cherrypy.expose
    @require_auth()
    def clearhistory(self, status=None):
        self.check_permitted(lazylibrarian.perm_edit)
        logger = logging.getLogger(__name__)
        db = database.DBConnection()
        if not status or status == 'all':
            logger.info("Clearing all history")
            # also reset the Snatched status in book table to Wanted and cancel any failed download task
            # ONLY reset if status is still Snatched, as maybe a later task succeeded
            status = "Snatched"
            cmd = "SELECT BookID,AuxInfo,Source,DownloadID from wanted WHERE Status=?"
            rowlist = db.select(cmd, (status,))
            for book in rowlist:
                if book['BookID'] != 'unknown':
                    if book['AuxInfo'] == 'eBook':
                        db.action("UPDATE books SET Status='Wanted' WHERE Bookid=? AND Status=?",
                                  (book['BookID'], status))
                    elif book['AuxInfo'] == 'AudioBook':
                        db.action("UPDATE books SET AudioStatus='Wanted' WHERE Bookid=? AND AudioStatus=?",
                                  (book['BookID'], status))
                    if CONFIG.get_bool('DEL_FAILED'):
                        delete_task(book['Source'], book['DownloadID'], True)
            db.action("DELETE from wanted")
        else:
            logger.info(f"Clearing history where status is {status}")
            if status == 'Snatched':
                # also reset the Snatched status in book table to Wanted and cancel any failed download task
                # ONLY reset if status is still Snatched, as maybe a later task succeeded
                cmd = "SELECT BookID,AuxInfo,Source,DownloadID from wanted WHERE Status in ('Snatched', 'Matched')"
                rowlist = db.select(cmd)
                for book in rowlist:
                    if book['BookID'] != 'unknown':
                        if book['AuxInfo'] == 'eBook':
                            db.action("UPDATE books SET Status='Wanted' WHERE Bookid=? AND Status=?",
                                      (book['BookID'], status))
                        elif book['AuxInfo'] == 'AudioBook':
                            db.action("UPDATE books SET AudioStatus='Wanted' WHERE Bookid=? AND AudioStatus=?",
                                      (book['BookID'], status))
                    if CONFIG.get_bool('DEL_FAILED'):
                        delete_task(book['Source'], book['DownloadID'], True)
                db.action("DELETE from wanted WHERE Status='Matched'")
            db.action('DELETE from wanted WHERE Status=?', (status,))
        db.close()
        raise cherrypy.HTTPRedirect("history")

    @cherrypy.expose
    @require_auth()
    def ol_api_changed(self, **kwargs):
        # ol_api is true/false, not an api key
        if kwargs['status']:
            CONFIG.set_bool('OL_API', True)
        else:
            CONFIG.set_bool('OL_API', False)
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
        return kwargs['status']

    @cherrypy.expose
    @require_auth()
    def dnb_api_changed(self, **kwargs):
        # dnb_api is true/false, not an api key
        if kwargs['status']:
            CONFIG.set_bool('DNB_API', True)
        else:
            CONFIG.set_bool('DNB_API', False)
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
        return kwargs['status']

    @cherrypy.expose
    @require_auth()
    def hc_api_changed(self, **kwargs):
        # hc_api is true/false, not an api key
        if kwargs['status']:
            CONFIG.set_bool('HC_API', True)
        else:
            CONFIG.set_bool('HC_API', False)
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
        return kwargs['status']

    @cherrypy.expose
    @require_auth()
    def gr_api_changed(self, **kwargs):
        self.validate_param("goodreads api", kwargs['gr_api'], ['<', '>', '='], 404)
        CONFIG.set_str('GR_API', kwargs['gr_api'])
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
        return kwargs['gr_api']

    @cherrypy.expose
    @require_auth()
    def gb_api_changed(self, **kwargs):
        self.validate_param("googlebooks api", kwargs['gb_api'], ['<', '>', '='], 404)
        CONFIG.set_str('GB_API', kwargs['gb_api'])
        if (not CONFIG.get_bool('HC_API') and not bool(CONFIG.get_str('GR_API'))
                and not bool(CONFIG.get_str('GB_API')) and not CONFIG.get_bool('DNB_API')):
            # ensure at least one option is available
            CONFIG.set_bool('OL_API', True)
        return kwargs['gb_api']

    @cherrypy.expose
    @require_auth()
    def testprovider(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("TESTPROVIDER")
        if 'name' in kwargs and kwargs['name']:
            host = ''
            api = ''
            if 'host' in kwargs and kwargs['host']:
                host = kwargs['host']
            if 'api' in kwargs and kwargs['api']:
                api = kwargs['api']
            fail = ''
            if not self.validate_param("provider name", kwargs['name'], ['<', '>', '='], None):
                fail += 'name '
            if not self.validate_param("provider host", kwargs['host'], ['<', '>'], None):
                fail += 'host '
            if not self.validate_param("provider api", kwargs['api'], ['<', '>'], None):
                fail += 'api '
            if fail:
                return f"{kwargs['name']} test FAILED, bad parameter: {fail}"

            result, name = test_provider(kwargs['name'], host=host, api=api)
            if result is False:
                msg = f"{name} test FAILED, check debug log"
            elif result is True:
                msg = f"{name} test PASSED"
                CONFIG.save_config_and_backup_old(section=kwargs['name'])
            else:
                wishtype = wishlist_type(host)
                if wishtype:
                    name = f'Wishlist {wishtype} {name}'
                msg = f"{name} test PASSED, found {result}"
                CONFIG.save_config_and_backup_old(section=kwargs['name'])
        else:
            msg = "Invalid or missing name in testprovider"
        return msg

    @cherrypy.expose
    @require_auth()
    def clearblocked(self):
        self.check_permitted(lazylibrarian.perm_admin)
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # clear any currently blocked providers
        num = BLOCKHANDLER.clear_all()
        result = f'Cleared {num} blocked {plural(num, "provider")}'
        logger.debug(result)
        return result

    @cherrypy.expose
    @require_auth()
    def showblocked(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # show any currently blocked providers
        result = BLOCKHANDLER.get_text_list_of_blocks()
        logger.debug(result)
        return result

    @cherrypy.expose
    @require_auth()
    def cleardownloads(self):
        self.check_permitted(lazylibrarian.perm_admin)
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        logger = logging.getLogger(__name__)
        # clear download counters
        db = database.DBConnection()
        try:
            count = db.match('SELECT COUNT(*) as counter FROM downloads')
            if count:
                num = count['counter']
            else:
                num = 0
            result = f'Deleted download counter for {num} {plural(num, "provider")}'
            db.action('DELETE from downloads')
        finally:
            db.close()
        logger.debug(result)
        return result

    @cherrypy.expose
    @require_auth()
    def showdownloads(self):
        self.check_permitted(lazylibrarian.perm_admin)
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        # show provider download totals
        result = ''
        db = database.DBConnection()
        try:
            downloads = db.select('SELECT Count,Provider FROM downloads ORDER BY Count DESC')
        finally:
            db.close()
        for line in downloads:
            provname = CONFIG.disp_name(line['Provider'].strip('/'))
            new_entry = f"{line['Count']:4d} - {provname}\n"
            result += new_entry

        if result == '':
            result = 'No downloads'
        return result

    @cherrypy.expose
    @require_auth()
    def sync_to_calibre(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if 'CalSync' in [n.name for n in list(threading.enumerate())]:
            msg = 'Calibre Sync is already running'
        else:
            self.label_thread('CalSync')
            cookie = cherrypy.request.cookie
            if cookie and 'll_uid' in list(cookie.keys()):
                userid = cookie['ll_uid'].value
                msg = sync_calibre_list(userid=userid)
                self.label_thread('WEBSERVER')
            else:
                msg = "No userid found"
        return msg

    @cherrypy.expose
    @require_auth()
    def sync_to_hardcover(self, confirmed=False, readonly=False, ignore=False):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('WEB-HCSYNC')
        # Convert string parameters to boolean
        if isinstance(confirmed, str):
            confirmed = confirmed.lower() in ('true', '1', 'yes')
        if isinstance(readonly, str):
            readonly = readonly.lower() in ('true', '1', 'yes')
        if isinstance(ignore, str):
            ignore = ignore.lower() in ('true', '1', 'yes')
        # If ignore is True, set readonly to True to prevent sending updates to HC
        if ignore:
            readonly = True
        msg = hc.hc_sync(library='', userid=None, confirmed=confirmed, readonly=readonly)
        self.label_thread('WEBSERVER')
        return msg

    @cherrypy.expose
    @require_auth()
    def sync_to_goodreads(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        self.label_thread('WEB-GRSYNC')
        msg = grsync.sync_to_gr()
        self.label_thread('WEBSERVER')
        return msg

    @cherrypy.expose
    @require_auth()
    def grauth_step1(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if 'gr_api' in kwargs:
            self.validate_param("goodreads api", kwargs['gr_api'], ['<', '>', '='], 404)
            CONFIG.set_str('GR_API', kwargs['gr_api'])
        if 'gr_secret' in kwargs:
            self.validate_param("goodreads secret", kwargs['gr_secret'], ['<', '>', '='], 404)
            CONFIG.set_str('GR_SECRET', kwargs['gr_secret'])
        ga = grsync.GrAuth()
        res = ga.goodreads_oauth1()
        return res

    @cherrypy.expose
    @require_auth()
    def grauth_step2(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        ga = grsync.GrAuth()
        res = ga.goodreads_oauth2()
        if "Authorisation complete" in res:
            CONFIG.set_bool('GR_SYNC', True)
        return res

    @cherrypy.expose
    @require_auth()
    def test_hcauth(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        if 'userid' in kwargs and 'hc_token' in kwargs:
            res = hc.test_auth(userid=kwargs['userid'], token=kwargs['hc_token'])
        elif 'userid' in kwargs:
            res = hc.test_auth(userid=kwargs['userid'], token=None)
        elif 'hc_token' in kwargs:
            res = hc.test_auth(userid=None, token=kwargs['hc_token'])
        else:
            res = hc.test_auth(userid=None, token=None)
        if str(res).isnumeric():
            res = f"Pass: whoami={res}"
        return res

    @cherrypy.expose
    @require_auth()
    def test_grauth(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'gr_api' in kwargs:
            if self.validate_param("goodreads api", kwargs['gr_api'], ['<', '>', '='], None):
                CONFIG.set_str('GR_API', kwargs['gr_api'])
            else:
                fail += "api "
        if 'gr_secret' in kwargs:
            if self.validate_param("goodreads secret", kwargs['gr_secret'], ['<', '>', '='], None):
                CONFIG.set_str('GR_SECRET', kwargs['gr_secret'])
            else:
                fail += 'secret '
        if 'gr_oauth_token' in kwargs:
            if self.validate_param("goodreads oauth token", kwargs['gr_oauth_token'], ['<', '>', '='], None):
                CONFIG.set_str('GR_OAUTH_TOKEN', kwargs['gr_oauth_token'])
            else:
                fail += 'oauth_token '
        if 'gr_oauth_secret' in kwargs:
            if self.validate_param("goodreads oauth secret", kwargs['gr_oauth_secret'], ['<', '>', '='], None):
                CONFIG.set_str('GR_OAUTH_SECRET', kwargs['gr_oauth_secret'])
            else:
                fail += "oauth_secret "
        if fail:
            res = f'gr_auth failed, bad parameter: {fail}'
        else:
            res = grsync.test_auth()
        if res.startswith('Pass:'):
            CONFIG.save_config_and_backup_old(section='API')
        return res

    # NOTIFIERS #########################################################

    @cherrypy.expose
    @require_auth()
    def twitter_step1(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        return notifiers.twitter_notifier._get_authorization()

    @cherrypy.expose
    @require_auth()
    def twitter_step2(self, key):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if key:
            result = notifiers.twitter_notifier._get_credentials(key)
            if result:
                CONFIG.save_config_and_backup_old(section='Twitter')
                return "Key verification successful"
            return "Unable to verify key"
        return "No Key provided"

    @cherrypy.expose
    @require_auth()
    def test_twitter(self):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        result = notifiers.twitter_notifier.test_notify()
        if result:
            return "Tweet successful, check your twitter to make sure it worked"
        return "Error sending tweet"

    @cherrypy.expose
    @require_auth()
    def test_android_pn(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'url' in kwargs:
            if self.validate_param("android_pn url", kwargs['url'], ['<', '>', '='], None):
                CONFIG.set_str('ANDROIDPN_URL', kwargs['url'])
            else:
                fail = 'url'
        if 'username' in kwargs:
            if self.validate_param("android_pn username", kwargs['username'], ['<', '>', '='], None):
                CONFIG.set_str('ANDROIDPN_USERNAME', kwargs['username'])
            else:
                fail = 'username'
        if 'broadcast' in kwargs:
            if kwargs['broadcast'] == 'True':
                CONFIG.set_bool('ANDROIDPN_BROADCAST', True)
            else:
                CONFIG.set_bool('ANDROIDPN_BROADCAST', False)
        if fail:
            result = ''
        else:
            result = notifiers.androidpn_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='AndroidPN')
            return "Test AndroidPN notice sent successfully"
        if fail:
            return f"AndroidPN failed, bad parameter: {fail}"
        return "Test AndroidPN notice failed"

    @cherrypy.expose
    @require_auth()
    def test_boxcar(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'token' in kwargs:
            if self.validate_param("boxcar token", kwargs['token'], ['<', '>'], None):
                CONFIG.set_str('BOXCAR_TOKEN', kwargs['token'])
            else:
                fail = 'token'
        if fail:
            result = ''
        else:
            result = notifiers.boxcar_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='Boxcar')
            return f"Boxcar notification successful,\n{result}"
        if fail:
            return f'boxcar failed, bad parameter: {fail}'
        return "Boxcar notification failed"

    @cherrypy.expose
    @require_auth()
    def test_pushbullet(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'token' in kwargs:
            if self.validate_param("pushbullet token", kwargs['url'], ['<', '>'], None):
                CONFIG.set_str('PUSHBULLET_TOKEN', kwargs['token'])
            else:
                fail += 'token '
        if 'device' in kwargs:
            if self.validate_param("pushbullet device", kwargs['device'], ['<', '>'], None):
                CONFIG.set_str('PUSHBULLET_DEVICEID', kwargs['device'])
            else:
                fail += 'device '
        if fail:
            result = ''
        else:
            result = notifiers.pushbullet_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='PushBullet')
            return f"Pushbullet notification successful,\n{result}"
        if fail:
            return f'Pushbullet failed, bad parameter: {fail}'
        return "Pushbullet notification failed"

    @cherrypy.expose
    @require_auth()
    def test_pushover(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'apitoken' in kwargs:
            if self.validate_param("pushover apitoken", kwargs['apitoken'], ['<', '>', '='], None):
                CONFIG.set_str('PUSHOVER_APITOKEN', kwargs['apitoken'])
            else:
                fail += 'apitoken '
        if 'keys' in kwargs:
            if self.validate_param("pushover keys", kwargs['keys'], ['<', '>', '='], None):
                CONFIG.set_str('PUSHOVER_KEYS', kwargs['keys'])
            else:
                fail += 'keys '
        if 'priority' in kwargs:
            res = check_int(kwargs['priority'], 0, positive=False)
            if res < -2 or res > 1:
                res = 0
            CONFIG.set_int('PUSHOVER_PRIORITY', res)
        if 'device' in kwargs:
            if self.validate_param("pushover device", kwargs['device'], ['<', '>', '='], None):
                CONFIG.set_str('PUSHOVER_DEVICE', kwargs['device'])
            else:
                fail += 'device '
        if fail:
            result = ''
        else:
            result = notifiers.pushover_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='Pushover')
            return f"Pushover notification successful,\n{result}"
        if fail:
            return f'Pushover failed, bad parameter: {fail}'
        return "Pushover notification failed"

    @cherrypy.expose
    @require_auth()
    def test_telegram(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'token' in kwargs:
            if self.validate_param("telegram token", kwargs['token'], ['<', '>', '='], None):
                CONFIG.set_str('TELEGRAM_TOKEN', kwargs['token'])
            else:
                fail += 'token '
        if 'userid' in kwargs:
            if self.validate_param("telegram userid", kwargs['userid'], ['<', '>', '='], None):
                CONFIG.set_str('TELEGRAM_USERID', kwargs['userid'])
            else:
                fail += 'userid '
        if fail:
            result = ''
        else:
            result = notifiers.telegram_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='Telegram')
            return "Test Telegram notice sent successfully"
        if fail:
            return f'Telegram failed, bad parameter: {fail}'
        return "Test Telegram notice failed"

    @cherrypy.expose
    @require_auth()
    def test_prowl(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'apikey' in kwargs:
            if self.validate_param("prowl apikey", kwargs['apikey'], ['<', '>', '='], None):
                CONFIG.set_str('PROWL_APIKEY', kwargs['apikey'])
            else:
                fail += 'apikey '
        if 'priority' in kwargs:
            if self.validate_param("prowl priority", kwargs['priority'], ['<', '>', '='], None):
                CONFIG.set_int('PROWL_PRIORITY', check_int(kwargs['priority'], 0))
            else:
                fail += 'priority '
        if fail:
            result = ''
        else:
            result = notifiers.prowl_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='Prowl')
            return "Test Prowl notice sent successfully"
        if fail:
            return f'Prowl failed, bad parameter: {fail}'
        return "Test Prowl notice failed"

    @cherrypy.expose
    @require_auth()
    def test_growl(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("growl host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('GROWL_HOST', kwargs['host'])
            else:
                fail += 'host '
        # if 'password' in kwargs:
        #    if self.validate_param("growl password", kwargs['password'], ['<', '>'], None):
        #        CONFIG.set_str('GROWL_PASSWORD', kwargs['password'])
        #    else:
        #        fail += 'password'
        if fail:
            result = ''
        else:
            result = notifiers.growl_notifier.test_notify()
        if result:
            CONFIG.save_config_and_backup_old(section='Growl')
            return "Test Growl notice sent successfully"
        if fail:
            return f'Growl failed, bad parameter: {fail}'
        return "Test Growl notice failed"

    @cherrypy.expose
    @require_auth()
    def test_slack(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'token' in kwargs:
            if self.validate_param("slack token", kwargs['token'], ['<', '>', '='], None):
                CONFIG.set_str('SLACK_TOKEN', kwargs['token'])
            else:
                fail += 'token '
        if 'url' in kwargs:
            if self.validate_param("slack url", kwargs['url'], ['<', '>', '='], None):
                CONFIG.set_str('SLACK_URL', kwargs['url'])
            else:
                fail += 'url'
        if fail:
            result = ''
        else:
            result = notifiers.slack_notifier.test_notify()
        if result != "ok":
            return f"Slack notification failed,\n{result}"
        if fail:
            return f'Slack failed, bad parameter: {fail}'
        CONFIG.save_config_and_backup_old(section='Slack')
        return "Slack notification successful"

    @cherrypy.expose
    @require_auth()
    def test_custom(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'script' in kwargs:
            if self.validate_param("custom script", kwargs['script'], ['<', '>', '='], None):
                CONFIG.set_str('CUSTOM_SCRIPT', kwargs['script'])
            else:
                fail = 'script'
        if fail:
            result = ''
        else:
            result = notifiers.custom_notifier.test_notify()
        if not result:
            return "Custom notification failed"
        if fail:
            return f'Custom notification failed, bad parameter: {fail}'
        CONFIG.save_config_and_backup_old(section='Custom')
        return "Custom notification successful"

    @cherrypy.expose
    @require_auth()
    def test_email(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'tls' in kwargs:
            if kwargs['tls'] == 'True':
                CONFIG.set_bool('EMAIL_TLS', True)
            else:
                CONFIG.set_bool('EMAIL_TLS', False)
        if 'ssl' in kwargs:
            if kwargs['ssl'] == 'True':
                CONFIG.set_bool('EMAIL_SSL', True)
            else:
                CONFIG.set_bool('EMAIL_SSL', False)
        if 'sendfile' in kwargs:
            if kwargs['sendfile'] == 'True':
                CONFIG.set_bool('EMAIL_SENDFILE_ONDOWNLOAD', True)
            else:
                CONFIG.set_bool('EMAIL_SENDFILE_ONDOWNLOAD', False)
        if 'emailfrom' in kwargs:
            if self.validate_param("email from", kwargs['emailfrom'], ['<', '>', '='], None):
                CONFIG.set_str('EMAIL_FROM', kwargs['emailfrom'])
            else:
                fail += 'emailfrom '
        if 'emailto' in kwargs:
            if self.validate_param("email to", kwargs['emailto'], ['<', '>', '='], None):
                CONFIG.set_str('EMAIL_TO', kwargs['emailto'])
            else:
                fail += 'emailto '
        if 'server' in kwargs:
            if self.validate_param("email smtp server", kwargs['server'], ['<', '>', '='], None):
                CONFIG.set_str('EMAIL_SMTP_SERVER', kwargs['server'])
            else:
                fail += 'server '
        if 'user' in kwargs:
            if self.validate_param("email smtp user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('EMAIL_SMTP_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'password' in kwargs:
        #    if self.validate_param("email password", kwargs['password'], ['<', '>'], None):
        #        CONFIG.set_str('EMAIL_SMTP_PASSWORD', kwargs['password'])
        #    else:
        #        fail += 'password '
        if 'port' in kwargs:
            if self.validate_param("email port", kwargs['port'], ['<', '>', '='], None):
                CONFIG.set_int('EMAIL_SMTP_PORT', check_int(kwargs['port'], 0))
            else:
                fail += 'port '
        if fail:
            result = ''
        else:
            result = notifiers.email_notifier.test_notify()
        if not result:
            return "Email notification failed"
        if fail:
            return f'email notificaton failed, bad parameter: {fail}'
        CONFIG.save_config_and_backup_old(section='Email')
        return "Email notification successful, check your email"

    # API ###############################################################

    @cherrypy.expose
    def api(self, **kwargs):
        from lazylibrarian.api import Api
        a = Api()
        # noinspection PyArgumentList
        a.check_params(**kwargs)
        return a.fetch_data

    @cherrypy.expose
    @require_auth()
    def generate_ro_api(self):
        return self.generate_api(ro=True)

    @cherrypy.expose
    @require_auth()
    def generate_api(self, ro=False):
        logger = logging.getLogger(__name__)
        api_key = hashlib.sha224(str(random.getrandbits(256)).encode('utf-8')).hexdigest()[0:32]
        if ro:
            CONFIG.set_str('API_RO_KEY', api_key)
        else:
            CONFIG.set_str('API_KEY', api_key)
        logger.info("New API generated")
        return api_key

    # ALL ELSE ##########################################################

    @staticmethod
    def valid_source(source=None):
        if str(source).lower() in ['books', 'audio', 'magazines', 'comics', 'author', 'manage', 'series', 'members']:
            return True
        logger = logging.getLogger(__name__)
        program, method, lineno = get_info_on_caller(depth=1)
        if lineno > 0:
            reason = f"{program}:{method}:{lineno}"
        else:
            reason = 'Unknown reason'
        logger.warning(f'Invalid source:{reason}: [{source}]')
        return False

    @cherrypy.expose
    @require_auth()
    def force_process(self, source=None):
        logger = logging.getLogger(__name__)
        if 'POSTPROCESSOR' not in [n.name for n in list(threading.enumerate())]:
            threading.Thread(target=process_dir, name='POSTPROCESSOR', args=[True]).start()
            schedule_job(action=SchedulerCommand.RESTART, target='PostProcessor')
        else:
            logger.debug('POSTPROCESSOR already running')
        if self.valid_source(source):
            raise cherrypy.HTTPRedirect(source)
        raise cherrypy.HTTPRedirect('index')

    @cherrypy.expose
    @require_auth()
    def force_wish(self, source=None):
        logger = logging.getLogger(__name__)
        if CONFIG.use_wishlist():
            search_wishlist()
        else:
            logger.warning('WishList search called but no wishlist providers set')
        if self.valid_source(source):
            raise cherrypy.HTTPRedirect(source)
        raise cherrypy.HTTPRedirect('index')

    @cherrypy.expose
    @require_auth()
    def force_search(self, source=None, title=None):
        self.validate_param("search title", title, ['<', '>', '='], 404)
        logger = logging.getLogger(__name__)
        if source in ["magazines", 'comics']:
            if CONFIG.use_any():
                if title:
                    title = title.replace('&amp;', '&')
                    if source == 'magazines':
                        self.search_for_mag(bookid=title)
                    elif source == 'comics':
                        self.search_for_comic(comicid=title)
                elif source == 'magazines' and 'SEARCHALLMAG' not in [
                        n.name for n in list(threading.enumerate())]:
                    threading.Thread(target=search_magazines, name='SEARCHALLMAG', args=[]).start()
                    schedule_job(action=SchedulerCommand.RESTART, target='search_magazines')
                elif source == 'comics' and 'SEARCHALLCOMICS' not in [
                        n.name for n in list(threading.enumerate())]:
                    threading.Thread(target=search_comics, name='SEARCHALLCOMICS', args=[]).start()
                    schedule_job(action=SchedulerCommand.RESTART, target='search_comics')
            else:
                logger.warning('Search called but no download providers set')
        elif source in ["books", "audio"]:
            if CONFIG.use_any():
                if 'SEARCHALLBOOKS' not in [n.name for n in list(threading.enumerate())]:
                    schedule_job(SchedulerCommand.STOP, "search_book")
                    schedule_job(SchedulerCommand.STARTNOW, "search_book")
                if CONFIG.use_rss():
                    schedule_job(SchedulerCommand.STOP, "search_rss_book")
                    schedule_job(SchedulerCommand.STARTNOW, "search_rss_book")
            else:
                logger.warning('Search called but no download providers set')

        if not self.valid_source(source):
            raise cherrypy.HTTPRedirect('index')
        raise cherrypy.HTTPRedirect(source)

    @cherrypy.expose
    @require_auth()
    def manage(self, **kwargs):
        self.check_permitted(lazylibrarian.perm_managebooks)
        types = []
        if CONFIG.get_bool('EBOOK_TAB'):
            types.append('eBook')
        if CONFIG.get_bool('AUDIO_TAB'):
            types.append('AudioBook')
        if not types:
            raise cherrypy.HTTPRedirect('authors')
        library = types[0]
        which_status = 'Wanted'
        if 'library' in kwargs and kwargs['library'] in types:
            library = kwargs['library']
        if 'whichStatus' in kwargs and kwargs['whichStatus']:
            which_status = kwargs['whichStatus']
        if which_status == 'None':
            which_status = "Wanted"
        return serve_template(templatename="managebooks.html", title=f"Manage {library}s",
                              books=[], types=types, library=library, whichStatus=which_status)

    @cherrypy.expose
    @require_auth()
    def test_deluge(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        dlcommslogger = logging.getLogger('special.dlcomms')
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("deluge host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('DELUGE_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'base' in kwargs:
            if self.validate_param("deluge base", kwargs['base'], ['<', '>', '='], None):
                CONFIG.set_str('DELUGE_BASE', kwargs['base'])
            else:
                fail += 'base '
        if 'cert' in kwargs:
            if self.validate_param("deluge cert", kwargs['cert'], ['<', '>', '='], None):
                CONFIG.set_str('DELUGE_CERT', kwargs['cert'])
            else:
                fail += 'cert '
        if 'port' in kwargs:
            CONFIG.set_int('DELUGE_PORT', check_int(kwargs['port'], 0))
        # if 'pwd' in kwargs:
        #    if self.validate_param("deluge pass", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('DELUGE_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'label' in kwargs:
            if self.validate_param("deluge label", kwargs['label'], ['<', '>', '='], None):
                CONFIG.set_str('DELUGE_LABEL', kwargs['label'])
            else:
                fail += 'label '
        if 'user' in kwargs:
            if self.validate_param("deluge user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('DELUGE_USER', kwargs['user'])
            else:
                fail += 'user '
        if fail:
            return f"deluge failed, bad parameter: {fail}"

        try:
            if not CONFIG['DELUGE_USER']:
                # no username, talk to the webui
                msg = deluge.check_link()
                if 'FAILED' in msg:
                    return msg
            else:
                # if there's a username, talk to the daemon directly
                # if daemon, no cert used
                CONFIG.set_str('DELUGE_CERT', '')
                # and host must not contain http:// or https://
                host = CONFIG['DELUGE_HOST']
                host = host.replace('https://', '').replace('http://', '')
                CONFIG.set_str('DELUGE_HOST', host)
                client = DelugeRPCClient(CONFIG['DELUGE_HOST'],
                                         check_int(CONFIG['DELUGE_PORT'], 0),
                                         CONFIG['DELUGE_USER'],
                                         CONFIG['DELUGE_PASS'])
                client.connect()
                msg = "Deluge: Daemon connection Successful\n"
                if CONFIG['DELUGE_LABEL']:
                    labels = client.call('label.get_labels')
                    if labels:
                        dlcommslogger.debug(f"Valid labels: {str(labels)}")
                    else:
                        msg += "Deluge daemon seems to have no labels set\n"

                    mylabel = CONFIG['DELUGE_LABEL'].lower()
                    if mylabel != CONFIG['DELUGE_LABEL']:
                        CONFIG.set_str('DELUGE_LABEL', mylabel)

                    labels = [make_unicode(s) for s in labels]
                    if mylabel not in labels:
                        res = client.call('label.add', mylabel)
                        if not res:
                            msg += f"Label [{CONFIG['DELUGE_LABEL']}] was added"
                        else:
                            msg = str(res)
                    else:
                        msg += f'Label [{CONFIG["DELUGE_LABEL"]}] is valid'
            # success, save settings
            CONFIG.save_config_and_backup_old(section='DELUGE')
            return msg

        except Exception as e:
            msg = "Deluge: Daemon connection FAILED\n"
            if 'Connection refused' in str(e):
                msg += str(e)
                msg += "Check Deluge daemon HOST and PORT settings"
            elif 'need more than 1 value' in str(e):
                msg += "Invalid USERNAME or PASSWORD"
            else:
                msg += type(e).__name__ + ' ' + str(e)
            return msg

    @cherrypy.expose
    @require_auth()
    def test_sabnzbd(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("sab host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('SAB_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'port' in kwargs:
            CONFIG.set_int('SAB_PORT', check_int(kwargs['port'], 0))
        if 'user' in kwargs:
            if self.validate_param("sab user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('SAB_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("sab pass", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('SAB_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'api' in kwargs:
            if self.validate_param("sab api", kwargs['api'], ['<', '>', '='], None):
                CONFIG.set_str('SAB_API', kwargs['api'])
            else:
                fail += 'api '
        if 'cat' in kwargs:
            if self.validate_param("sab cat", kwargs['cat'], ['<', '>', '='], None):
                CONFIG.set_str('SAB_CAT', kwargs['cat'])
            else:
                fail += 'cat '
        if 'subdir' in kwargs:
            if self.validate_param("sab subdir", kwargs['subdir'], ['<', '>', '='], None):
                CONFIG.set_str('SAB_SUBDIR', kwargs['subdir'])
            else:
                fail += 'subdir '
        if fail:
            msg = f"sab failed, bad parameter: {fail}"
        else:
            msg = sabnzbd.check_link()
            if 'success' in msg:
                CONFIG.save_config_and_backup_old(section='sab_nzbd')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_nzbget(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("nzbget host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('NZBGET_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'port' in kwargs:
            CONFIG.set_int('NZBGET_PORT', check_int(kwargs['port'], 0))
        if 'user' in kwargs:
            if self.validate_param("nzbget user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('NZBGET_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("nzbget pass", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('NZBGET_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'cat' in kwargs:
            if self.validate_param("nzbget category", kwargs['cat'], ['<', '>', '='], None):
                CONFIG.set_str('NZBGET_CATEGORY', kwargs['cat'])
            else:
                fail += 'cat '
        if 'pri' in kwargs:
            CONFIG.set_int('NZBGET_PRIORITY', check_int(kwargs['pri'], 0))
        if fail:
            msg = f'NzbGet failed, bad parameter: {fail}'
        else:
            msg = nzbget.check_link()
        if 'success' in msg:
            CONFIG.save_config_and_backup_old(section='NZBGet')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_transmission(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("transmission host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('TRANSMISSION_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'base' in kwargs:
            if self.validate_param("transmission base", kwargs['base'], ['<', '>', '='], None):
                CONFIG.set_str('TRANSMISSION_BASE', kwargs['base'])
            else:
                fail += 'base '
        if 'port' in kwargs:
            CONFIG.set_int('TRANSMISSION_PORT', check_int(kwargs['port'], 0))
        if 'user' in kwargs:
            if self.validate_param("transmission user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('TRANSMISSION_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("transmission pass", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('TRANSMISSION_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if fail:
            msg = f'Transmission failed, bad parameter: {fail}'
        else:
            msg = transmission.check_link()
        if 'success' in msg:
            CONFIG.save_config_and_backup_old(section='TRANSMISSION')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_qbittorrent(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("qbit host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('QBITTORRENT_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'port' in kwargs:
            CONFIG.set_int('QBITTORRENT_PORT', check_int(kwargs['port'], 0))
        if 'base' in kwargs:
            if self.validate_param("qbit base", kwargs['base'], ['<', '>', '='], None):
                CONFIG.set_str('QBITTORRENT_BASE', kwargs['base'])
            else:
                fail += 'base '
        if 'user' in kwargs:
            if self.validate_param("qbit user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('QBITTORRENT_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("qbit password", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('QBITTORRENT_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'label' in kwargs:
            if self.validate_param("qbit label", kwargs['label'], ['<', '>', '='], None):
                CONFIG.set_str('QBITTORRENT_LABEL', kwargs['label'])
            else:
                fail += 'label '
        if 'ignore_ssl' in kwargs:
            CONFIG.set_bool('QBITTORRENT_IGNORE_SSL', kwargs['ignore_ssl'] == '1')
        if fail:
            msg = f'QbitTorrent failed, bad parameter: {fail}'
        else:
            msg = qbittorrent.check_link()
        if 'success' in msg:
            CONFIG.save_config_and_backup_old(section='QBITTORRENT')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_utorrent(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("utorrent host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('UTORRENT_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'port' in kwargs:
            CONFIG.set_int('UTORRENT_PORT', check_int(kwargs['port'], 0))
        if 'base' in kwargs:
            if self.validate_param("utorrent base", kwargs['base'], ['<', '>', '='], None):
                CONFIG.set_str('UTORRENT_BASE', kwargs['base'])
            else:
                fail += 'base '
        if 'user' in kwargs:
            if self.validate_param("utorrent user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('UTORRENT_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("utorrent password", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('UTORRENT_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'label' in kwargs:
            if self.validate_param("utorrent label", kwargs['label'], ['<', '>', '='], None):
                CONFIG.set_str('UTORRENT_LABEL', kwargs['label'])
            else:
                fail += 'label '
        if fail:
            msg = f'utorrent failed, bad parameter: {fail}'
        else:
            msg = utorrent.check_link()
        if 'success' in msg:
            CONFIG.save_config_and_backup_old(section='UTORRENT')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_rtorrent(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("rtorrent host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('RTORRENT_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'dir' in kwargs:
            if self.validate_param("rtorrent dir", kwargs['dir'], ['<', '>', '='], None):
                CONFIG.set_str('RTORRENT_DIR', kwargs['dir'])
            else:
                fail += 'dir '
        if 'user' in kwargs:
            if self.validate_param("rtorrent user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('RTORRENT_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("rtorrent password", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('RTORRENT_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'psaaword '
        if 'label' in kwargs:
            if self.validate_param("rtorrent label", kwargs['label'], ['<', '>', '='], None):
                CONFIG.set_str('RTORRENT_LABEL', kwargs['label'])
            else:
                fail += 'label '
        if fail:
            msg = f'rtorrent failed, bad parameter: {fail}'
        else:
            msg = rtorrent.check_link()
        if 'success' in msg:
            CONFIG.save_config_and_backup_old(section='RTORRENT')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_synology(self, **kwargs):
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        thread_name("WEBSERVER")
        fail = ''
        if 'host' in kwargs:
            if self.validate_param("synology host", kwargs['host'], ['<', '>', '='], None):
                CONFIG.set_str('SYNOLOGY_HOST', kwargs['host'])
            else:
                fail += 'host '
        if 'port' in kwargs:
            CONFIG.set_int('SYNOLOGY_PORT', check_int(kwargs['port'], 0))
        if 'user' in kwargs:
            if self.validate_param("synology user", kwargs['user'], ['<', '>', '='], None):
                CONFIG.set_str('SYNOLOGY_USER', kwargs['user'])
            else:
                fail += 'user '
        # if 'pwd' in kwargs:
        #    if self.validate_param("synology password", kwargs['pwd'], ['<', '>'], None):
        #        CONFIG.set_str('SYNOLOGY_PASS', kwargs['pwd'])
        #    else:
        #        fail += 'password '
        if 'dir' in kwargs:
            if self.validate_param("synology dir", kwargs['dir'], ['<', '>', '='], None):
                CONFIG.set_str('SYNOLOGY_DIR', kwargs['dir'])
            else:
                fail += 'dir '
        if fail:
            msg = f'synology failed, bad parameter: {fail}'
        else:
            msg = synology.check_link()
        if 'success' in msg:
            CONFIG.save_config_and_backup_old(section='SYNOLOGY')
        return msg

    @cherrypy.expose
    @require_auth()
    def test_ffmpeg(self, **kwargs):
        thread_name("WEBSERVER")
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        postprocesslogger = logging.getLogger('special.postprocess')
        if 'prg' in kwargs and kwargs['prg']:
            if self.validate_param("ffmpeg program", kwargs['prg'], ['<', '>', '='], None):
                CONFIG.set_str('FFMPEG', kwargs['prg'])
            else:
                return 'ffmpeg failed, bad parameter: program'
        ffmpeg = CONFIG['FFMPEG']
        try:
            if postprocesslogger.isEnabledFor(logging.DEBUG):
                ffmpeg_env = os.environ.copy()
                ffmpeg_env["FFREPORT"] = DIRS.get_logfile(
                    f"ffmpeg-test-{now().replace(':', '-').replace(' ', '-')}.log")
                params = [ffmpeg, "-version", "-report"]
            else:
                params = [ffmpeg, "-version"]
                ffmpeg_env = None

            if os.name != 'nt':
                res = subprocess.check_output(params, preexec_fn=lambda: os.nice(10),
                                              stderr=subprocess.STDOUT, env=ffmpeg_env)
            else:
                res = subprocess.check_output(params, stderr=subprocess.STDOUT, env=ffmpeg_env)

            ff_ver = make_unicode(res).strip().split("Copyright")[0].split()[-1]
            lazylibrarian.FFMPEGVER = ff_ver
            return f"Found ffmpeg version {ff_ver}"
        except Exception as e:
            lazylibrarian.FFMPEGVER = None
            return f"ffmpeg -version failed: {type(e).__name__} {str(e)}"

    @cherrypy.expose
    @require_auth()
    def test_ebook_convert(self, **kwargs):
        thread_name("WEBSERVER")
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if 'prg' in kwargs and kwargs['prg']:
            if self.validate_param("ebook convert", kwargs['prg'], ['<', '>', '='], None):
                CONFIG.set_str('EBOOK_CONVERT', kwargs['prg'])
            else:
                return "ebook-convert failed, bad parameter"

        prg = CONFIG['EBOOK_CONVERT']
        try:
            params = [prg, "--version"]
            res = subprocess.check_output(params, stderr=subprocess.STDOUT)
            res = make_unicode(res).strip().split("(")[1].split(")")[0]
            return f"Found ebook-convert version {res}"
        except Exception as e:
            return f"ebook-convert --version failed: {type(e).__name__} {str(e)}"

    @cherrypy.expose
    @require_auth()
    def test_calibredb(self, **kwargs):
        thread_name("WEBSERVER")
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if 'prg' in kwargs and kwargs['prg']:
            if self.validate_param("calibredb", kwargs['prg'], ['<', '>', '='], None):
                CONFIG.set_str('IMP_CALIBREDB', kwargs['prg'])
            else:
                return 'calibredb failed, bad parameter: program'
        return calibre_test()

    @cherrypy.expose
    @require_auth()
    def test_preprocessor(self, **kwargs):
        thread_name("WEBSERVER")
        cherrypy.response.headers['Cache-Control'] = "max-age=0,no-cache,no-store"
        if 'prg' in kwargs and kwargs['prg']:
            if self.validate_param("preprocessor", kwargs['prg'], ['<', '>', '='], None):
                CONFIG.set_str('EXT_PREPROCESS', kwargs['prg'])
            else:
                return 'preprocessor failed, bad parameter: program'
        if len(CONFIG['EXT_PREPROCESS']):
            params = [CONFIG['EXT_PREPROCESS'], 'test', '']
            rc, res, err = run_script(params)
            if rc:
                return f"Preprocessor returned {rc}: res[{res}] err[{err}]"
        else:
            return "No preprocessor set in config"
        return res

    @cherrypy.expose
    def opds(self, **kwargs):
        self.label_thread('OPDS Server')
        op = OPDS()
        op.check_params(**kwargs)
        data = op.fetch_data()
        return data

    def send_file(self, myfile, name=None, email=False):
        logger = logging.getLogger(__name__)
        self.check_permitted(lazylibrarian.perm_download)
        userid = ''
        if CONFIG.get_bool('USER_ACCOUNTS'):
            cookie = cherrypy.request.cookie
            if 'll_uid' in list(cookie.keys()):
                userid = cookie['ll_uid'].value
            msg = ''
            if email and userid:
                db = database.DBConnection()
                res = db.match('SELECT UserName,SendTo from users where UserID=?', (userid,))
                db.close()
                if res and res['SendTo']:
                    db = database.DBConnection()
                    sent = []
                    not_sent = []
                    # sending files to kindles only seems to work if separate emails
                    if ',' in res['SendTo']:
                        addrs = get_list(res['SendTo'])
                    else:
                        addrs = [res['SendTo']]
                    for addr in addrs:
                        logger.debug(f"Emailing {myfile} to {addr}")
                        if name:
                            msg = lazylibrarian.NEWFILE_MSG.replace('{name}', name).replace(
                                '{method}', ' is attached').replace('{link}', '')
                        result = notifiers.email_notifier.email_file(subject="Message from LazyLibrarian",
                                                                     message=msg, to_addr=addr, files=[myfile])
                        if result:
                            db.action('INSERT into sent_file (WhenSent, UserID, Addr, FileName) VALUES (?, ?, ?, ?)',
                                      (str(int(time.time())), userid, addr, os.path.basename(myfile)))
                            sent.append(addr)
                        else:
                            not_sent.append(addr)
                    db.close()
                    msg = ''
                    if sent:
                        msg = f"Emailed file {os.path.basename(myfile)} to {','.join(sent)} "
                        logger.debug(msg)
                    if not_sent:
                        msg2 = f"Failed to email file {os.path.basename(myfile)} to {','.join(not_sent)}"
                        logger.error(msg2)
                        msg += msg2
                return serve_template(templatename="choosetype.html", title='Send file',
                                      pop_message=msg, pop_types='', bookid='', valid='', email=email)
        if not name:
            name = os.path.basename(myfile)
        if path_isfile(myfile):
            if userid:
                db = database.DBConnection()
                db.action('INSERT into sent_file (WhenSent, UserID, Addr, FileName) VALUES (?, ?, ?, ?)',
                          (str(int(time.time())), userid, 'Open', name))
                db.close()
            return serve_file(myfile, mime_type(myfile), "attachment", name=name)
        logger.error(f"No file [{myfile}]")
        return None

    # TELEMETRY ##########################################################

    @cherrypy.expose
    @require_auth()
    def get_telemetry_data(self, **kwargs):
        send_config = kwargs['send_config']
        send_usage = kwargs['send_usage']
        return TELEMETRY.get_data_for_ui_preview(send_config, send_usage)

    @cherrypy.expose
    @require_auth()
    def reset_telemetry_usage_data(self):
        return TELEMETRY.clear_usage_data()

    @cherrypy.expose
    @require_auth()
    def submit_telemetry_data(self, **kwargs):
        server = kwargs['server']
        send_config = kwargs['send_config']
        send_usage = kwargs['send_usage']
        result, _ = TELEMETRY.submit_data(server, send_config, send_usage)
        return result

    @cherrypy.expose
    @require_auth()
    def test_telemetry_server(self, **kwargs):
        return TELEMETRY.test_server(kwargs['server'])

    @cherrypy.expose
    @require_auth()
    def set_current_tabs(self, **kwargs):
        if 'config_tab' in kwargs:
            CONFIG.set_from_ui('CONFIG_TAB_NUM', check_int(kwargs['config_tab'], 1))

    # noinspection PyUnusedLocal
    @cherrypy.expose
    @require_auth()
    def enable_telemetry(self, **kwargs):
        CONFIG.set_bool('TELEMETRY_ENABLE', True)
        CONFIG.set_int('TELEMETRY_INTERVAL', 6)
        CONFIG.set_url('TELEMETRY_SERVER', 'https://lazylibrarian.telem.ch')
        CONFIG.save_config_and_backup_old(section='Telemetry')
        return "Thank you for enabling Telemetry"
