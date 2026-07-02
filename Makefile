include .env certs/cert.conf

JELLYFIN_BASE_URL ?= /jellyfin
JELLYFIN_KNOWN_PROXY ?= $(NGINX_MEDIA_IP)

# CONTAINER_RUNTIME can be set in .env to 'podman' or 'docker'.
# If not set, auto-detect: Podman takes priority when available.
CONTAINER_RUNTIME ?= $(shell command -v podman >/dev/null 2>&1 && echo podman || echo docker)

ifeq ($(CONTAINER_RUNTIME),podman)
	RUNTIME := podman
	COMPOSE  := $(shell command -v podman-compose >/dev/null 2>&1 && echo podman-compose || echo "podman compose")
else
	RUNTIME := docker
	COMPOSE  := docker compose
endif

comma := ,
empty :=
space := $(empty) $(empty)

VPN_ON ?=
VPN_ON_LIST := $(strip $(subst $(comma),$(space),$(VPN_ON)))
VPN_ROUTE_SERVICES := bazarr flaresolverr lazylibrarian lidarr mylar prowlarr radarr readarr recyclarr sonarr whisparr
VPN_ROUTE_FILES := $(if $(filter servarr,$(VPN_ON_LIST)),docker-compose.routes/servarr-vpn.yml,$(foreach service,$(VPN_ROUTE_SERVICES),$(if $(filter $(service),$(VPN_ON_LIST)),docker-compose.routes/$(service)-vpn.yml)))
ROUTE_FILES ?= $(VPN_ROUTE_FILES)
COMPOSE_FILES := --file docker-compose.yml $(foreach route_file,$(ROUTE_FILES),--file $(route_file))
COMPOSE_PROJECT_NAME ?= $(notdir $(CURDIR))
PODMAN_DOWN_TIMEOUT ?= 60

.PHONY: backup backup-configs backup-full bootstrap clean clean_all check_requirements \
	configure_jellyfin_network \
	detect_secrets_create_baseline down generate_certificate \
	disk_status permissions_check permissions_repair permissions_smoke permissions_host_smoke prune_cache rotate_nginx_logs \
	install_requirements pull_docker_images pre_commit \
	restore-configs restore-full \
	restart sanity_fast sanity_full start start_library start_observability \
	stop stop_all update_containers update_images test test_prerequisites

BACKUP_DIR ?= backup
BACKUP_TIMESTAMP ?= $(shell date +%Y-%m-%d-%H%M%S)
CONFIG_BACKUP_ARCHIVE := $(BACKUP_DIR)/configs-$(BACKUP_TIMESTAMP).tar.gz
FULL_BACKUP_ARCHIVE := $(BACKUP_DIR)/full-$(BACKUP_TIMESTAMP).tar.gz
RESTORE_SAFETY_ARCHIVE := $(BACKUP_DIR)/pre-restore-$(BACKUP_TIMESTAMP).tar.gz

COMMON_BACKUP_EXCLUDES := \
	--exclude=.git \
	--exclude=.codex \
	--exclude=.pytest_cache \
	--exclude=.ruff_cache \
	--exclude='*.log' \
	--exclude='*.log.*' \
	--exclude='*.pid' \
	--exclude=cache \
	--exclude=data \
	--exclude=logs \
	--exclude=media \
	--exclude=megalinter-reports \
	--exclude=node_modules \
	--exclude=storage \
	--exclude=tests \
	--exclude='configs/*/config/.aspnet' \
	--exclude='configs/*/config/asp' \
	--exclude='configs/*/config/logs' \
	--exclude='configs/*/config/*/logs'

CONFIG_BACKUP_EXCLUDES := $(COMMON_BACKUP_EXCLUDES) \
	--exclude='*.db-shm' \
	--exclude='*.db-wal' \
	--exclude='*.json.bak' \
	--exclude='*.sqlite-shm' \
	--exclude='*.sqlite-wal' \
	--exclude='configs/*/config.bak' \
	--exclude='configs/*/config.v*.bak' \
	--exclude='configs/*/config/Backups' \
	--exclude='configs/*/config/MediaCover' \
	--exclude='configs/*/config/Sentry' \
	--exclude='configs/*/config/logs.db' \
	--exclude='configs/jellyfin/cache' \
	--exclude='configs/jellyfin/config/cache' \
	--exclude='configs/jellyfin/config/metadata' \
	--exclude='configs/recyclarr/config/resources/*/git'

