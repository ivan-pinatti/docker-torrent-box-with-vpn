.PHONY: backup clean clean_all create_config start stop update_images

all: create_config update_images start

backup:
	@echo "Backing up config files..."
	@cp --recursive configs configs.backup.`date +%Y-%m-%d-%H:%M:%S`
	@echo ".OK!"

clean:
	@echo "Stopping and removing containers (if they are running)..."
	@docker-compose --profile enabled down

	@echo "Reverting git files to orignal"
	@sudo git clean -fdx

	@echo -n "Cleaning Download folders........."
	@cd shared && find . ! -name '.gitignore' -type f -exec sudo rm -f {} + && cd ..
	@echo ".OK!"

clean_all: clean
	@echo -n "Cleaning Media folders........."
	@cd media && find . ! -name '.gitignore' ! -name 'metadata.db' -type f -exec sudo rm -f {} + && cd ..
	@echo ".OK!"

create_config:
	@echo -n "Creating .env file with defaults........."
	@cp .env.example .env
	@echo ".OK!"

generate_certificate:
	@echo -n "Generating self-signed certificate........."
	@echo ".OK!"

start:
	@echo "Starting containers..."
	@docker-compose --profile enabled up --detach

stop:
	@echo "Stopping containers (if they are running)..."
	@docker-compose --profile enabled stop

update_images:
	@echo "Updating Docker Images..."
	@docker-compose pull
