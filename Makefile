.PHONY: clean

clean: 
	@echo "Reverting git files to orignal"
	@sudo git clean -fdx
	@echo -n "Cleaning Download folders....."
	@cd shared && find . ! -name '.gitignore' -type f -exec sudo rm -f {} + && cd ..
	@echo ".OK!"
	@echo -n "Cleaning Media folders........."
	@cd media && find . ! -name '.gitignore' -type f -exec sudo rm -f {} + && cd ..
	@echo ".OK!"
