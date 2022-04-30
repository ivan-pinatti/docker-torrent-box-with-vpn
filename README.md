# Docker Torrent Box

[![license](https://img.shields.io/github/license/ivan-pinatti/docker-torrent-box?style=plastic)](https://github.com/ivan-pinatti/docker-torrent-box/blob/master/LICENSE)

The code below is intented to be used as a Torrent Box through a VPN connection.


## Apps Included

|    App Name   |                    Docker Image                    |                     Function                     |
|:-------------:|:--------------------------------------------------:|:------------------------------------------------:|
|    Calibre    | https://hub.docker.com/r/linuxserver/calibre       |              eBooks Library Manager              |
|  Calibre-web  | https://hub.docker.com/r/linuxserver/calibre-web   |              eBooks Library Manager              |
|    Jackett    | https://hub.docker.com/r/linuxserver/jackett       |                Query Proxy Server                |
|  Flaresolverr | https://hub.docker.com/r/flaresolverr/flaresolverr |        Bypass to Cloudflare and DDoS-GUARD       |
| LazyLibrarian | https://hub.docker.com/r/linuxserver/lazylibrarian |               Books Tracker/Manager              |
|     Lidarr    | https://hub.docker.com/r/linuxserver/lidarr        |               Music Tracker/Manager              |
|     Mylar     | https://hub.docker.com/r/linuxserver/mylar3        |              Comics Tracker/Manager              |
|     NZBGet    | https://hub.docker.com/r/linuxserver/nzbget        |                 Usenet Downloader                |
|   NZBHydra2   | https://hub.docker.com/r/linuxserver/nzbhydra2     |          Meta Searcher for NZB indexers          |
|      Plex     | https://hub.docker.com/r/linuxserver/plex          | Movie/TV Shows/Music Library Manager and Player  |
|   ProtonVPN   | https://github.com/tprasadtp/protonvpn-docker      |                    VPN Gateway                   |
|  qBittorrent  | https://hub.docker.com/r/linuxserver/qbittorrent   |                Torrent Downloader                |
|     Radarr    | https://hub.docker.com/r/linuxserver/radarr        |              Movies Tracker/Manager              |
|    Readarr    | https://hub.docker.com/r/linuxserver/readarr       |              eBooks Tracker/Manager              |
|     Sonarr    | https://hub.docker.com/r/linuxserver/sonarr        |             TV Shows Tracker/Manager             |

---

# How to run

## 1 - Create dotenv (.env) file
Copy from the example and generate a new .env file.
```shell
cp .env.example .env
```

## 2 - Check your parameters
It is necessary to set a few parameters to match your environment.
Check your user id and gid. To get this info, go to your shell and run:
```shell
id
```

The result should be something like;
```shell
uid=1000(my_user) gid=1000(my_user) groups=1000(my_user)
```

After that, check your timezone. For that, run:
```shell
cat /etc/timezone
```

The result should be something like;
```shell
America/Toronto
```

Save these values for later reference.

## 3 - Edit dotenv (.env) file
Edit the newly created .env file and change the `UID, GID, and TIMEZONE` parameters to the values you gathered from steps 1 and 2.

## 4 - Configure the ProtonVPN parameters
Now, edit the file `protonvpn/.env` with the values from the ProtonVPN page. If you don't know how to get them, please visit [https://protonvpn.com/support/vpn-login](https://protonvpn.com/support/vpn-login).

With the values from the page, change the `PROTONVPN_USERNAME, PROTONVPN_PASSWORD, and PROTONVPN_EXCLUDE_CIDRS`.

**IMPORTANT:** The value of `PROTONVPN_EXCLUDE_CIDRS` it is your LAN IP range, for example; 192.168.0.0/24.

## 5 - Run the containers
Now that everything is set, please run the containers by using the command below;
```shell
docker-compose up -d
```

---

If you are using the code consider buying me a coffee or a beer :)

<a href="https://www.buymeacoffee.com/ivan.pinatti" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>
