import xbmc
import xbmcgui
import xbmcaddon
import shutil
import zipfile
import time
import os
import urllib.request
import urllib.parse
import json
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
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink()
        except Exception as e:
            xbmc.log(f"Error clearing {item}: {e}", xbmc.LOGERROR)

# --- Actions ---

def soft_clean():
    """Former 'clean' function - now called Soft Clean"""
    try:
        try:
            manual_limit = int(ADDON.getSetting('manual_clean_size'))
        except:
            manual_limit = 5

        progress = xbmcgui.DialogProgress()
        progress.create('Soft Clean', 'Initializing cleaning process...')

        if progress: progress.update(10, f'Trimming Cache/Temp...\nTarget: {manual_limit}MB')
        trim_folder(TEMP, manual_limit)

        if progress: progress.update(40, 'Clearing Packages folder...')
        clear_folder(PACKAGES)

        if progress: progress.update(60, f'Trimming Thumbnails...\nTarget: {manual_limit}MB')
        trim_folder(THUMBNAILS, manual_limit)

        if progress: progress.update(90, 'Removing old logs...')
        old_log = LOGPATH / 'kodi.old.log'
        if old_log.exists():
            try:
                old_log.unlink()
            except: pass

        progress.update(100, 'Done!')
        progress.close()

        notify('Lazy Maintenance', 'Soft Clean completed successfully.')
        reload_ui()

    except Exception as e:
        if 'progress' in locals(): progress.close()
        log_error('Soft Clean', e)

def hard_clean():
    # 1. Display the description dialog
    show_description('Hard Clean', DESCRIPTIONS['Hard Clean'])
    
    # 2. Display the Yes/No confirmation dialog
    if not confirm_action('Hard Clean', 'This will completely clear Temp, Thumbnails, Packages and delete Textures13.db.\n\nAre you sure you want to proceed?'):
        return

    try:
        progress = xbmcgui.DialogProgress()
        progress.create('Hard Clean', 'Clearing folders...')

        progress.update(20, 'Clearing Temp...')
        clear_folder(TEMP)

        progress.update(40, 'Clearing Packages...')
        clear_folder(PACKAGES)

        progress.update(60, 'Clearing Thumbnails...')
        clear_folder(THUMBNAILS)

        progress.update(80, 'Deleting Textures13.db...')
        textures_db = DATABASE / 'Textures13.db'
        if textures_db.exists():
            textures_db.unlink()

        progress.update(100, 'Complete!')
        progress.close()

        # 3. Prompt the final dialog before closing
        xbmcgui.Dialog().ok('Hard Clean Done', 'Hard clean completed successfully.\nPress OK to force close Kodi.')
        
        # 4. Force close
        xbmc.executebuiltin('Quit')

    except Exception as e:
        if 'progress' in locals(): progress.close()
        log_error('Hard Clean', e)

def clean(silent=False):
    """Auto clean on startup - still uses auto_clean_size setting"""
    try:
        try:
            auto_limit = int(ADDON.getSetting('auto_clean_size'))
        except:
            auto_limit = 50

        trim_folder(TEMP, auto_limit)
        clear_folder(PACKAGES)
        trim_folder(THUMBNAILS, auto_limit)

        old_log = LOGPATH / 'kodi.old.log'
        if old_log.exists():
            try:
                old_log.unlink()
            except: pass

        if silent:
            msg = 'Auto clean done.'
        else:
            msg = 'Cleaning completed.'
        notify('Lazy Maintenance', msg)

    except Exception as e:
        log_error('Auto Cleaning', e)

def cleaner_options():
    menu = ['Soft Clean', 'Hard Clean']
    idx = xbmcgui.Dialog().select('Cleaner Options', menu)
    if idx == -1: return
    if idx == 0:
        soft_clean()
    elif idx == 1:
        hard_clean()

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

