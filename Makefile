.PHONY: clean

clean: 
	@echo "Reverting git files to orignal"
	@git clean -fdx
	@echo -n "Cleaning Download folders."
	@cd shared
	@sudo find . ! -name '.gitignore' -type f -exec rm -f {} +
	@cd ..
	@echo ".OK!"
	@echo -n "Cleaning Media folders."
	@cd media
	@sudo find . ! -name '.gitignore' -type f -exec rm -f {} +
	@cd ..
	@echo ".OK!"
