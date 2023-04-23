# Torrent, Usenet, NZB, VPN (ProtonVPN) box by Docker Compose containers

![GitHub issues](https://img.shields.io/github/issues-raw/ivan-pinatti/docker-torrent-box-with-vpn?logo=Github&style=for-the-badge)
![GitHub Sponsors](https://img.shields.io/github/sponsors/ivan-pinatti?logo=Github&style=for-the-badge)

The code on this repository is intended to be used to share media content with various networks such as Torrent and Usenet while protecting your privacy through a VPN (ProtonVPN). The main idea is to provide access where Internet censors and content restriction apply. I totally discourage using this code for any piracy reasons.

The stack can be run in any Linux box.\
Besides Plex transcoding, all other apps and functions are super light and a basic Raspberry Pi is able to handle the load.

All the apps are pre-configured and integrated. Therefore, with a few clicks you can start adding Indexers to the configurations and tinkering to your liking.

**IMPORTANT:** I strongly recommend rotating all the API keys and changing all the passwords.

---

# Requisites

|    **App**     | **Version** |                                       **Site**                                        |
| :------------: | :---------: | :-----------------------------------------------------------------------------------: |
| Docker-Compose |    >2.4     |                        https://docs.docker.com/compose/install                        |
|  Linux Kernel  |    >5.6     | More info at: https://github.com/tprasadtp/protonvpn-docker#linux-kernel-requirements |
|    Makefile    |    >4.x     |                                           -                                           |

---

# Apps Included

| **App Name**  |                  **Docker Image**                  |                  **Function**                   |
| :-----------: | :------------------------------------------------: | :---------------------------------------------: |
|    Calibre    |    https://hub.docker.com/r/linuxserver/calibre    |             eBooks Library Manager              |
|  Calibre-web  |  https://hub.docker.com/r/linuxserver/calibre-web  |             eBooks Library Manager              |
|    Jackett    |    https://hub.docker.com/r/linuxserver/jackett    |               Query Proxy Server                |
| Flaresolverr  | https://hub.docker.com/r/flaresolverr/flaresolverr |       Bypass to Cloudflare and DDoS-GUARD       |
| LazyLibrarian | https://hub.docker.com/r/linuxserver/lazylibrarian |              Books Tracker/Manager              |
|    Lidarr     |    https://hub.docker.com/r/linuxserver/lidarr     |              Music Tracker/Manager              |
|     Mylar     |    https://hub.docker.com/r/linuxserver/mylar3     |             Comics Tracker/Manager              |
|    NZBGet     |    https://hub.docker.com/r/linuxserver/nzbget     |                Usenet Downloader                |
|   NZBHydra2   |   https://hub.docker.com/r/linuxserver/nzbhydra2   |         Meta Searcher for NZB indexers          |
|     Plex      |     https://hub.docker.com/r/linuxserver/plex      | Movie/TV Shows/Music Library Manager and Player |
|   ProtonVPN   |   https://github.com/tprasadtp/protonvpn-docker    |                   VPN Gateway                   |
|  qBittorrent  |  https://hub.docker.com/r/linuxserver/qbittorrent  |               Torrent Downloader                |
|    Radarr     |    https://hub.docker.com/r/linuxserver/radarr     |             Movies Tracker/Manager              |
|    Readarr    |    https://hub.docker.com/r/linuxserver/readarr    |             eBooks Tracker/Manager              |
|    Sonarr     |    https://hub.docker.com/r/linuxserver/sonarr     |            TV Shows Tracker/Manager             |

---

# Table of Contents

- [Torrent, Usenet, NZB, VPN (ProtonVPN) box by Docker Compose containers](#torrent-usenet-nzb-vpn-protonvpn-box-by-docker-compose-containers)
- [Requisites](#requisites)
- [Apps Included](#apps-included)
- [Table of Contents](#table-of-contents)
- [Usage](#usage)
  - [1. Check your parameters](#1-check-your-parameters)
  - [2.Create dotenv (.env) file](#2create-dotenv-env-file)
  - [3. Edit dotenv (.env) file](#3-edit-dotenv-env-file)
    - [3.1. Edit ProtonVPN dotenv (.env) file](#31-edit-protonvpn-dotenv-env-file)
  - [4. Generate the certificate](#4-generate-the-certificate)
    - [4.1. Use your own certificate](#41-use-your-own-certificate)
  - [5. Enable / Disable Apps](#5-enable--disable-apps)
  - [6. Run the containers](#6-run-the-containers)
  - [7. Rotate your keys](#7-rotate-your-keys)
  - [8. Shutting it down](#8-shutting-it-down)
  - [9. Backup](#9-backup)
- [Folders](#folders)
- [App Links](#app-links)
- [Indexers](#indexers)
  - [Torrent](#torrent)
  - [Usenet](#usenet)
- [Downloaders](#downloaders)
  - [Torrent](#torrent-1)
  - [Usenet](#usenet-1)
- [Library Managers](#library-managers)
  - [Movies / Series / Music](#movies--series--music)
  - [AudioBooks / eBooks / Comics](#audiobooks--ebooks--comics)
- [Bandwith Control](#bandwith-control)
  - [Revert to original state](#revert-to-original-state)
  - [Clean up everything (including media folder)](#clean-up-everything-including-media-folder)
- [License](#license)
- [Contribute / Donate](#contribute--donate)
---

# Usage

## 1. Check your parameters

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

## 2.Create dotenv (.env) file

Copy from the example and generate a new .env file.

```shell
cp .env.example .env
```

## 3. Edit dotenv (.env) file

Edit the newly created .env file and change the `UID, GID, and TIMEZONE` parameters to the values you gathered from steps 1 and 2.

In addition, set the `DOMAIN` variable for the certificate generation and the reverse proxy configuration.

For now the only available VPN provider configured is ProtonVPN, therefore leave the `VPN_PROVIDER` as default.

It will look something like this;
```
# System Parameters
UID=1000
GID=1000
TIMEZONE=America/Toronto
UMASK=022
DOMAIN=media-library.nas.local
VPN_PROVIDER=protonvpn
```
### 3.1. Edit ProtonVPN dotenv (.env) file

Now, edit the file `configs/protonvpn/.env` with the values from the ProtonVPN page.

- Log in to ProtonVPN and go to Downloads → WireGuard configuration.
- Enter a name for the key, and select features to enable like NetShield and VPN Accelerator & click create.
- Generated config might look something like below;

```[Interface]
# Key for <name>
# VPN Accelerator = on
PrivateKey = KLjfIMiuxPskM4+DaSUDmL2uSIYKJ9Wap+CHvs0Lfkw=
Address = 10.2.0.2/32
DNS = 10.2.0.1

[Peer]
# NL-FREE#128
PublicKey = jbTC1lYeHxiz1LNSJHQMKDTq6sHgcWxkBwXvt7GWo1E=
AllowedIPs = 0.0.0.0/0
Endpoint = 91.229.23.180:51820
```

- Only thing needed from the above config is PrivateKey.
- See https://protonvpn.com/support/wireguard-configurations/ for more info.

With the values from the page, change the `WIREGUARD_PRIVATE_KEY` and `PROTONVPN_SERVER`.

**IMPORTANT:** To use a server that is best for you, please check the details in the ProtonVPN Docker page; https://github.com/tprasadtp/protonvpn-docker#protonvpn_server

After that your `configs/protonvpn/.env` file should look like this;

```
WIREGUARD_PRIVATE_KEY=KLjfIMiuxPskM4+DaSUDmL2uSIYKJ9Wap+CHvs0Lfkw=
PROTONVPN_SERVER=nl-free-127.protonvpn.net
KILL_SWITCH=true
```

## 4. Generate the certificate

At this moment the stack only supports self-signed certificates.

Go back to the `.env` file and look for the section about the certificate if you want to change any parameter.
An example is like;

```
# Certificate details
CERT_COUNTRY=CS
CERT_STATE=Classified
CERT_CITY=Classified
CERT_ORGANIZATION=Classified
CERT_OU=Classified
CERT_FQDN=${DOMAIN} # it will use the previously declared DOMAIN variable
```

After you have configured the parameters in the `.env` file, you can generate a certificate by running the command;

```
make generate_certificate
```

This will create the `server.key`, `server.crt`, and `server.pfx` in the `/certs/` folder.

### 4.1. Use your own certificate

If you have your own certificate, just copy them to the `/certs` folder using the exact names.

Remember, the `server.key`, `server.crt`, and `server.pfx` have to match the `uid` and `gid`, and the permissions have to be `644` for the `.crt` and `600` for the `.key` and `.pfx`.

## 5. Enable / Disable Apps

In the same `.env` file, edit the Docker container profile to enabled/disabled for the apps in the stack.

The only **REQUIRED** app is the `VPN_PROVIDER` as the stack is tightly coupled to it.

It will look like this;
```
# Default Apps' Profiles (enabled/disabled)
CALIBRE_PROFILE=disabled
CALIBREWEB_PROFILE=disabled
FLARESOLVERR_PROFILE=enabled
JACKETT_PROFILE=disabled
LAZYLIBRARIAN_PROFILE=disabled
LIDARR_PROFILE=disabled
MYLAR_PROFILE=disabled
NGINX_PROFILE=enabled
NZBGET_PROFILE=enabled
NZBHYDRA2_PROFILE=enabled
PLEX_PROFILE=enabled
PROTONVPN_PROFILE=enabled
QBITTORRENT_PROFILE=enabled
RADARR_PROFILE=enabled
READARR_PROFILE=disabled
SONARR_PROFILE=enabled

# NOT Default Apps' Profiles (enabled/disabled)
PROWLARR_PROFILE=enabled
```

## 6. Run the containers

Now that everything is set, please run the containers by using the command below;

```shell
docker-compose --profile enabled up --detach
```

**OR**

```shell
make start
```

## 7. Rotate your keys

All the services are pre-configured, therefore they already have API keys set.

It is **strongly recommended rotating all of them** for the sake of security.

## 8. Shutting it down

Now that everything is working, if you need to bring it down to change parameters and make adjustments, please run the command below;

```shell
docker-compose --profile enabled stop
```

**OR**

```shell
make stop
```

## 9. Backup

Now that everything is **fully working**. Make sure you create a backup of your configurations and changes, in order to perform the backup operation, please run;

```shell
make backup
```

This command will generate a backup of all the config folders.

---
# Folders

The media type will be stored into the folders below;

| **Media**  |    **Folder**    |
| :--------: | :--------------: |
| AudioBooks | media/AudioBooks |
|   Comics   |   media/Comics   |
|   eBooks   |   media/eBooks   |
|   Movies   |   media/Movies   |
|   Music    |   media/Music    |
|   Series   |   media/Series   |

---

# App Links

To access the services, please use the table below;

|    **App**    |        **Link**         |   **User**    | **Password**  |
| :-----------: | :---------------------: | :-----------: | :-----------: |
|    Calibre    | http://localhost:8080/  |      abc      |    calibre    |
|  Calibre-Web  | http://localhost:8083/  |    calibre    |    calibre    |
| FlareSolverr  | http://localhost:8191/  |       -       |       -       |
|    Jackett    | http://localhost:9117/  |       -       |    jackett    |
| LazyLibrarian | http://localhost:5299/  | lazylibrarian | lazylibrarian |
|    Lidarr     | http://localhost:8686/  |    lidarr     |    lidarr     |
|     Mylar     | http://localhost:8090/  |     mylar     |     mylar     |
|    Nzbget     | http://localhost:6789/  |    nzbget     |    nzbget     |
|   NzbHydra2   | http://localhost:5076/  |   nzbhydra2   |   nzbhydra2   |
|     Plex      | http://localhost:32400/ |       -       |       -       |
|  qBitTorrent  | http://localhost:8082/  |  qbittorrent  |  qbittorrent  |
|    Radarr     | http://localhost:7878/  |    radarr     |    radarr     |
|    Readarr    | http://localhost:8787/  |    readarr    |    readarr    |
|    Sonarr     | http://localhost:8989/  |    sonarr     |    sonarr     |

---

# Indexers

## Torrent

LazyLibrarian ---> NzbHydra2 ---> Jackett ---> Flaresolverr\
Lidarr ---> NzbHydra2 ---> Jackett ---> Flaresolverr\
Mylar ---> NzbHydra2 ---> Jackett ---> Flaresolverr\
Radarr ---> NzbHydra2 ---> Jackett ---> Flaresolverr\
Readarr ---> NzbHydra2 ---> Jackett ---> Flaresolverr\
Sonarr ---> NzbHydra2 ---> Jackett ---> Flaresolverr

## Usenet

LazyLibrarian ---> NzbHydra2\
Lidarr ---> NzbHydra2\
Mylar ---> NzbHydra2\
Radarr ---> NzbHydra2\
Readarr ---> NzbHydra2\
Sonarr ---> NzbHydra2

---

# Downloaders

## Torrent

LazyLibrarian ---> qBitTorrent\
Lidarr ---> qBitTorrent\
Mylar ---> qBitTorrent\
Radarr ---> qBitTorrent\
Readarr ---> qBitTorrent\
Sonarr ---> qBitTorrent

## Usenet

LazyLibrarian ---> NzbGet\
Lidarr ---> NzbGet\
Mylar ---> NzbGet\
Radarr ---> NzbGet\
Readarr ---> NzbGet\
Sonarr ---> NzbGet

---

# Library Managers

## Movies / Series / Music

Lidarr ---> Plex Media Server\
Radarr ---> Plex Media Server\
Sonarr ---> Plex Media Server

## AudioBooks / eBooks / Comics

LazyLibrarian ---> Calibre\
Mylar ---> Calibre\
Readarr ---> Calibre

---

# Bandwith Control

By default, both downloaders, qBitTorrent and NzbGet, are configured to limit from 8AM to 11:59PM to;

- **Download Rate** - 1 Gbps
- **Upload Rate** - 30 Mbps (only applicable to qBitTorrent)

Outside of these hours, no speed control applied.\
If desired, it is possible to change or disable the settings in these app's configs.

---

## Revert to original state

If you need to revert to the original code and configs, simply run;

```shell
make clean
```

---

## Clean up everything (including media folder)

**IMPORTANT:** This will **ERASE** every file on your media folder!

```shell
make clean_all
```

---

# License

[![license](https://img.shields.io/github/license/ivan-pinatti/docker-torrent-box?style=plastic)](https://github.com/ivan-pinatti/docker-torrent-box/blob/master/LICENSE)

See [LICENSE](LICENSE) for full details.

> `THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.`

---

# Contribute / Donate

If you are using the code, entirelly or partially, forking the project, or getting inspired by it, consider becoming a sponsor, buying me a coffee, or maybe a beer, I would really appreciate it :smiley:

[![](https://img.shields.io/static/v1?label=Sponsor&message=%E2%9D%A4&logo=GitHub&color=%23fe8e86)](https://github.com/sponsors/ivan-pinatti)

<a href="https://www.buymeacoffee.com/ivan.pinatti" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>