# --- Existing functions

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
        if not confirm_action('Overwrite?', f'{zip_name} exists. Overwrite?'):
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
                    
                    for file in files:
                        if exclude_db and file.lower().startswith('textures') and file.lower().endswith('.db'):
                            continue

                        full_path = Path(root) / file
                        arcname = get_zip_arcname(full_path, HOME)
                        
                        zipf.write(str(full_path), arcname)
                        current += 1
                        pct = int(current * 100 / total_items)
                        progress.update(pct, f'Backing up: {file}')
                        
                        if progress.iscanceled():
                            raise KeyboardInterrupt("Cancelled")

            add_folder_to_zip(ADDONS)
            add_folder_to_zip(USERDATA, exclude_db=True)
            
            zi_thumbnails = zipfile.ZipInfo('userdata/Thumbnails/')
            zi_thumbnails.external_attr = 0o40775 << 16 | 0x10
            zipf.writestr(zi_thumbnails, '')
            
            zi_media = zipfile.ZipInfo('media/') 
            zi_media.external_attr = 0o40775 << 16 | 0x10
            zipf.writestr(zi_media, '')

            add_folder_to_zip(MEDIA)

        progress.close()
        xbmcgui.Dialog().ok('Backup Complete', f'Backup done. Saved at:\n{str(zip_path)}\n\nPress OK to return.')

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

    if not confirm_action('Confirm Restore', 'Overwrite files? Kodi will close after.'):
        return

    try:
        for folder in [ADDONS, USERDATA, MEDIA]:
             if folder.exists():
                 shutil.rmtree(str(folder), ignore_errors=True)
                 folder.mkdir(exist_ok=True)

        zip_path = Path(zip_path_str)
        with zipfile.ZipFile(str(zip_path), 'r') as zipf:
            files = zipf.namelist()
            total = len(files)
            progress = xbmcgui.DialogProgress()
            progress.create('Restore', 'Restoring...')
            
            for idx, member in enumerate(files):
                if progress.iscanceled():
                    notify('Restore', 'Cancelled.')
                    return
                
                target_path = MEDIA / member[6:] if member.startswith('media/') else HOME / member
                
                if member.endswith('/'):
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with zipf.open(member) as s, open(str(target_path), 'wb') as d:
                        shutil.copyfileobj(s, d)
                
                progress.update(int((idx / total) * 100), f'Restoring: {member}')

        progress.close()
        xbmcgui.Dialog().ok('Restore Complete', 'Restore completed successfully.\n\nPress OK to force close Kodi and apply changes.')
        xbmc.executebuiltin('Quit')

    except Exception as e:
        log_error('Restore', e)

def reset_kodi():
    show_description('Fresh Start', DESCRIPTIONS['Fresh Start'])
    if not confirm_action('Fresh Start', 'Are you SURE? This wipes everything.'): return

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

        # Display dialog after wiping data
        xbmcgui.Dialog().ok('All Data has been wiped', 'Press OK to force close Kodi.')
        
        # Force close Kodi
        xbmc.executebuiltin('Quit')
    except Exception as e:
        log_error('Fresh Start', e)

def upload_log():
    log_file = LOGPATH / 'kodi.log'
    if not log_file.exists():
        notify('Error', 'No log file found.')
        return

    if not confirm_action('Upload Log', 'Upload kodi.log to a public pastebin?'):
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
            xbmcgui.Dialog().textviewer('Log Uploaded', f"Log URL:\n{url}")
        else:
            notify('Upload Failed', 'Could not parse response.')

    except Exception as e:
        log_error('Log Upload', e)

def log_options():
    log_menu = ['Read', 'Export', 'Upload', 'Clear']
    idx = xbmcgui.Dialog().select('Log Options', log_menu)
    if idx == -1: return

    log_file = LOGPATH / 'kodi.log'
    
    if idx == 0:
        if log_file.exists():
            with open(str(log_file), 'r', encoding='utf-8', errors='ignore') as f:
                xbmcgui.Dialog().textviewer('Kodi Log', f.read())
    elif idx == 1:
        dest = xbmcgui.Dialog().browse(3, 'Export Location', 'files')
        if dest:
            try:
                shutil.copy(str(log_file), os.path.join(dest, 'kodi.log'))
                notify('Success', 'Log exported.')
            except Exception as e: log_error('Export Log', e)
    elif idx == 2:
        upload_log()
    elif idx == 3:
        try:
            open(str(log_file), 'w').close()
            notify('Success', 'Log cleared.')
        except Exception as e: log_error('Clear Log', e)

def reload_ui():
    xbmc.executebuiltin('ReloadSkin()')

def refresh_repos():
    notify('Lazy Maintenance', 'Scanning repos...')
    xbmc.executebuiltin('UpdateAddonRepos')
    time.sleep(3)
    notify('Lazy Maintenance', 'Scan done.')
    reload_ui()

def show_help():
    text = "[B]Lazy Maintenance Help[/B]\n\n"
    for title, desc in DESCRIPTIONS.items():
        if title not in ["Info", "Settings"]:
            text += f"[B]{title}:[/B]\n{desc}\n\n"
    xbmcgui.Dialog().textviewer('Info', text)

def open_settings():
    xbmc.executebuiltin(f'Addon.OpenSettings({ADDON_ID})')

# --- Main Entry ---

def main():
    idx = xbmcgui.Dialog().select('Maintenance Menu', OPTIONS)
    if idx == -1: return

    sel = OPTIONS[idx]
    
    if sel == 'Info':
        show_help()
    elif sel == 'Settings':
        open_settings()
    elif sel == 'Cleaner Options':
        cleaner_options()
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
