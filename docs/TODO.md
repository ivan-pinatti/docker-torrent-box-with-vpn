### Todo

- [ ] Enhance the library update process
- [ ] Research Dependabot/Renovate for Docker image versions
- [ ] Lidarr is not configured for Indexers due to a restriction to add it
- [ ] Mylar is not working to add HTTPS qBitorrent and Nzbget
- [ ] Sonarr HTTPS
- [ ] Lazylibrarian not working with qBittorrent on HTTPS
- [ ] Fix pre-commit docker-compose hook
- [ ] Fix python version w/ GHA

### In Progress

### Done ✓

2.0.1

- [x] Added backup entries to .gitignore
- [x] Added certs to the backup
- [x] Rearranging Github files
- [x] Automate semantic versioning
- [x] Automate release generation
- [x] Adding devContainers to the repository to facilitate development
- [x] Plex network changed to `host` for better performance
- [x] Added support for NordVPN (untested)

  2.0.0

- [x] Augment the stack to use a reverse proxy w/ https
- [x] Add Lazylibrarian to Prowlarr
- [x] Added Prowlarr to the stack
- [x] Config HTTPS available services
- [x] Create the script to generate self-certificate
- [x] Add Stale bot
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
