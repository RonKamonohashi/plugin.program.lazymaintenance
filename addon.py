import xbmcgui
import xbmcaddon
import shutil
import zipfile
import time
import os
import sys
import urllib.request
import urllib.parse
import json
import re
from pathlib import Path

# Import constants and paths
from constants import (
    ADDON, ADDON_ID, HOME, ADDONS, USERDATA, TEMP, THUMBNAILS, 
    PACKAGES, LOGPATH, MEDIA, DATABASE, OPTIONS, DESCRIPTIONS
)

# --- Helper Functions ---

def notify(title, message, time=5000):
    xbmcgui.Dialog().notification(title, message, time=time)

def confirm_action(title, message):
    return xbmcgui.Dialog().yesno(title, message)

def show_description(title, description):
    xbmcgui.Dialog().ok(title, description)

def log_error(context, exception):
    """Centralized error handling."""
    msg = f"LazyMaintenance Error [{context}]: {str(exception)}"
    xbmc.log(msg, xbmc.LOGERROR)
    if not context.startswith("Auto"):
        notify('Lazy Maintenance Error', f'{context}: {str(exception)}')

def get_zip_arcname(full_path, base_path):
    try:
        relative_path = full_path.relative_to(base_path)
        return str(relative_path).replace(os.sep, '/')
    except ValueError:
        return str(full_path.name)

def get_folder_size(path_obj):
    total = 0
    if not path_obj.exists():
        return 0
    for root, dirs, files in os.walk(str(path_obj)):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total

def force_close_kodi():
    """
    Aggressively kills Kodi to prevent it from saving current RAM settings 
    over the files we just restored (crucial for guisettings.xml).
    """
    try:
        xbmc.log("LazyMaintenance: Initiating Force Close sequence...", xbmc.LOGINFO)
        
        # 1. Platform specific system kills
        if xbmc.getCondVisibility('system.platform.windows'):
            os.system('taskkill /F /IM kodi.exe /T')
        elif xbmc.getCondVisibility('system.platform.android'):
            # Android is restrictive, but we try standard commands
            pass 
        else: # Linux / MacOS / LibreELEC
            os.system('killall -9 kodi.bin')
            os.system('killall -9 kodi')
            
    except Exception as e:
        xbmc.log(f"LazyMaintenance: System kill failed: {e}", xbmc.LOGDEBUG)

    # 2. Python Hard Exit (The most reliable cross-platform crasher)
    try:
        os._exit(1)
    except:
        sys.exit(1)

# --- Core Logic ---

def trim_folder(path_obj, max_size_mb):
    """Trims folder to target size in MB."""
    if not path_obj.exists():
        return

    max_size_bytes = max_size_mb * 1024 * 1024
    current_size = get_folder_size(path_obj)
    
    if current_size <= max_size_bytes:
        return

    files = []
    for root, dirs, files_list in os.walk(str(path_obj)):
        for f in files_list:
            if f == 'kodi.log': continue
            fp = Path(root) / f
            try:
                stat = fp.stat()
                files.append((stat.st_mtime, stat.st_size, fp))
            except Exception as e:
                xbmc.log(f"Error reading file stats {fp}: {e}", xbmc.LOGDEBUG)

    files.sort(key=lambda x: x[0])

    for mtime, size, fp in files:
        try:
            fp.unlink()
            current_size -= size
            if current_size <= max_size_bytes:
                break
        except Exception as e:
            xbmc.log(f"Failed to delete {fp}: {e}", xbmc.LOGDEBUG)

    for root, dirs, files in os.walk(str(path_obj), topdown=False):
        for d in dirs:
            dp = Path(root) / d
            try:
                if not any(dp.iterdir()):
                    dp.rmdir()
            except Exception:
                pass

def clear_folder(path_obj):
    if not path_obj.exists():
        return
    for item in path_obj.iterdir():
        try:
            # Skip kodi.log to prevent deletion
            if item.name == 'kodi.log':
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink()
        except Exception as e:
            xbmc.log(f"Error clearing {item}: {e}", xbmc.LOGERROR)

# --- Actions ---

