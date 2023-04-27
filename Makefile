include .env

.PHONY: backup clean clean_all create_config start stop update_images

all: generate_certificate update_images start

backup:
	@echo "Backing up config files..."
	@cp --recursive configs configs.backup.`date +%Y-%m-%d-%H:%M:%S`
	@cp --recursive certs certs.backup.`date +%Y-%m-%d-%H:%M:%S`
	@cp .env .env.backup.`date +%Y-%m-%d-%H:%M:%S`
	@echo ".OK!"

clean:
	@echo "Stopping and removing containers (if they are running)..."
	@docker-compose --profile enabled down

	@echo "Reverting git files to orignal"
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

detect_secrets_create_baseline:
	@echo -n "Creating detect-secrets baseline file........."
	@detect-secrets scan > .secrets.baseline
	@echo ".OK!"

down:
	@echo "Stopping containers (if they are running)..."
	@docker-compose --profile enabled down

generate_certificate:
	@echo -n "Generating self-signed certificate..."
	@openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 -subj "/C=${CERT_COUNTRY}/ST=${CERT_STATE}/L=${CERT_CITY}/O=${CERT_ORGANIZATION}/OU=${CERT_OU}/CN=${CERT_FQDN}" -keyout certs/server.key -out certs/server.crt
	@openssl pkcs12 -export -out ${CERTIFICATES_FOLDER}/server.pfx -inkey ${CERTIFICATES_FOLDER}/server.key -in ${CERTIFICATES_FOLDER}/server.crt -password pass:${CERT_PASSWORD}
	@echo Hash for the certificate is...
	@openssl x509 -noout -fingerprint -sha256 -inform pem -in ${CERTIFICATES_FOLDER}/server.crt

pre_commit:
	@echo "Running pre-commit checks..."
	@pre-commit run --all-files

pull_docker_images:
	@echo "Pulling Docker Images..."
	@docker-compose --profile enabled pull

restart:
	@echo "Re-starting containers..."
	@docker-compose --profile enabled restart

start:
	@echo "Starting containers..."
	@docker-compose --profile enabled up --detach

stop:
	@echo "Stopping containers (if they are running)..."
	@docker-compose --profile enabled stop

update_containers:
	@echo "Stopping Docker Containers..."
	@docker-compose --profile enabled stop

	@echo "Pulling Docker Images..."
	@docker-compose pull

	@echo "Starting containers..."
	@docker-compose --profile enabled up --detach

update_pre_commit:
	@echo "Updating pre-commit hooks..."
	@pre-commit autoupdate
