#!/usr/bin/env bash
# Install one desktop launcher per launch profile (LITE / SMART / FULL).
#
# - installs ~/.local/bin/36tb-launch (absolute paths substituted)
# - installs the 36tb-intelligence icon in the hicolor theme
# - creates .desktop files on the Desktop and in the application menu
# - marks them executable + trusted where supported
#
# Usage:
#   scripts/install_desktop_launchers.sh
#   scripts/install_desktop_launchers.sh --uninstall
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python)"

DESKTOP_DIR="${XDG_DESKTOP_DIR:-$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")}"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
WRAPPER="$BIN_DIR/36tb-launch"

PROFILES=(lite smart full)
declare -A LABEL=( [lite]="LITE" [smart]="SMART" [full]="FULL" )
declare -A PORT=( [lite]="8510" [smart]="8504" [full]="8501" )
declare -A DESC=(
  [lite]="Démarrage rapide, ressources réduites, IA locale"
  [smart]="Profil adapté au matériel, capacités à la demande"
  [full]="Toutes les capacités, chargement paresseux"
)

desktop_name() {
    echo "$DESKTOP_DIR/36TB Intelligence - ${LABEL[$1]}.desktop"
}
menu_name() {
    echo "$APPS_DIR/36tb-intelligence-$1.desktop"
}

uninstall() {
    echo "Removing desktop launchers..."
    for profile in "${PROFILES[@]}"; do
        rm -f "$(desktop_name "$profile")" "$(menu_name "$profile")"
    done
    rm -f "$WRAPPER" "$ICON_DIR/36tb-intelligence.svg"
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && \
        gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
    echo "Done."
}

if [ "${1:-}" = "--uninstall" ]; then
    uninstall
    exit 0
fi

[ -f "$ROOT/launchers/desktop/launch.sh" ] || {
    echo "missing template: $ROOT/launchers/desktop/launch.sh" >&2
    exit 2
}

mkdir -p "$DESKTOP_DIR" "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"

# 1. Wrapper with absolute ROOT/PY (handles spaces in the repository path).
sed -e "s|@ROOT@|$ROOT|g" -e "s|@PY@|$PY|g" \
    "$ROOT/launchers/desktop/launch.sh" > "$WRAPPER"
chmod 755 "$WRAPPER"

# 2. Icon (hicolor scalable theme).
cp "$ROOT/launchers/desktop/36tb-intelligence.svg" "$ICON_DIR/36tb-intelligence.svg"

# 3. Desktop + application-menu entries.
for profile in "${PROFILES[@]}"; do
    entry="$(desktop_name "$profile")"
    cat > "$entry" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=36TB Intelligence — ${LABEL[$profile]}
GenericName=Personal Knowledge System
Comment=${DESC[$profile]}
Exec="$WRAPPER" $profile
Icon=36tb-intelligence
Terminal=false
StartupNotify=true
Categories=Utility;FileTools;
Keywords=search;index;knowledge;documents;files;36TB;PIS;
Actions=Stop;

[Desktop Action Stop]
Name=Arrêter 36TB Intelligence — ${LABEL[$profile]}
Exec="$WRAPPER" --stop $profile
DESKTOP
    chmod 755 "$entry"
    cp "$entry" "$(menu_name "$profile")"
done

# 4. Trust + caches (best effort; KDE uses the executable bit).
if command -v gio >/dev/null 2>&1; then
    for profile in "${PROFILES[@]}"; do
        gio set "$(desktop_name "$profile")" metadata::trusted true >/dev/null 2>&1 || true
    done
fi
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true

# 5. Validate.
if command -v desktop-file-validate >/dev/null 2>&1; then
    for profile in "${PROFILES[@]}"; do
        desktop-file-validate "$(desktop_name "$profile")" || exit 1
    done
fi

echo "Installed launchers:"
for profile in "${PROFILES[@]}"; do
    echo "  - $(desktop_name "$profile")  (port ${PORT[$profile]})"
done
echo "  - application menu entries under $APPS_DIR"
echo "  - helper: $WRAPPER"
echo "  - icon:   $ICON_DIR/36tb-intelligence.svg"
