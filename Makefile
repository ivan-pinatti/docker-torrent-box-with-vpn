.PHONY: clean

clean: 
	@echo -n "Cleaning Download folders."
	@sudo rm -rf shared/Torrent/Downloads/*/
	@echo -n "."
	@sudo rm -rf shared/Torrent/Blackhole/*/
	@echo -n "."
	@sudo rm -rf shared/Torrent/Blackhole/*.torrent
	@echo -n "."
	@sudo rm -rf shared/Usenet/Blackhole/*/
	@echo -n "."
	@sudo rm -rf shared/Usenet/Downloads/*/
	@echo -n "."
	@sudo rm -rf shared/Usenet/Downloads/nzbget.log
	@echo ".OK!"
