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

# Menu Config
OPTIONS = [
    'Info',
    'Settings',
    'Cleaner Options',
    'Refresh Options',
    'Log Options',
    'Backup/Restore',
    'Fresh Start'
]

DESCRIPTIONS = {
    'Cleaner Options': (
        "• Soft Clean: Trims cache/thumbnails to your set limits.\n"
        "• Hard Clean: Full wipe of cache and texture databases."
    ),
    
    'Soft Clean': (
        "Trims cache and thumbnails based on Addon Settings.\n"
        "• Clears the packages folder to save space."
    ),
    
    'Hard Clean': (
        "CRITICAL: COMPLETELY clears Temp, Thumbnails, and Packages.\n"
        "• Deletes Textures13.db (Texture Database).\n"
        "• Kodi will FORCE CLOSE to rebuild the cache."
    ),
    
    'Refresh Options': "Force refresh repositories or reload the UI skin.",
    'Refresh Repos': "Manually triggers a scan of repositories for addon updates.",
    'Refresh UI': "Reloads the GUI skin to fix display glitches or menu errors.",
    
    'Backup/Restore': "Create or restore a full backup of your Kodi configuration.",
    
    'Backup': (
        "Creates a ZIP backup including:\n"
        "• Addons & Userdata & Media Directories"
    ),
    
    'Restore': (
        "RESTORE PROCEDURE:\n"
        "1. Select a ZIP backup to restore.\n"
        "2. WARNING: This will DELETE existing files!\n"
        "3. Kodi will FORCE CLOSE once finished.\n"
        "NOTE: If the screen goes black, please be patient while it extracts and wait for the success message"
    ),
    
    'Log Options': "Read, Export, Clear, or Upload the Kodi log file.",
    'Info': "View descriptions of all tools available in this addon.",
    'Settings': "Quickly open the settings window for Lazy Maintenance.",
    'Fresh Start': (
        "WARNING: Wipes all data except this maintenance tool.\n"
        "• Resets Kodi to factory default state."
    )
}