all: generate_certificate update_images start

bootstrap:
	@echo "Remapping directory ownership into the container user namespace..."
	@echo "  (rootless Podman: host uid maps to uid=0 inside containers;"
	@echo "   app processes run as service-specific non-root UIDs)"
	@mkdir -p \
		configs/audiobookshelf/metadata/backups \
		data/media \
		data/media/calibre-library \
		data/recycle \
		data/torrents/blackhole \
		data/torrents \
		data/usenet/blackhole \
		storage/loki/data \
		storage/prometheus/data \
		storage/grafana/data
	@touch data/torrents/blackhole/.gitkeep data/usenet/blackhole/.gitkeep
	@./scripts/permissions.py repair --runtime $(RUNTIME) --recursive
	@$(MAKE) --no-print-directory configure_jellyfin_network
	@echo "Bootstrap complete. You can now run: make start"

backup: backup-configs

backup-configs:
	@echo "Creating lean config backup at $(CONFIG_BACKUP_ARCHIVE)..."
	@echo "For a FULL backup, run: make backup-full"
	@mkdir -p "$(BACKUP_DIR)"
	@tar --create --gzip --file "$(CONFIG_BACKUP_ARCHIVE)" \
		$(CONFIG_BACKUP_EXCLUDES) \
		.env certs configs
	@echo ".OK!"

backup-full:
	@echo "Creating full config backup at $(FULL_BACKUP_ARCHIVE)..."
	@mkdir -p "$(BACKUP_DIR)"
	@tar --create --gzip --file "$(FULL_BACKUP_ARCHIVE)" \
		$(COMMON_BACKUP_EXCLUDES) \
		.env certs configs
	@echo ".OK!"

restore-configs:
	@if [ -z "$(BACKUP)" ]; then echo "ERROR: BACKUP=/path/to/archive.tar.gz is required"; exit 1; fi
	@if [ ! -f "$(BACKUP)" ]; then echo "ERROR: backup archive not found: $(BACKUP)"; exit 1; fi
	@echo "Creating pre-restore safety backup at $(RESTORE_SAFETY_ARCHIVE)..."
	@mkdir -p "$(BACKUP_DIR)"
	@tar --create --gzip --file "$(RESTORE_SAFETY_ARCHIVE)" .env certs configs
	@echo "Restoring $(BACKUP)..."
	@rm -rf .env certs configs
	@tar --extract --gzip --file "$(BACKUP)" --directory .
	@echo ".OK!"

restore-full: restore-configs

clean:
	@echo "Stopping and removing containers (if they are running)..."
	@$(COMPOSE) $(COMPOSE_FILES) --profile enabled down

	@echo "Reverting git files to original"
	@sudo git clean -fdx

	@echo -n "Cleaning Certs folders........."
	@cd certs && find . ! -name '.gitignore' -type f -exec sudo rm -f {} + && cd ..
	@echo ".OK!"

	@echo -n "Cleaning Download folders........."
	@cd shared && find . ! -name '.gitignore' -type f -exec sudo rm -f {} + && cd ..
	@echo ".OK!"

clean_all: clean
	@echo -n "Cleaning Media folders........."
	@cd media && find . ! -name '.gitignore' ! -name 'metadata.db' -type f -exec sudo rm -f {} + && cd ..
	@echo ".OK!"

check_requirements:
	make --version
	@echo
	@(command -v podman && podman --version) || docker --version
	@echo
	@(command -v podman-compose && podman-compose --version) || docker compose version
	@echo
	yq --version
	@echo
	xmlstarlet --version
	@echo
	uname --kernel-release
	@echo
	@modinfo wireguard 2>/dev/null || lsmod | grep wireguard || echo "WARNING: WireGuard module not loaded"

detect_secrets_create_baseline:
	@echo -n "Creating detect-secrets baseline file........."
	@detect-secrets scan > .secrets.baseline
	@echo ".OK!"

