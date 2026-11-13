#!/bin/bash
# Rebuilds "ChordPro Maker.app" (an AppleScript applet that runs tools/launcher.sh). Run from anywhere.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/ChordPro Maker.app"
rm -rf "$APP"
osacompile -o "$APP" -e '
on run
	set script_ to POSIX path of (path to resource "launcher.sh")
	try
		do shell script "export PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin; /bin/bash " & quoted form of script_ & " </dev/null 2>&1"
	on error msg number n
		display alert "ChordPro Maker could not start" message ("Error " & n & ": " & msg & return & return & "Tried: " & script_ & return & "Try \"Start ChordPro Maker.command\" instead.") as critical
	end try
end run'
cp "$ROOT/tools/launcher.sh" "$APP/Contents/Resources/launcher.sh"
cp "$ROOT/tools/icon.icns" "$APP/Contents/Resources/applet.icns"
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleName ChordPro Maker" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier local.chordpro-maker" "$APP/Contents/Info.plist" 2>/dev/null || \
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string local.chordpro-maker" "$APP/Contents/Info.plist"
codesign --force --deep -s - "$APP" 2>/dev/null || true
echo "Built $APP"