def hard_clean():
    # 1. Display the description dialog
    show_description('Hard Clean', DESCRIPTIONS['Hard Clean'])
    
    # 2. Display the Yes/No confirmation dialog
    if not confirm_action('Hard Clean Confirmation', 
                          '[COLOR red][B]This is a destructive action![/B][/COLOR]\n\n'
                          'It will completely clear Temp, Thumbnails, Packages\n'
                          'and delete Textures13.db.\n\n'
                          '[B]Are you sure you want to proceed?[/B]'):
        return

    try:
        progress = xbmcgui.DialogProgress()
        progress.create('Hard Clean', 'Clearing folders...')

        progress.update(20, 'Clearing Temp folder...')
        clear_folder(TEMP)

        progress.update(40, 'Clearing Packages folder...')
        clear_folder(PACKAGES)

        progress.update(60, 'Clearing Thumbnails folder...')
        clear_folder(THUMBNAILS)

        progress.update(80, 'Deleting Textures13.db...')
        textures_db = DATABASE / 'Textures13.db'
        if textures_db.exists():
            textures_db.unlink()

        progress.update(100, 'Complete!')
        progress.close()

        # 3. Prompt the final dialog before closing
        xbmcgui.Dialog().ok('Hard Clean Complete', 
                            'Hard Clean completed successfully.\n\n'
                            'Press OK to force close Kodi.')
        
        # 4. Force close
        force_close_kodi()

    except Exception as e:
        if 'progress' in locals(): progress.close()
        log_error('Hard Clean', e)

def clean(silent=False):
    """Auto clean on startup"""
    try:
        try:
            auto_limit = int(ADDON.getSetting('auto_clean_size'))
        except:
            auto_limit = 50

        # Updated Logic: Clear Temp, Clear Packages, Trim Thumbnails
        clear_folder(TEMP)
        clear_folder(PACKAGES)
        trim_folder(THUMBNAILS, auto_limit)

        if silent:
            msg = 'Auto clean done.'
        else:
            msg = 'Cleaning completed.'
        notify('Lazy Maintenance', msg)

    except Exception as e:
        log_error('Auto Cleaning', e)

def refresh_options():
    menu = ['Refresh Repos', 'Refresh UI']
    idx = xbmcgui.Dialog().select('Refresh Options', menu)
    if idx == -1: return
    if idx == 0:
        refresh_repos()
    elif idx == 1:
        reload_ui()
        notify('Lazy Maintenance', 'UI Refreshed')

def backup_restore():
    menu = ['Backup', 'Restore']
    idx = xbmcgui.Dialog().select('Backup/Restore', menu)
    if idx == -1: return
    if idx == 0:
        backup()
    elif idx == 1:
        restore()

# --- Backup/Restore Functions ---

def backup():
    show_description('Backup', DESCRIPTIONS['Backup'])
    
    kb = xbmc.Keyboard('', 'Enter backup name (leave empty for timestamp)')
    kb.doModal()
    if not kb.isConfirmed(): return
    
    zip_name = kb.getText().strip()
    if not zip_name:
        zip_name = f"kodi_backup_{time.strftime('%Y-%m-%d_%H-%M-%S')}"
    if not zip_name.endswith('.zip'):
        zip_name += '.zip'
    
    dest_dir_str = xbmcgui.Dialog().browse(3, 'Select backup location', 'files')
    if not dest_dir_str:
        notify('Lazy Maintenance', 'Backup cancelled.')
        return
    
    dest_dir = Path(dest_dir_str)
    zip_path = dest_dir / zip_name

    if zip_path.exists():
        if not confirm_action('File Exists', 
                              f'[B]{zip_name}[/B] already exists in the selected location.\n\n'
                              'Do you want to overwrite it?'):
            return

    try:
        progress = xbmcgui.DialogProgress()
        progress.create('Backup', 'Calculating files...')
        
        total_items = sum([len(files) for r, d, files in os.walk(str(ADDONS))]) + \
                      sum([len(files) for r, d, files in os.walk(str(USERDATA))]) + \
                      sum([len(files) for r, d, files in os.walk(str(MEDIA))])
        
        if total_items == 0: total_items = 1 
        current = 0

        with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zipf:
            
            def add_folder_to_zip(folder_path, exclude_db=False):
                nonlocal current
                for root, dirs, files in os.walk(str(folder_path)):
                    # Exclude Thumbnails if scanning USERDATA
                    if folder_path == USERDATA and 'Thumbnails' in dirs:
                        dirs.remove('Thumbnails')

                    # Exclude Packages if scanning ADDONS
                    if folder_path == ADDONS and 'packages' in dirs:
                        dirs.remove('packages')
                    
                    # Exclude temp if scanning ADDONS
                    if folder_path == ADDONS and 'temp' in dirs:
                        dirs.remove('temp')
                    
                    for file in files:
                        # Exclude Textures13.db if requested
                        if exclude_db and file.lower().startswith('textures') and file.lower().endswith('.db'):
                            continue

                        full_path = Path(root) / file
                        arcname = get_zip_arcname(full_path, HOME)
                        
                        try:
                            zipf.write(str(full_path), arcname)
                        except Exception:
                            pass # Skip files we can't read

                        current += 1
                        pct = int(current * 100 / total_items)
                        progress.update(pct, f'Backing up: {file}')
                        
                        if progress.iscanceled():
                            raise KeyboardInterrupt("Cancelled")

            add_folder_to_zip(ADDONS)
            add_folder_to_zip(USERDATA, exclude_db=True)
            
            # Create empty placeholder dirs in zip
            zi_thumbnails = zipfile.ZipInfo('userdata/Thumbnails/')
            zi_thumbnails.external_attr = 0o40775 << 16 | 0x10
            zipf.writestr(zi_thumbnails, '')
            
            zi_media = zipfile.ZipInfo('media/') 
            zi_media.external_attr = 0o40775 << 16 | 0x10
            zipf.writestr(zi_media, '')

            add_folder_to_zip(MEDIA)

        progress.close()
        xbmcgui.Dialog().ok('Backup Complete', 
                            f'Backup created successfully!\n\n'
                            f'Location:\n{str(zip_path)}\n\n'
                            'Press OK to return.')

    except KeyboardInterrupt:
        progress.close()
        if zip_path.exists(): zip_path.unlink()
        notify('Backup', 'Cancelled by user.')
    except Exception as e:
        if 'progress' in locals(): progress.close()
        log_error('Backup', e)