down:
	@echo "Stopping containers (if they are running)..."
	@if [ "$(RUNTIME)" = "podman" ]; then \
		project_filter="label=com.docker.compose.project=$(COMPOSE_PROJECT_NAME)"; \
		project_containers="$$(podman ps --all --filter "$$project_filter" --format "{{.Names}}")"; \
		if [ -z "$$project_containers" ]; then \
			echo "No stack containers found."; \
		else \
			running_containers="$$(podman ps --filter "$$project_filter" --format "{{.Names}}")"; \
			if [ -n "$$running_containers" ]; then \
				echo "$$running_containers" | xargs -r podman kill --signal TERM >/dev/null || true; \
				elapsed=0; \
				while [ "$$elapsed" -lt "$(PODMAN_DOWN_TIMEOUT)" ]; do \
					remaining="$$(podman ps --filter "$$project_filter" --format "{{.Names}}")"; \
					[ -z "$$remaining" ] && break; \
					sleep 1; \
					elapsed=$$((elapsed + 1)); \
				done; \
				remaining="$$(podman ps --filter "$$project_filter" --format "{{.Names}}")"; \
				if [ -n "$$remaining" ]; then \
					echo "Force-killing containers still running after $(PODMAN_DOWN_TIMEOUT)s..."; \
					echo "$$remaining" | xargs -r podman kill >/dev/null || true; \
				fi; \
			fi; \
			echo "$$project_containers" | grep -vx gluetun | xargs -r podman rm --force --time 0 >/dev/null || true; \
			echo "$$project_containers" | grep -x gluetun | xargs -r podman rm --force --time 0 >/dev/null || true; \
			for network in edge media wan; do \
				podman network rm "$(COMPOSE_PROJECT_NAME)_$$network" >/dev/null 2>&1 || true; \
			done; \
		fi; \
	else \
		$(COMPOSE) $(COMPOSE_FILES) --profile enabled down --timeout 60; \
	fi

configure_jellyfin_network:
	@echo "Configuring Jellyfin network settings..."
	@if [ "$(RUNTIME)" = "podman" ]; then runner="podman unshare"; else runner=""; fi; \
	$$runner xmlstarlet --quiet ed --inplace \
		--update '/NetworkConfiguration/BaseUrl' --value "$(JELLYFIN_BASE_URL)" \
		--delete '/NetworkConfiguration/KnownProxies/string' \
		--subnode '/NetworkConfiguration/KnownProxies' --type elem --name string --value "$(JELLYFIN_KNOWN_PROXY)" \
		"configs/jellyfin/config/network.xml"

