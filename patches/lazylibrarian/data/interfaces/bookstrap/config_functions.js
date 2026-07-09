<script type="text/javascript">
    (function() {
        document.addEventListener("DOMContentLoaded", function () {
            // Checkbox handler, plus either hide/show or slide it down/up
            function toggleElement(checkboxId, elementId, reverse=false) {
                function updateState(state, useSlide) {
                    const showit = (state ? !reverse : reverse) //  XOR in js
                    if (useSlide) {
                        $(elementId)[showit ? "slideDown" : "slideUp"]();
                    } else {
                        $(elementId)[showit ? "show" : "hide"]();
                    }
                }
                const checked = $(checkboxId).is(":checked");
                updateState(checked, false);

                $(checkboxId).click(function () {
                    updateState(this.checked, true);
                })
            }

            // Handler for dropdown that has a detailed element (Log options)
            function toggleSelectElement(selectId, elementId, detailedValue) {
                function updateState(state) {
                    $(elementId)[state ? "show" : "hide"]();
                }
                const selectedValue = $(selectId).val();
                const show_detailed = selectedValue === detailedValue;
                updateState(show_detailed)

                $(selectId).change(function() {
                    updateState( $(selectId).val() === detailedValue);
                });
            }

            // Register all the elements that need to react to change of state
            // Interface
            toggleElement("#https_enabled", "#https_options");
            toggleElement("#ssl_verify", "#ssl_options");
            toggleElement("#user_accounts", "#admin_options");
            toggleElement("#user_accounts", "#rss_options");
            toggleElement("#user_accounts", "#webserver_options", true);
            toggleElement("#api_enabled", "#api_options");
            toggleElement("#proxy_auth", "#proxy_auth_options");
            toggleElement("#proxy_register", "#proxy_register_options");
            toggleElement("#opds_enabled", "#opdsoptions");
            toggleElement("#audio_tab", "#graudio_options"); // A sub-setting on the Importing page
            toggleSelectElement("#log_type", "#debug_options", "Debug");

            //Downloaders
            toggleElement("#tor_downloader_deluge", "#deluge_options");
            toggleElement("#tor_downloader_transmission", "#transmission_options");
            toggleElement("#tor_downloader_rtorrent", "#rtorrent_options");
            toggleElement("#tor_downloader_utorrent", "#utorrent_options");
            toggleElement("#tor_downloader_qbittorrent", "#qbittorrent_options");
            toggleElement("#tor_downloader_blackhole", "#tor_blackhole_options");
            toggleElement("#nzb_downloader_sabnzbd", "#sabnzbd_options");
            toggleElement("#nzb_downloader_nzbget", "#nzbget_options");
            toggleElement("#use_synology", "#synology_options");
            toggleElement("#nzb_downloader_blackhole", "#nzb_blackhole_options");
            toggleElement("#opds_authentication", "#opdscredentials");

            // Importing
            toggleElement("#hc_api", "#hc_options");
            toggleElement("#hc_sync", "#hcsync_options");
            toggleElement("#hc_syncreadonly", "#hc_sync_limit_group", true);
            toggleElement("#gr_sync", "#grsync_options");
            toggleElement("#gr_syncuser", "#gruser_options");
            toggleElement("#gr_syncuser", "#grlibrary_options");

            // Providers
            toggleElement("#show_direct_prov", "#direct_prov");
            toggleElement("#show_newz_prov", "#newz_prov");
            toggleElement("#show_torz_prov", "#torz_prov");
            toggleElement("#show_rss_prov", "#rss_prov");
            toggleElement("#show_tor_prov", "#tor_prov");
            toggleElement("#show_irc_prov", "#irc_prov");
            toggleElement("#rss_enabled", "#rssoptions");

            // Processing
            toggleElement("#calibre_use_server", "#calibre_options");

            // Notifications
            toggleElement("#use_twitter", "#twitteroptions");
            toggleElement("#use_boxcar", "#boxcaroptions");
            toggleElement("#use_pushbullet", "#pushbulletoptions");
            toggleElement("#use_pushover", "#pushoveroptions");
            toggleElement("#use_androidpn", "#androidpnoptions");
            toggleElement("#androidpn_broadcast", "#androidpn_username");
            toggleElement("#use_prowl", "#prowloptions");
            toggleElement("#use_growl", "#growloptions");
            toggleElement("#use_telegram", "#telegramoptions");
            toggleElement("#use_slack", "#slackoptions");
            toggleElement("#use_custom", "#customoptions");
            toggleElement("#use_email", "#emailoptions");
            toggleElement("#use_email_custom_format", "#email_custom_format_options");

            // Telemetry
            toggleElement("#telemetry_enable", "#telemetry_options");
        });
    })();

    function initThisPage()
    {
        "use strict";
        // when the page first loads, hide all tab headers and panels
        $("li[role='presentation']").attr("aria-selected", "false");
        $("li[role='presentation']").removeClass('active');
        //$("div[role='tabpanel']").attr("aria-hidden", "true");
        $("div[role='tab-table']").removeClass('active');
        // which one do we want to show
        const tabnum = $("#config_tab_num").val();
        const tabid = $("#" + tabnum);
        const tabpanel = tabid.attr('aria-controls');
        const tabpanelid = $("#" + tabpanel);

             if ( tabnum === '8' )  {
                $("#savefilters").removeClass('hidden');
                $("#loadfilters").removeClass('hidden');
            }
            else {
                    $("#savefilters").addClass('hidden');
                    $("#loadfilters").addClass('hidden');
            }
             if ( tabnum === '4' )  {
                $("#showblocked").removeClass('hidden');
            }
            else {
                    $("#showblocked").addClass('hidden');
            }

        // show the tab header and panel we want
        tabpanelid.addClass('active');
        tabid.attr("aria-selected", "true");
        tabid.addClass('active');
        $("div[role='tab-table']").removeClass('hidden');

        // when a tab is clicked
        $("li[role='presentation']").click(function(){
            const tabnum = $(this).attr('id');
            $("#config_tab_num").val(tabnum);
            $.get('set_current_tabs', {'config_tab': tabnum });
             if ( tabnum === '8' )  {
                $("#savefilters").removeClass('hidden');
                $("#loadfilters").removeClass('hidden');
            }
            else {
                    $("#savefilters").addClass('hidden');
                    $("#loadfilters").addClass('hidden');
            }
             if ( tabnum === '4' )  {
                $("#showblocked").removeClass('hidden');
            }
            else {
                    $("#showblocked").addClass('hidden');
            }
         });

        $('#showblocked').on('click', function() {
            $.get('showblocked', function(data) {
                bootbox.dialog({
                    title: 'Provider Status',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        prompt: {
                            label: "Clear Blocklist",
                            className: 'btn-danger',
                            callback: function(){ $.get("clearblocked", function(e) {}); }
                        },
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $("button[role='testprov']").on('click', function() {
            let prov = $(this).val();
            let host = ""
            let api = ""
            if ( 'KAT TPB TDL LIME'.indexOf(prov) >= 0 ) {
                host = $("#" + prov.toLowerCase() + "_host").val();
                api = $("#" + prov.toLowerCase() + "_seeders").val();
            }
            if ( 'BFI'.indexOf(prov) >= 0 ) {
                host = $("#" + prov.toLowerCase() + "_host").val();
            }
            if ( 'BOK'.indexOf(prov) >= 0 ) {
                host = $("#" + prov.toLowerCase() + "_host").val();
                let email = $("#" + prov.toLowerCase() + "_email").val();
                let pass = $("#" + prov.toLowerCase() + "_pass").val();
                let langs = $("#" + prov.toLowerCase() + "_search_lang").val();
                api = email + ' : ' + pass + ' : ' + langs
            }
            if ( prov.indexOf('gen_') === 0 ) {
                host = $("#" + prov.toLowerCase() + "_host").val();
                api = $("#" + prov.toLowerCase() + "_search").val();
            }
            if ( prov.indexOf('newznab_') === 0 ) {
                host = $("#" + prov.toLowerCase() + "_host").val();
                api = $("#" + prov.toLowerCase() + "_api").val();
            }
            if ( prov.indexOf('torznab_') === 0 ) {
                host = $("#" + prov.toLowerCase() + "_host").val();
                let ap = $("#" + prov.toLowerCase() + "_api").val();
                let seed = $("#" + prov.toLowerCase() + "_seeders").val();
                api = ap + ' : ' + seed
            }
            if ( prov.indexOf('rss_') === 0 ) {
                host = $("#" + prov.toLowerCase() + "_host").val();
            }
            if ( prov.indexOf('irc_') === 0 ) {
                let server = $("#" + prov.toLowerCase() + "_server").val();
                let channel = $("#" + prov.toLowerCase() + "_channel").val();
                host = server + ' : ' + channel
                let nick = $("#" + prov.toLowerCase() + "_botnick").val();
                let search = $("#" + prov.toLowerCase() + "_search").val();
                api = nick + ' : ' + search
            }
            if ( prov.indexOf('apprise_') === 0 ) {
                host = $("#" + prov.toLowerCase() + "_url").val();
                let s = ($("#" + prov.toLowerCase() + "_snatch").prop('checked') === true) ? '1' : '0';
                let d = ($("#" + prov.toLowerCase() + "_download").prop('checked') === true) ? '1' : '0';
                api = s + ':' + d
            }
            $("#myAlert").removeClass('hidden');
            $.get('testprovider', {'name': prov, 'host': host, 'api': api},
            function(data) {
                $("#myAlert").addClass('hidden');
                bootbox.dialog({
                    title: 'Test Result',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#show_stats').on('click', function() {
            $.get('show_stats', function(data) {
                bootbox.dialog({
                    title: 'Database Stats',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#show_jobs').on('click', function() {
            $.get('show_jobs', function(data) {
                bootbox.dialog({
                    title: 'Job Status',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        stopit: {
                            label: "<i class=\"fa fa-ban\"></i> Stop Jobs",
                            className: 'btn-warning',
                            callback: function(){ $.get("stop_jobs", function(e) {}); }
                        },
                        restart: {
                            label: "<i class=\"fa fa-sync\"></i> Restart Jobs",
                            className: 'btn-info',
                            callback: function(){ $.get("restart_jobs", function(e) {}); }
                        },
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#show_apprise').on('click', function() {
            $.get('show_apprise', function(data) {
                bootbox.dialog({
                    title: 'Supported Types',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#test_sabnzbd').on('click', function() {
            let host = $.trim($("#sab_host").val());
            let port = $.trim($("#sab_port").val());
            let user = $.trim($("#sab_user").val());
            let pwd = $.trim($("#sab_pass").val());
            let api = $.trim($("#sab_api").val());
            let cat = $.trim($("#sab_cat").val());
            let subdir = $.trim($("#sab_subdir").val());
            $.get("test_sabnzbd", {'host': host, 'port': port, 'user': user, 'pwd': pwd, 'api': api, 'cat': cat, 'subdir': subdir},
            function(data) {
                bootbox.dialog({
                    title: 'SABnzbd Connection',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#test_nzbget').on('click', function() {
            let host = $.trim($("#nzbget_host").val());
            let port = $.trim($("#nzbget_port").val());
            let user = $.trim($("#nzbget_user").val());
            let pwd = $.trim($("#nzbget_pass").val());
            let cat = $.trim($("#nzbget_category").val());
            let pri = $.trim($("#nzbget_priority").val());
            $.get('test_nzbget', {'host': host, 'port': port, 'user': user, 'pwd': pwd, 'cat': cat, 'pri': pri},
                function(data) {
                bootbox.dialog({
                    title: 'NZBget Connection',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#test_synology').on('click', function() {
            let host = $.trim($("#synology_host").val());
            let port = $.trim($("#synology_port").val());
            let user = $.trim($("#synology_user").val());
            let pwd = $.trim($("#synology_pass").val());
            let dir = $.trim($("#synology_dir").val());
            $.get('test_synology', {'host': host, 'port': port, 'user': user, 'pwd': pwd, 'dir': dir},
                function(data) {
                bootbox.dialog({
                    title: 'Synology Connection',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#test_deluge').on('click', function() {
            let host = $.trim($("#deluge_host").val());
            let base = $.trim($("#deluge_base").val());
            let cert = $.trim($("#deluge_cert").val());
            let port = $.trim($("#deluge_port").val());
            let user = $.trim($("#deluge_user").val());
            let pwd = $.trim($("#deluge_pass").val());
            let label = $.trim($("#deluge_label").val());
            $.get("test_deluge", {'host': host, 'port': port, 'base': base, 'cert': cert, 'user': user, 'pwd': pwd, 'label': label},
                function(data) {
                    bootbox.dialog({
                    title: 'Deluge Connection',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#test_transmission').on('click', function() {
            let host = $.trim($("#transmission_host").val());
            let port = $.trim($("#transmission_port").val());
            let base = $.trim($("#transmission_base").val());
            let user = $.trim($("#transmission_user").val());
            let pwd = $.trim($("#transmission_pass").val());
            $.get('test_transmission', {'host': host, 'port': port, 'base': base, 'user': user, 'pwd': pwd},
                function(data) {
                bootbox.dialog({
                    title: 'Transmission Connection',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#test_qbittorrent').on('click', function() {
            let host = $.trim($("#qbittorrent_host").val());
            let port = $.trim($("#qbittorrent_port").val());
            let base = $.trim($("#qbittorrent_base").val());
            let user = $.trim($("#qbittorrent_user").val());
            let pwd = $.trim($("#qbittorrent_pass").val());
            let label = $.trim($("#qbittorrent_label").val());
            let ignore_ssl = $("#qbittorrent_ignore_ssl").is(':checked') ? '1' : '0';
            $.get('test_qbittorrent', {'host': host, 'port': port, 'base': base, 'user': user, 'pwd': pwd, 'label': label, 'ignore_ssl': ignore_ssl},
                function(data) {
                bootbox.dialog({
                    title: 'qBittorrent Connection',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#test_utorrent').on('click', function() {
            let host = $.trim($("#utorrent_host").val());
            let port = $.trim($("#utorrent_port").val());
            let base = $.trim($("#utorrent_base").val());
            let user = $.trim($("#utorrent_user").val());
            let pwd = $.trim($("#utorrent_pass").val());
            let label = $.trim($("#utorrent_label").val());
            $.get('test_utorrent', {'host': host, 'port': port, 'base': base, 'user': user, 'pwd': pwd, 'label': label},
                function(data) {
                bootbox.dialog({
                    title: 'uTorrent Connection',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#test_rtorrent').on('click', function() {
            let host = $.trim($("#rtorrent_host").val());
            let dir = $.trim($("#rtorrent_dir").val());
            let user = $.trim($("#rtorrent_user").val());
            let pwd = $.trim($("#rtorrent_pass").val());
            let label = $.trim($("#rtorrent_label").val());
            $.get('test_rtorrent', {'host': host, 'dir': dir, 'user': user, 'pwd': pwd, 'label': label},
                function(data) {
                bootbox.dialog({
                    title: 'rTorrent Connection',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#sysinfo').on('click', function() {
            $.get('log_header', function(data) {
                bootbox.dialog({
                    title: 'System Info',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#savefilters').on('click', function() {
            $.get('save_filters', function(data) {
                bootbox.dialog({
                    title: 'Export Filters',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#loadfilters').on('click', function() {
            $.get('load_filters', function(data) {
                bootbox.dialog({
                    title: 'Import Filters',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#test_grauth').click(function () {
            let gr_api = $.trim($("#gr_api").val());
            let gr_secret = $.trim($("#gr_secret").val());
            let oauth_token = $.trim($("#gr_oauth_token").val());
            let oauth_secret = $.trim($("#gr_oauth_secret").val());
            $.get("test_grauth", {'gr_api': gr_api, 'gr_secret': gr_secret, 'oauth_token': oauth_token, 'oauth_secret': oauth_secret},
                function (data) {
                    bootbox.dialog({
                        title: 'GoodReads Auth',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#grauth_step1').click(function () {
            let gr_api = $.trim($("#gr_api").val());
            let gr_secret = $.trim($("#gr_secret").val());
            $.get("grauth_step1", {'gr_api': gr_api, 'gr_secret': gr_secret},
                function (data) {
                if ( data.substr(0, 4) === 'http') { bootbox.dialog({
                        title: 'GoodReads Auth',
                        message: '<pre>A new tab or page should open at GoodReads to authorise lazylibrarian. Follow the prompts, then go back to LazyLibrarian and request oAuth2\nIf the page does not open, visit this link...\n'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });  window.open(data);
                }
                else { bootbox.dialog({
                        title: 'GoodReads Response',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                }
              })
        });

        $('#grauth_step2').click(function () {
            $.get("grauth_step2", {},
                function (data) { bootbox.dialog({
                        title: 'GoodReads Confirm',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary',
                                callback: function(){ document.location.reload(); }
                            }
                        }
                    });
                })
        });


        $('#twitter_step1').click(function () {
            $('#testTwitter-result').html('');
            $.get("twitter_step1", function (data) {window.open(data); })
                .done(function () { $('#testTwitter-result').html('<b>Step1:</b> Confirm Authorization'); });
        });

        $('#twitter_step2').click(function () {
            $('#testTwitter-result').html('');
            let twitter_key = $("#twitter_key").val();
            $.get("twitter_step2", {'key': twitter_key},
                function (data) { $('#testTwitter-result').html(data); });
        });

        $('#test_twitter').click(function () {
            $.get("test_twitter", {},
                function (data) {
                    bootbox.dialog({
                        title: 'Twitter Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_boxcar').click(function () {
            let token = $.trim($("#boxcar_token").val());
            $.get("test_boxcar", {'token': token},
                function (data) {
                    bootbox.dialog({
                        title: 'Boxcar Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_pushbullet').click(function () {
            let token = $.trim($("#pushbullet_token").val());
            let device = $.trim($("#pushbullet_deviceid").val());
            $.get("test_pushbullet", {'token': token, 'device': device},
                function (data) {
                    bootbox.dialog({
                        title: 'Pushbullet Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
            });

        $('#test_pushover').click(function () {
            let token = $.trim($("#pushover_apitoken").val());
            let keys = $.trim($("#pushover_keys").val());
            let priority = $.trim($("#pushover_priority").val());
            let device = $.trim($("#pushover_device").val());
            $.get("test_pushover", {'apitoken': token, 'keys': keys, 'priority': priority, 'device': device},
                function (data) {
                    bootbox.dialog({
                        title: 'Pushover Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_prowl').click(function () {
            let apikey = $.trim($("#prowl_apikey").val());
            let priority = $.trim($("#prowl_priority").val());
            $.get("test_prowl", {'apikey': apikey, 'priority': priority},
                function (data) {
                    bootbox.dialog({
                        title: 'Prowl Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_growl').click(function () {
            let host = $.trim($("#growl_host").val());
            let password = $.trim($("#growl_password").val());
            $.get("test_growl", {'host': host, 'password': password},
                function (data) {
                    bootbox.dialog({
                        title: 'Growl Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_telegram').click(function () {
            let token = $.trim($("#telegram_token").val());
            let userid = $.trim($("#telegram_userid").val());
            $.get("test_telegram", {'token': token, 'userid': userid},
                function (data) {
                    bootbox.dialog({
                        title: 'Telegram Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_slack').click(function () {
            let token = $.trim($("#slack_token").val());
            let url = $.trim($("#slack_url").val());
            $.get("test_slack", {'token': token, 'url': url},
                function (data) {
                    bootbox.dialog({
                        title: 'Slack Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_custom').click(function () {
            let script = $.trim($("#custom_script").val());
            $.get("test_custom", {'script': script},
                function (data) {
                    bootbox.dialog({
                        title: 'Custom Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_email').click(function () {
            let tls = ($("#email_tls").prop('checked') === true) ? 'True' : 'False';
            let ssl = ($("#email_ssl").prop('checked') === true) ? 'True' : 'False';
            let sendfile = ($("#email_sendfile_ondownload").prop('checked') === true) ? 'True' : 'False';
            let emailfrom = $.trim($("#email_from").val());
            let emailto = $.trim($("#email_to").val());
            let server = $.trim($("#email_smtp_server").val());
            let user = $.trim($("#email_smtp_user").val());
            let password = $.trim($("#email_smtp_password").val());
            let port = $.trim($("#email_smtp_port").val());
            $.get("test_email", {'tls': tls, 'ssl': ssl, 'emailfrom': emailfrom, 'emailto': emailto, 'server': server, 'user': user, 'password': password, 'port': port, 'sendfile': sendfile},
                function (data) {
                    bootbox.dialog({
                        title: 'Email Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $("#test_androidpn").click(function () {
            let androidpn_url = $.trim($("#androidpn_url").val());
            let androidpn_username = $.trim($("#androidpn_username").val());
            let androidpn_broadcast = ($("#androidpn_broadcast").prop('checked') === true) ? 'Y' : 'N';
            $.get("test_androidpn", {'url': androidpn_url, 'username': androidpn_username, 'broadcast': androidpn_broadcast},
                function (data) {
                    bootbox.dialog({
                        title: 'Android Notifier',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_calibredb').click(function () {
            let prg = $.trim($("#imp_calibredb").val());
            $.get("test_calibredb", { 'prg': prg},
                function (data) {
                    bootbox.dialog({
                        title: 'CalibreDB',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });
        $('#test_ebook_convert').click(function () {
            let prg = $.trim($("#ebook_convert").val());
            $.get("test_ebook_convert", { 'prg': prg},
                function (data) {
                    bootbox.dialog({
                        title: 'ebook-convert',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_ffmpeg').click(function () {
            let prg = $.trim($("#ffmpeg").val());
            $.get("test_ffmpeg", { 'prg': prg},
                function (data) {
                    bootbox.dialog({
                        title: 'FFMPEG',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#test_preprocessor').click(function () {
            let prg = $.trim($("#ext_preprocessor").val());
            $.get("test_preprocessor", { 'prg': prg},
                function (data) {
                    bootbox.dialog({
                        title: 'PreProcessor',
                        message: '<pre>'+data+'</pre>',
                        buttons: {
                            primary: {
                                label: "Close",
                                className: 'btn-primary'
                            }
                        }
                    });
                });
        });

        $('#http_look').change(function() {
            if ($(this).val() === 'bookstrap') {
                $('#bookstrap_options').removeClass("hidden");
            } else {
                $('#bookstrap_options').addClass("hidden");
            }
        });

       $('#checkforupdates').on('click', function() {
            eraseCookie("ignoreUpdate");
            $("#myAlert").removeClass('hidden');
            $.get('check_for_updates', function(data) {
                $("#myAlert").addClass('hidden');
                bootbox.dialog({
                    title: 'Check Version',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary',
                            callback: function(){ location.reload(); }
                        },
                    }
                });
            });
        });

       $('#generate_api').on('click', function() {
            $("#myAlert").removeClass('hidden');
            $.get('generate_api', function(data) {
                $("#myAlert").addClass('hidden');
                bootbox.dialog({
                    title: 'Generate API',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary',
                            callback: function(){ location.reload(); }
                        },
                    }
                });
            });
        });

       $('#generate_ro_api').on('click', function() {
            $("#myAlert").removeClass('hidden');
            $.get('generate_ro_api', function(data) {
                $("#myAlert").addClass('hidden');
                bootbox.dialog({
                    title: 'Generate Read-Only API',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary',
                            callback: function(){ location.reload(); }
                        },
                    }
                });
            });
        });

        // Refresh telemetry data when the page has loaded
        $('window').ready(function() {
            let send_config = $("#telemetry_send_config").prop("checked") ? 'True' : ''
            let send_usage = $("#telemetry_send_usage").prop("checked") ? 'True' : ''
            $.get('get_telemetry_data', {'send_config': send_config, 'send_usage': send_usage},
            function(data) {
                $("#telemetry_data").val(data)
            });
        });

        $('#telemetry_refresh').on('click', function() {
            let send_config = $("#telemetry_send_config").prop("checked") ? 'True' : ''
            let send_usage = $("#telemetry_send_usage").prop("checked") ? 'True' : ''
            $.get('get_telemetry_data', {'send_config': send_config, 'send_usage': send_usage},
            function(data) {
                $("#telemetry_data").val(data)
            });
        });

        $('#telemetry_reset').on('click', function() {
            let send_config = $("#telemetry_send_config").prop("checked") ? 'True' : ''
            let send_usage = $("#telemetry_send_usage").prop("checked") ? 'True' : ''
            $.get('reset_telemetry_usage_data', function() {});
            $.get('get_telemetry_data', {'send_config': send_config, 'send_usage': send_usage},
            function(data) {
                $("#telemetry_data").val(data)
            });
        });

        $('#test_telemetry_server').on('click', function() {
            let server = $.trim($("#telemetry_server").val());
            $.get('test_telemetry_server', {'server': server},
                function(data) {
                bootbox.dialog({
                    title: 'Telemetry server connection',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary'
                        }
                    }
                });
            });
        });

        $('#telemetry_submit').on('click', function() {
            let server = $.trim($("#telemetry_server").val());
            let send_config = $("#telemetry_send_config").prop("checked") ? 'True' : ''
            let send_usage = $("#telemetry_send_usage").prop("checked") ? 'True' : ''
            $.get('submit_telemetry_data', {'server': server, 'send_config': send_config, 'send_usage': send_usage},
                function(data) {
                bootbox.dialog({
                    title: 'Submitted telemetry data',
                    message: '<pre>'+data+'</pre>',
                    buttons: {
                        primary: {
                            label: "Close",
                            className: 'btn-primary',
                        },
                    }
                });
            });
        });

        $('#ol_api').on('click', function() {
            let status = $("#ol_api").prop("checked") ? 'True' : ''
            $.get('ol_api_changed', {'status': status},
            function(data) {
                location.reload();
            });
        });

        $('#dnb_api').on('click', function() {
            let status = $("#dnb_api").prop("checked") ? 'True' : ''
            $.get('dnb_api_changed', {'status': status},
            function(data) {
                location.reload();
            });
        });

        $('#hc_api').on('change', function() {
            let status = $("#hc_api").prop("checked") ? 'True' : ''
            $.get('hc_api_changed', {'status': status},
            function(data) {
                location.reload();
            });
        });

        $('#gr_api').on('change', function() {
            let apikey = $.trim($("#gr_api").val());
            $.get('gr_api_changed', {'gr_api': apikey},
            function(data) {
                location.reload();
            });
        });

        $('#gb_api').on('change', function() {
            let apikey = $.trim($("#gb_api").val());
            $.get('gb_api_changed', {'gb_api': apikey},
            function(data) {
                location.reload();
            });
        });

        $("form #bookstrap_theme").on("change", function() {
            $("head #theme").attr("href", "https://maxcdn.bootstrapcdn.com/bootswatch/3.3.7/" + $(this).val() + "/bootstrap.min.css");
        });
    }
</script>
