# Torrent, Usenet, NZB, VPN (ProtonVPN) box by Docker Compose containers

The code on this repository is intended to be used to share media content with various networks such as Torrent and Usenet while protecting your privacy through a VPN (ProtonVPN). The main idea is to provide access where Internet censors and content restriction apply. I totally discourage using this code for any piracy reasons.

The stack can be run in any Linux box.\
Besides Plex transcoding, all other apps and functions are super light and a basic Raspberry Pi is able to handle the load.

All the apps are pre-configured and integrated. Therefore, with a few clicks you can start adding Indexers to the configurations and tinkering to your liking.

**IMPORTANT:** I strongly recommend rotating all the API keys and changing all the passwords.


[![license](https://img.shields.io/github/license/ivan-pinatti/docker-torrent-box?style=plastic)](https://github.com/ivan-pinatti/docker-torrent-box/blob/master/LICENSE)

---

## Requisites

|       **App**      |  **Version**  |                     **Site**                   |
|:------------------:|:-------------:|:----------------------------------------------:|
|   Docker-Compose   |      >2.4     |      https://docs.docker.com/compose/install   |

---

## Apps Included

|    **App Name**   |                    **Docker Image**                    |                     **Function**                     |
|:-----------------:|:------------------------------------------------------:|:----------------------------------------------------:|
|       Calibre     |   https://hub.docker.com/r/linuxserver/calibre         |               eBooks Library Manager                 |
|     Calibre-web   |   https://hub.docker.com/r/linuxserver/calibre-web     |               eBooks Library Manager                 |
|       Jackett     |   https://hub.docker.com/r/linuxserver/jackett         |                 Query Proxy Server                   |
|     Flaresolverr  |   https://hub.docker.com/r/flaresolverr/flaresolverr   |         Bypass to Cloudflare and DDoS-GUARD          |
|    LazyLibrarian  |   https://hub.docker.com/r/linuxserver/lazylibrarian   |                Books Tracker/Manager                 |
|        Lidarr     |   https://hub.docker.com/r/linuxserver/lidarr          |                Music Tracker/Manager                 |
|        Mylar      |   https://hub.docker.com/r/linuxserver/mylar3          |               Comics Tracker/Manager                 |
|        NZBGet     |   https://hub.docker.com/r/linuxserver/nzbget          |                  Usenet Downloader                   |
|      NZBHydra2    |   https://hub.docker.com/r/linuxserver/nzbhydra2       |           Meta Searcher for NZB indexers             |
|         Plex      |   https://hub.docker.com/r/linuxserver/plex            |  Movie/TV Shows/Music Library Manager and Player     |
|      ProtonVPN    |   https://github.com/tprasadtp/protonvpn-docker        |                     VPN Gateway                      |
|     qBittorrent   |   https://hub.docker.com/r/linuxserver/qbittorrent     |                 Torrent Downloader                   |
|        Radarr     |   https://hub.docker.com/r/linuxserver/radarr          |               Movies Tracker/Manager                 |
|       Readarr     |   https://hub.docker.com/r/linuxserver/readarr         |               eBooks Tracker/Manager                 |
|        Sonarr     |   https://hub.docker.com/r/linuxserver/sonarr          |              TV Shows Tracker/Manager                |

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
Now, edit the file `configs/protonvpn/.env` with the values from the ProtonVPN page. If you don't know how to get them, please visit [https://protonvpn.com/support/vpn-login](https://protonvpn.com/support/vpn-login).

With the values from the page, change the `PROTONVPN_USERNAME, PROTONVPN_PASSWORD, and PROTONVPN_EXCLUDE_CIDRS`.

**IMPORTANT:** The value of `PROTONVPN_EXCLUDE_CIDRS` it is your LAN IP range, for example; 192.168.0.0/24.

## 5 - Run the containers
Now that everything is set, please run the containers by using the command below;
```shell
docker-compose up -d
```

---
## Folders

The media type will be stored into the folders below;

|    **Media**    	|                 **Folder**                |
|:-------------:	|:-----------------------------------------:|
|    AudioBooks    	|               media/AudioBooks          	|
|     Comics   	    |               media/Comics              	|
|     eBooks   	    |               media/eBooks             	|
|     Movies    	|               media/Movies          	    |
|     Music    	    |               media/Music       	        |
|     Series    	|               media/Series          	    |

---
## App Links

To access the services, please use the table below;

|    **App**    	|                 **Link**                 	|    **User**     |  **Password** 	|
|:-------------:	|:----------------------------------------:	|:-------------:  |:---------------:|
|    Calibre    	|          http://localhost:8080/          	|      abc        |    calibre    	|
|  Calibre-Web  	|          http://localhost:8083/          	|    calibre      |    calibre    	|
|  FlareSolverr 	|          http://localhost:8191/          	|       -         |       -       	|
|    Jackett    	|          http://localhost:9117/          	|    jackett      |    jackett    	|
| LazyLibrarian 	|          http://localhost:5299/          	| lazylibrarian   | lazylibrarian 	|
|     Lidarr    	|          http://localhost:8686/          	|     lidarr      |     lidarr    	|
|     Mylar     	|          http://localhost:8090/          	|     mylar       |     mylar     	|
|     Nzbget    	|          http://localhost:6789/          	|     nzbget      |     nzbget    	|
|   NzbHydra2   	|          http://localhost:5076/          	|   nzbhydra2     |   nzbhydra2   	|
|      Plex     	| http://localhost:32400/web/index.html#!/ 	|       -         |       -       	|
|  qBitTorrent  	|          http://localhost:8082/          	|  qbittorrent    |  qbittorrent  	|
|     Radarr    	|          http://localhost:7878/          	|     radarr      |     radarr    	|
|    Readarr    	|          http://localhost:8787/          	|    readarr      |    readarr    	|
|     Sonarr    	|          http://localhost:8989/          	|     sonarr      |     sonarr    	|

---
# Indexers
## Torrent
LazyLibrarian  --->  NzbHydra2  --->  Jackett  --->  Flaresolverr\
Lidarr         --->  NzbHydra2  --->  Jackett  --->  Flaresolverr\
Mylar          --->  NzbHydra2  --->  Jackett  --->  Flaresolverr\
Radarr         --->  NzbHydra2  --->  Jackett  --->  Flaresolverr\
Readarr        --->  NzbHydra2  --->  Jackett  --->  Flaresolverr\
Sonarr         --->  NzbHydra2  --->  Jackett  --->  Flaresolverr

## Usenet
LazyLibrarian  --->  NzbHydra2\
Lidarr         --->  NzbHydra2\
Mylar          --->  NzbHydra2\
Radarr         --->  NzbHydra2\
Readarr        --->  NzbHydra2\
Sonarr         --->  NzbHydra2

---
# Downloaders
## Torrent
LazyLibrarian  --->  qBitTorrent\
Lidarr         --->  qBitTorrent\
Mylar          --->  qBitTorrent\
Radarr         --->  qBitTorrent\
Readarr        --->  qBitTorrent\
Sonarr         --->  qBitTorrent

## Usenet
LazyLibrarian  --->  NzbGet\
Lidarr         --->  NzbGet\
Mylar          --->  NzbGet\
Radarr         --->  NzbGet\
Readarr        --->  NzbGet\
Sonarr         --->  NzbGet

---
# Library Managers
## Movies / Series / Music
Lidarr         --->  Plex Media Server\
Radarr         --->  Plex Media Server\
Sonarr         --->  Plex Media Server

## AudioBooks / eBooks / Comics
LazyLibrarian  --->  Calibre\
Mylar          --->  Calibre\
Readarr        --->  Calibre

---
# Bandwith Control
By default, both downloaders, qBitTorrent and NzbGet, are configured to limit from 8AM to 11:59PM to;

- **Download Rate** - 1 Gbps
- **Upload Rate**   - 30 Mbps (only applicable to qBitTorrent)

Outside of these hours, no speed control applied.\
If desired, it is possible to change or disable the settings in these app's configs.

---
## Clean up and revert to original state

If you need to revert to the original code and also want to delete any files inside the `shared` and `media` folders, simply run;

**IMPORTANT:** This will **ERASE** every file on your media folder!

```shell
make clean
```

---
# Contribute / Donate
If you are using the code, entirelly or partially, forking the project, or getting inspired by it, consider buying me a coffee or maybe a beer, I would really appreciate it :smiley:

<a href="https://www.buymeacoffee.com/ivan.pinatti" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