generate_certificate:
	@echo -n "Generating self-signed certificate..."
	@openssl req -new -newkey rsa:4096 -days 3650 -nodes -x509 \
		-subj "/C=${CERT_COUNTRY}/ST=${CERT_STATE}/L=${CERT_CITY}/O=${CERT_ORGANIZATION}/OU=${CERT_OU}/CN=${CERT_FQDN}" \
		-addext "subjectAltName = DNS:${CERT_FQDN}, DNS:${JELLYFIN_PROXY_DOMAIN}, DNS:localhost, IP:127.0.0.1, IP:${LAN_IP}, IP:${GLUETUN_SERVICES_IP}, IP:${GLUETUN_OBSERVABILITY_IP}" \
		-keyout certs/server.key -out certs/server.crt
	@openssl pkcs12 -export -out ${CERTIFICATES_FOLDER}/server.pfx -inkey ${CERTIFICATES_FOLDER}/server.key -in ${CERTIFICATES_FOLDER}/server.crt -password pass:${CERT_PASSWORD}
	@echo Hash for the certificate is...
	@openssl x509 -noout -fingerprint -sha256 -inform pem -in ${CERTIFICATES_FOLDER}/server.crt
	@echo Updating certificate password in Apps configs...
	@echo -n "Lidarr... 		"; 	xmlstarlet --quiet ed --inplace --update '/Config/SslCertPassword' --value "${CERT_PASSWORD}" "configs/lidarr/config/config.xml"; 			echo OK!  # pragma: allowlist secret
	@echo -n "Prowlarr...		"; 	xmlstarlet --quiet ed --inplace --update '/Config/SslCertPassword' --value "${CERT_PASSWORD}" "configs/prowlarr/config/config.xml"; 		echo OK!  # pragma: allowlist secret
	@echo -n "Radarr... 		";	xmlstarlet --quiet ed --inplace --update '/Config/SslCertPassword' --value "${CERT_PASSWORD}" "configs/radarr/config/config.xml"; 			echo OK!  # pragma: allowlist secret
	@echo -n "Readarr... 		";	xmlstarlet --quiet ed --inplace --update '/Config/SslCertPassword' --value "${CERT_PASSWORD}" "configs/readarr/config/config.xml"; 			echo OK!  # pragma: allowlist secret
	@echo -n "Sonarr... 		";	xmlstarlet --quiet ed --inplace --update '/Config/SslCertPassword' --value "${CERT_PASSWORD}" "configs/sonarr/config/config.xml"; 			echo OK!  # pragma: allowlist secret
	@echo -n "Whisparr...		";	xmlstarlet --quiet ed --inplace --update '/Config/SslCertPassword' --value "${CERT_PASSWORD}" "configs/whisparr/config/config.xml"; 		echo OK!  # pragma: allowlist secret
	@echo -n "Jellyfin...		";	xmlstarlet --quiet ed --inplace --update '/NetworkConfiguration/CertificatePassword' --value "${CERT_PASSWORD}" "configs/jellyfin/config/network.xml"; echo OK!  # pragma: allowlist secret
	@echo -n "NZBHydra...		"; 	sslKey="${CERT_PASSWORD}" yq -i '(.main.sslKeyStorePassword) = strenv(sslKey)' "configs/nzbhydra2/config/nzbhydra.yml"; 	echo OK!

install_requirements:
	@echo "Installing requirements..."
	@echo "Recommended: Podman (rootless, daemonless, more secure than Docker)"
	@echo "  Fedora/RHEL:  sudo dnf install podman podman-compose xmlstarlet wireguard-tools"
	@echo "  Debian/Ubuntu: sudo apt install podman podman-compose xmlstarlet wireguard"
	@echo ""
	@echo "Alternative: Docker"
	@echo "  sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras xmlstarlet wireguard"
	@echo ""
	@echo "yq: https://github.com/mikefarah/yq#install  (or via asdf: asdf install)"

pre_commit:
	@echo "Running pre-commit checks..."
	@pre-commit run --all-files

disk_status:
	@./scripts/disk-status.sh

permissions_check:
	@./scripts/permissions.py check --runtime $(RUNTIME)

permissions_repair:
	@./scripts/permissions.py repair --runtime $(RUNTIME) --recursive

permissions_smoke:
	@./scripts/permissions.py smoke --runtime $(RUNTIME)

permissions_host_smoke:
	@./scripts/permissions.py host-smoke --runtime $(RUNTIME)

rotate_nginx_logs:
	@./scripts/rotate-nginx-logs.sh

prune_cache:
	@./scripts/prune-nginx-cache.sh

sanity_fast:
	@echo "Running fast sanity checks..."
	@pre-commit run --all-files

sanity_full: sanity_fast
	@echo "Running full MegaLinter push checks..."
	@pre-commit run megalinter-full --hook-stage pre-push --all-files

build_images:
	@echo "Building custom container images..."
	@$(COMPOSE) $(COMPOSE_FILES) --profile enabled build lazylibrarian mylar

pull_docker_images:
	@echo "Pulling container images..."
	@$(COMPOSE) $(COMPOSE_FILES) --profile enabled pull

restart:
	@echo "Re-starting containers..."
	@$(COMPOSE) $(COMPOSE_FILES) --profile enabled restart

rotate_passwords:
	@BAZARR_PASSWORD="$(echo "bazarr${RANDOM})"; yq --in-place '(.auth.apikey) = strenv(BAZARR_PASSWORD)' "configs/bazarr/config/config/config.yaml"

repair_permissions:
	@echo "Repairing managed data/config ownership and ACLs..."
	@./scripts/permissions.py repair --runtime $(RUNTIME) --recursive