def restore():
    show_description('Restore', DESCRIPTIONS['Restore'])
    zip_path_str = xbmcgui.Dialog().browse(1, 'Select backup ZIP', 'files', '.zip')
    if not zip_path_str: return

    # Stronger warning about the force close
    if not confirm_action('Confirm Restore', 
                          '[COLOR red][B]DANGER: This will overwrite everything![/B][/COLOR]\n\n'
                          'Your current addons, settings, and data will be deleted\n'
                          'and replaced with the backup contents.\n\n'
                          'Kodi will force close at the end (this is normal).\n\n'
                          '[B]Proceed?[/B]'):
        return

    try:
        progress = xbmcgui.DialogProgress()
        progress.create('Restore', 'Preparing folders...')

        # 1. Aggressive Wipe (with error tolerance)
        folders_to_wipe = [ADDONS, USERDATA, MEDIA]
        
        for i, folder in enumerate(folders_to_wipe):
             progress.update(int(i*10 + 10), f'Wiping: {folder.name}')
             if folder.exists():
                 # We try to remove individual items to handle locked files gracefully
                 for item in folder.iterdir():
                     try:
                         if item.is_dir():
                             shutil.rmtree(str(item), ignore_errors=True)
                         else:
                             item.unlink()
                     except Exception:
                         # Likely log file locked, ignore and continue
                         pass
                 
                 # Re-ensure folder exists
                 folder.mkdir(parents=True, exist_ok=True)

        # 2. Extract
        zip_path = Path(zip_path_str)
        with zipfile.ZipFile(str(zip_path), 'r') as zipf:
            files = zipf.namelist()
            total = len(files)
            
            for idx, member in enumerate(files):
                if progress.iscanceled():
                    notify('Restore', 'Cancelled.')
                    return
                
                # Determine target path
                if member.startswith('media/'):
                    # Map zip 'media/...' -> 'special://home/media/...'
                    target_path = MEDIA / member[6:]
                else:
                    # Map zip 'addons/...' or 'userdata/...' -> 'special://home/...'
                    target_path = HOME / member
                
                try:
                    if member.endswith('/'):
                        target_path.mkdir(parents=True, exist_ok=True)
                    else:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        with zipf.open(member) as s, open(str(target_path), 'wb') as d:
                            shutil.copyfileobj(s, d)
                except Exception as e:
                    xbmc.log(f"LazyMaintenance: Failed to restore {member}: {e}", xbmc.LOGDEBUG)
                
                progress.update(40 + int((idx / total) * 60), f'Restoring: {member}')

        progress.close()
        
        # 3. Final Warning
        xbmcgui.Dialog().ok('Restore Complete', 
                            'Restore completed successfully.\n\n'
                            'Press OK to force close Kodi.\n'
                            '(The app may appear to crash - this is normal.)')
        
        # 4. EXECUTE FORCE CLOSE
        force_close_kodi()

    except Exception as e:
        if 'progress' in locals(): progress.close()
        log_error('Restore', e)

