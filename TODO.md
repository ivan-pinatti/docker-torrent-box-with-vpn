### Todo

- [ ] Enhance the library update process
- [ ] Automate release generation
- [ ] Augment the stack to use a reverse proxy w/ https
- [ ] Add Stale bot for issues
- [ ] Add Patreon and Paypal buttons - https://github.com/ivan-pinatti/docker-torrent-box-with-vpn#contribute--donate

### In Progress

- [ ] Research Dependabot for Docker image versions
- [ ] Create the script to generate self-certificate
- [ ] Config HTTPS to all services

### Done ✓

- [x] Pre-commit hooks - Linting, security, etc...
- [x] Added restart to Makefile
- [x] Added ports 6881 and 6881/udp to qBittorrent container
- [x] Made the `docker-compose` file more compact
- [x] Remove the `depends_on` clause from the containers to make it more customizable
- [x] Add the option to select to enable/disable apps
- [x] Fix the text for the `make clean`
- [x] Flaresolverr typo (missing an R)
- [x] Flaresolverr doesn't have a captcha solver - investigate
- [x] Create my first TODO.md
- [x] Add more tasks to Makefile
