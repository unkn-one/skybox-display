PKG := skybox-display

.PHONY: all info deps clean distclean deb install uninstall reinstall \
        bump-patch bump-minor bump-major docker-image docker-deb docker-deb-arm64 \
        service-start service-stop service-restart service-status logs

all: deb

info:
	@echo "PEP440: $$(python3 scripts/version.py show)"
	@echo "Debian: $$(python3 scripts/version.py debian)-1"
	@echo "Desc  : $$(python3 scripts/version.py desc)"

deps:
	sudo apt-get update
	sudo apt-get install -y python3-dev python3-venv python3-pip git dpkg-dev build-essential make
	# convenience for dynamic versioning
	pip3 install -U setuptools-scm tomli || true

clean:
	rm -rf build

distclean: clean

deb:
	bash scripts/build_deb.sh

install: deb
	@debfile=$$(ls -1 build/$(PKG)_*_*\.deb | head -n1); \
	echo "[install] $$debfile"; \
	sudo apt-get install -y "$$debfile"; \
	sudo systemctl enable --now $(PKG).service

uninstall:
	- sudo systemctl disable --now $(PKG).service
	- sudo apt-get remove -y $(PKG)

reinstall: uninstall install

bump-patch:
	@python3 scripts/version.py bump patch

bump-minor:
	@python3 scripts/version.py bump minor

bump-major:
	@python3 scripts/version.py bump major

# -------- Dockerized build (no host pollution) --------
docker-image:
	docker build -t $(PKG)-builder -f Dockerfile .

docker-deb: docker-image
	docker run --rm -v "$$PWD":/work -w /work \
		-e DEBFULLNAME="$$(git config user.name || echo CI Builder)" \
		-e DEBEMAIL="$$(git config user.email || echo ci@example.com)" \
		$(PKG)-builder make deb

# build for arm64 on capable Docker (QEMU) hosts:
docker-deb-arm64: docker-image
	docker run --rm --platform=linux/arm64 -v "$$PWD":/work -w /work \
		-e ARCH=arm64 \
		-e DEBFULLNAME="$$(git config user.name || echo CI Builder)" \
		-e DEBEMAIL="$$(git config user.email || echo ci@example.com)" \
		$(PKG)-builder make deb

# -------- Service helpers --------
service-start:
	sudo systemctl start $(PKG).service
service-stop:
	sudo systemctl stop $(PKG).service
service-restart:
	sudo systemctl restart $(PKG).service
service-status:
	systemctl status $(PKG).service
logs:
	journalctl -u $(PKG).service -e -n 200 -f