def reset_kodi():
    show_description('Fresh Start', DESCRIPTIONS['Fresh Start'])
    if not confirm_action('Confirm Fresh Start', 
                          '[COLOR red][B]Are you absolutely sure?[/B][/COLOR]\n\n'
                          'This will delete all userdata and remove all addons\n'
                          '(except this maintenance tool).\n\n'
                          'Kodi will be reset to a fresh state.'):
        return

    try:
        if USERDATA.exists():
            shutil.rmtree(str(USERDATA), ignore_errors=True)
            USERDATA.mkdir()
        
        if ADDONS.exists():
            for item in ADDONS.iterdir():
                if item.name == ADDON_ID: continue
                if item.is_dir():
                    shutil.rmtree(str(item), ignore_errors=True)
                else:
                    item.unlink()

        xbmcgui.Dialog().ok('Fresh Start Complete', 
                            'All data has been wiped.\n\n'
                            'Press OK to force close Kodi.')
        force_close_kodi()
        
    except Exception as e:
        log_error('Fresh Start', e)

def upload_log():
    log_file = LOGPATH / 'kodi.log'
    if not log_file.exists():
        notify('Error', 'No log file found.')
        return

    if not confirm_action('Upload Log', '[B]Upload kodi.log[/B] to a public paste service?\n\nThe URL will be shown after upload.'):
        return

    try:
        addon_version = ADDON.getAddonInfo('version')
        user_agent_string = f'Kodi-LazyMaintenance/{addon_version}'

        with open(str(log_file), 'rb') as f:
            log_data = f.read()

        req = urllib.request.Request(
            'https://paste.kodi.tv/documents', 
            data=log_data,
            headers={'User-Agent': user_agent_string}
        )
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        if 'key' in result:
            url = f"https://paste.kodi.tv/{result['key']}"
            xbmcgui.Dialog().textviewer('Log Uploaded Successfully', f"Log URL:\n{url}")
        else:
            notify('Upload Failed', 'Could not parse response.')

    except Exception as e:
        log_error('Log Upload', e)

def log_options():
    log_menu = ['Read', 'Export', 'Upload', 'Clear']
    idx = xbmcgui.Dialog().select('Log Options', log_menu)
    if idx == -1: return

    log_file = LOGPATH / 'kodi.log'
    
    if idx == 0:  # Read
        if not log_file.exists():
            notify('Error', 'No log file found.')
            return
        try:
            with open(str(log_file), 'r', encoding='utf-8', errors='ignore') as f:
                xbmcgui.Dialog().textviewer('Kodi Log', f.read())
        except Exception as e:
            log_error('Read Log', e)
    elif idx == 1:  # Export
        if not log_file.exists():
            notify('Error', 'No log file found.')
            return
        dest = xbmcgui.Dialog().browse(3, 'Select Export Location', 'files')
        if dest:
            try:
                shutil.copy(str(log_file), os.path.join(dest, 'kodi.log'))
                notify('Success', 'Log exported successfully.')
            except Exception as e: 
                log_error('Export Log', e)
    elif idx == 2:  # Upload
        upload_log()
    elif idx == 3:  # Clear
        if not log_file.exists():
            notify('Error', 'No log file found.')
            return
        if confirm_action('Clear Log', 'Are you sure you want to clear the Kodi log?'):
            try:
                open(str(log_file), 'w').close()
                notify('Success', 'Log cleared.')
            except Exception as e: 
                log_error('Clear Log', e)

def reload_ui():
    xbmc.executebuiltin('ReloadSkin()')

def refresh_repos():
    notify('Lazy Maintenance', 'Scanning repositories...')
    xbmc.executebuiltin('UpdateAddonRepos')
    time.sleep(3)
    notify('Lazy Maintenance', 'Repository scan complete.')
    reload_ui()

def show_help():
    text = "[B]Lazy Maintenance - Feature Overview[/B]\n\n"
    for title, desc in DESCRIPTIONS.items():
        if title not in ["Info", "Settings"]:
            text += f"[B]{title}[/B]\n{desc}\n\n"
    xbmcgui.Dialog().textviewer('Help & Info', text)

def open_settings():
    xbmc.executebuiltin(f'Addon.OpenSettings({ADDON_ID})')

# --- Main Entry ---

def main():
    idx = xbmcgui.Dialog().select('Lazy Maintenance', OPTIONS)
    if idx == -1: return

    sel = OPTIONS[idx]
    
    if sel == 'Info':
        show_help()
    elif sel == 'Settings':
        open_settings()
    elif sel == 'Hard Clean':
        hard_clean()
    elif sel == 'Refresh Options':
        refresh_options()
    elif sel == 'Log Options':
        log_options()
    elif sel == 'Backup/Restore':
        backup_restore()
    elif sel == 'Fresh Start':
        reset_kodi()

if __name__ == '__main__':
    main()