start:
	@if [ "$(RUNTIME)" = "podman" ]; then \
		stopping=$$(podman ps -a --format "{{.ID}} {{.State}}" | awk '/stopping/{print $$1}'); \
		if [ -n "$$stopping" ]; then \
			echo "Force-killing containers stuck in stopping state..."; \
			echo "$$stopping" | xargs podman kill 2>/dev/null || true; \
		fi \
	fi
	@echo "Ensuring required networks exist..."
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_apps || $(RUNTIME) network create docker-torrent-box-with-vpn_apps
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_services || $(RUNTIME) network create --internal --subnet ${SERVICES_SUBNET} docker-torrent-box-with-vpn_services
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_observability || $(RUNTIME) network create --internal --subnet ${OBSERVABILITY_SUBNET} docker-torrent-box-with-vpn_observability
	@echo "Starting VPN gateway..."
	@$(COMPOSE) $(COMPOSE_FILES) --profile enabled up --detach --no-recreate gluetun
	@echo "Waiting for VPN gateway to be healthy (up to 120s)..."
	@timeout 120 sh -c 'until $(RUNTIME) inspect gluetun --format "{{.State.Health.Status}}" 2>/dev/null | grep -q healthy; do sleep 5; done' || (echo "ERROR: gluetun did not become healthy in time"; exit 1)
	@echo "Starting all containers..."
	@$(COMPOSE) $(COMPOSE_FILES) --profile enabled up --detach --no-recreate

start_library:
	@echo "Starting Media Library containers..."
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_apps || $(RUNTIME) network create docker-torrent-box-with-vpn_apps
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_services || $(RUNTIME) network create --internal --subnet ${SERVICES_SUBNET} docker-torrent-box-with-vpn_services
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_media || $(RUNTIME) network create --subnet ${MEDIA_SUBNET} docker-torrent-box-with-vpn_media
	@$(COMPOSE) --file docker-compose.yml --file docker-compose-media-library.yml --profile enabled up --detach --no-recreate

start_observability:
	@echo "Starting Observability containers..."
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_apps || $(RUNTIME) network create docker-torrent-box-with-vpn_apps
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_services || $(RUNTIME) network create --internal --subnet ${SERVICES_SUBNET} docker-torrent-box-with-vpn_services
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_observability || $(RUNTIME) network create --internal --subnet ${OBSERVABILITY_SUBNET} docker-torrent-box-with-vpn_observability
	@$(COMPOSE) --file docker-compose-observability.yml --profile enabled up --detach

stop: stop_all

stop_all:
	@echo "Stopping containers (if they are running)..."
	@$(COMPOSE) $(COMPOSE_FILES) --profile enabled stop

update_containers:
	@echo "Stopping containers..."
	@$(COMPOSE) $(COMPOSE_FILES) --profile enabled stop

	@echo "Ensuring required networks exist..."
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_apps || $(RUNTIME) network create docker-torrent-box-with-vpn_apps
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_services || $(RUNTIME) network create --internal --subnet ${SERVICES_SUBNET} docker-torrent-box-with-vpn_services
	@$(RUNTIME) network exists docker-torrent-box-with-vpn_observability || $(RUNTIME) network create --internal --subnet ${OBSERVABILITY_SUBNET} docker-torrent-box-with-vpn_observability

	@echo "Pulling images..."
	@$(COMPOSE) $(COMPOSE_FILES) pull

	@echo "Starting containers..."
	@$(COMPOSE) $(COMPOSE_FILES) --profile enabled up --detach

update_pre_commit:
	@echo "Updating pre-commit hooks..."
	@pre-commit autoupdate

tests/.venv:
	@echo "Creating test virtual environment..."
	@python3 -m venv tests/.venv
	@tests/.venv/bin/pip install -q -r tests/requirements.txt
	@echo ".OK!"

test: tests/.venv ## Run full test suite (requires the stack to be running)
	@tests/.venv/bin/pytest $(PYTEST_ARGS)

test_prerequisites: tests/.venv ## Run only pre-flight checks (no containers needed)
	@tests/.venv/bin/pytest -m prerequisites $(PYTEST_ARGS)
