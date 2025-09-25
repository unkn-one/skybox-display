#!/usr/bin/env bash
set -euo pipefail

PKG="skybox-display"
ARCH="${ARCH:-arm64}"  # Debian arch name (arm64 for aarch64)
INSTALL_PREFIX="/opt/${PKG}"
VENVDIR="${INSTALL_PREFIX}/.venv"
STAGE="$(pwd)/build/pkgroot"
OUTDIR="$(pwd)/build"
MAINT_NAME="${DEBFULLNAME:-CI Builder}"
MAINT_EMAIL="${DEBEMAIL:-ci@example.com}"

PY_VERSION="$(python3 scripts/version.py show)"
DEB_BASE_VER="$(python3 scripts/version.py debian)"
DEB_VERSION="${DEB_BASE_VER}-1"
DESC="$(python3 scripts/version.py desc)"

echo "[info] PEP440=${PY_VERSION}  Debian=${DEB_VERSION}  Arch=${ARCH}"
echo "[info] Desc='${DESC}'"

# clean stage
rm -rf "${STAGE}" "${OUTDIR}"
mkdir -p "${STAGE}/DEBIAN" "${STAGE}/usr/bin" "${STAGE}/lib/systemd/system" "${STAGE}${INSTALL_PREFIX}" "${OUTDIR}"

# create venv at final path within staging tree
echo "[venv] creating ${STAGE}${VENVDIR}"
python3 -m venv "${STAGE}${VENVDIR}"
"${STAGE}${VENVDIR}/bin/python" -m pip install --upgrade pip setuptools wheel

# install the project into that venv
echo "[pip] installing project into venv"
# Prefer binary wheels where available, but allow source builds
PIP_PREFER_BINARY=1 "${STAGE}${VENVDIR}/bin/pip" install .

# wrapper
cat > "${STAGE}/usr/bin/${PKG}" <<'SH'
#!/usr/bin/env bash
exec /opt/skybox-display/.venv/bin/skybox-display "$@"
SH
chmod 0755 "${STAGE}/usr/bin/${PKG}"

# systemd service (framebuffer)
cat > "${STAGE}/lib/systemd/system/${PKG}.service" <<'UNIT'
[Unit]
Description=Skybox Display
After=network-online.target

[Service]
Type=simple
ExecStart=/opt/skybox-display/.venv/bin/python3 -m skybox_display
Restart=on-failure
User=root

[Install]
WantedBy=multi-user.target
UNIT

# control file
cat > "${STAGE}/DEBIAN/control" <<CTRL
Package: ${PKG}
Version: ${DEB_VERSION}
Section: misc
Priority: optional
Architecture: ${ARCH}
Maintainer: ${MAINT_NAME} <${MAINT_EMAIL}>
Depends: python3 (>= 3.11), systemd
Description: ${DESC}
 Bundled virtualenv installed under ${INSTALL_PREFIX}
CTRL

# maintainer scripts
cat > "${STAGE}/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
systemctl daemon-reload || true
if [ "$1" = "configure" ]; then
    systemctl enable --now skybox-display.service || true
fi
exit 0
POST
chmod 0755 "${STAGE}/DEBIAN/postinst"

cat > "${STAGE}/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
if [ "$1" = "remove" ]; then
    systemctl stop skybox-display.service || true
    systemctl disable skybox-display.service || true
fi
exit 0
PRERM
chmod 0755 "${STAGE}/DEBIAN/prerm"

# perms
find "${STAGE}" -type d -print0 | xargs -0 chmod 0755

# build .deb
DEB_PATH="${OUTDIR}/${PKG}_${DEB_VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "${STAGE}" "${DEB_PATH}"
echo "[done] ${DEB_PATH}"
