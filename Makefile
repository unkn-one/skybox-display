                                                                 # Makefile for skybox-display (.deb with bundled virtualenv via dh-virtualenv)

PKG        := skybox-display
SERVICE    := $(PKG)

# Derived versions
PY_VERSION      := $(shell python3 scripts/version.py show)
DEB_BASE_VER    := $(shell python3 scripts/version.py debian)
DEB_VERSION     := $(DEB_BASE_VER)-1

# Tools
DCH          := dch
DPKG_BUILD   := dpkg-buildpackage
APT          := sudo apt-get
INSTALL_DEB  := sudo apt-get install -y

# ---------- Phony ----------
.PHONY: all info deps clean distclean changelog deb package install uninstall \
        reinstall bump-major bump-minor bump-patch service-start service-stop \
        service-restart service-status logs

all: deb

info:
	@echo "Package      : $(PKG)"
	@echo "PEP440 ver   : $(PY_VERSION)"
	@echo "Debian ver   : $(DEB_VERSION)"

deps:
	@echo "[deps] Installing packaging toolchain"
	$(APT) update
	$(APT) install -y build-essential debhelper devscripts dh-virtualenv python3-all python3 python3-venv python3-pip git
	@echo "[deps] (optional) setuptools-scm for local 'show' without CI"
	pip3 install -q --upgrade setuptools-scm || true

clean:
	@echo "[clean] Removing build artifacts"
	rm -rf build dist *.egg-info
	rm -f ../$(PKG)_* || true
	find . -name '__pycache__' -type d -exec rm -rf {} +

distclean: clean
	@echo "[distclean] Done"

# Ensure changelog matches DEB_VERSION
changelog:
	@test -d debian || (echo "Missing debian/ directory" && exit 1)
	@if [ -f debian/changelog ]; then \
	  CUR=$$(dpkg-parsechangelog -S Version || true); \
	  if [ "$$CUR" != "$(DEB_VERSION)" ]; then \
	    echo "[changelog] Updating $$CUR -> $(DEB_VERSION)"; \
	    DEBEMAIL="$${DEBEMAIL:-$$USER@localhost}" DEBFULLNAME="$${DEBFULLNAME:-$$(git config user.name || echo 'CI Builder')}" \
	    $(DCH) --newversion "$(DEB_VERSION)" --distribution bookworm \
	           "Sync changelog to version $(PY_VERSION)."; \
	  else \
	    echo "[changelog] Already at $(DEB_VERSION)"; \
	  fi \
	else \
	  echo "[changelog] Creating initial changelog at $(DEB_VERSION)"; \
	  DEBEMAIL="$${DEBEMAIL:-$$USER@localhost}" DEBFULLNAME="$${DEBFULLNAME:-$$(git config user.name || echo 'CI Builder')}" \
	  $(DCH) --create --package $(PKG) --newversion "$(DEB_VERSION)" \
	         --distribution bookworm "Initial changelog for $(PY_VERSION)."; \
	fi

# Build unsigned binary .deb
deb package: changelog
	@echo "[build] Building $(PKG) $(DEB_VERSION)"
	$(DPKG_BUILD) -us -uc -b
	@echo "[build] Result(s):"
	@ls -lh ../$(PKG)_*_*\.deb

install: deb
	@debfile=$$(ls -1 ../$(PKG)_*_*\.deb | head -n1); \
	echo "[install] Installing $$debfile"; \
	$(INSTALL_DEB) "$$debfile"; \
	echo "[install] Enabling & starting service"; \
	sudo systemctl enable --now $(SERVICE).service

uninstall:
	- sudo systemctl disable --now $(SERVICE).service
	- sudo apt-get remove -y $(PKG)

reinstall: uninstall install

# -------- Version bumps (create annotated git tag vX.Y.Z) --------
bump-patch:
	@python3 scripts/version.py bump patch

bump-minor:
	@python3 scripts/version.py bump minor

bump-major:
	@python3 scripts/version.py bump major

# -------- Service helpers --------
service-start:
	sudo systemctl start $(SERVICE).service

service-stop:
	sudo systemctl stop $(SERVICE).service

service-restart:
	sudo systemctl restart $(SERVICE).service

service-status:
	systemctl status $(SERVICE).service

logs:
	journalctl -u $(SERVICE).service -e -n 200 -f
