import xbmcaddon
import xbmcvfs
from pathlib import Path

ADDON_ID = 'plugin.program.lazymaintenance'
ADDON = xbmcaddon.Addon(ADDON_ID)

# Helper for Kodi Paths using pathlib
def get_kodi_path(path_str):
    return Path(xbmcvfs.translatePath(path_str))

# Paths
HOME = get_kodi_path('special://home/')
ADDONS = get_kodi_path('special://home/addons/')
USERDATA = get_kodi_path('special://userdata/')
TEMP = get_kodi_path('special://temp/')
THUMBNAILS = get_kodi_path('special://thumbnails/')
PACKAGES = get_kodi_path('special://home/addons/packages/')
LOGPATH = get_kodi_path('special://logpath/')
MEDIA = get_kodi_path('special://home/media/')
DATABASE = get_kodi_path('special://userdata/Database/')

DESCRIPTIONS = {
    'Hard Clean': (
        "[COLOR red][B]WARNING: This is destructive![/B][/COLOR]\n\n"
        "Completely clears:\n"
        "• Temp/Cache folder\n"
        "• Thumbnails folder\n"
        "• Packages folder\n\n"
        "Also deletes Textures13.db (texture cache database).\n\n"
        "Kodi will force close to properly rebuild textures."
    ),
    
    'Refresh Options': (
        "Refresh repositories or reload the user interface.\n\n"
        "• Refresh Repos: Manually scan for addon updates\n"
        "• Refresh UI: Reload skin to fix display glitches"
    ),
    
    'Backup/Restore': (
        "Create a complete backup of your Kodi configuration\n"
        "or restore from a previous backup.\n\n"
        "Safe way to save and recover your setup."
    ),
    
    'Backup': (
        "Creates a ZIP backup containing:\n\n"
        "• All installed addons\n"
        "• Userdata (settings, databases, favorites, etc.)\n"
        "• Media folder contents\n\n"
        "Excludes large cache folders (Thumbnails, Packages, Temp\n"
        "and Textures13.db) to keep the backup size manageable."
    ),
    
    'Restore': (
        "[COLOR red][B]DANGER: This overwrites your current setup![/B][/COLOR]\n\n"
        "Process:\n"
        "1. Select your backup ZIP file\n"
        "2. Current addons, settings and data are wiped\n"
        "3. Backup contents are restored\n"
        "4. Kodi force closes to apply changes\n\n"
        "[I]Note: The screen may go black during extraction –\n"
        "please be patient and wait for completion.[/I]"
    ),
    
    'Log Options': (
        "Manage the Kodi log file:\n\n"
        "• Read: View the current log\n"
        "• Export: Save log to another location\n"
        "• Upload: Share log via public paste service\n"
        "• Clear: Empty the log file"
    ),
    
    'Fresh Start': (
        "[COLOR red][B]WARNING: Total reset![/B][/COLOR]\n\n"
        "Deletes:\n"
        "• Entire userdata folder\n"
        "• All addons except this maintenance tool\n\n"
        "Results in a fresh Kodi installation.\n\n"
        "Kodi will force close afterwards."
    )
}