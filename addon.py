import xbmcgui
import xbmcplugin
import xbmc
import xbmcvfs
import shutil
import zipfile
import time
import os
import sys
import urllib.request
import urllib.parse
import json
from pathlib import Path

# Import constants and paths
from constants import (
    ADDON, ADDON_ID, HOME, ADDONS, USERDATA, TEMP, THUMBNAILS, 
    PACKAGES, LOGPATH, MEDIA, DATABASE, DESCRIPTIONS
)

# --- Helper Functions ---

def notify(title, message, duration=5000):
    xbmcgui.Dialog().notification(title, message, time=duration)

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

CHUNK_SIZE = 8 * 1024 * 1024  # 8MB

def vfs_copy_file(source_local_path, dest_vfs_path):
    """Copy a local file to any VFS destination (SMB/FTP/local) in chunks."""
    try:
        vfs_file = xbmcvfs.File(dest_vfs_path, 'w')
        with open(str(source_local_path), 'rb') as src:
            while True:
                chunk = src.read(CHUNK_SIZE)
                if not chunk:
                    break
                vfs_file.write(bytearray(chunk))
        vfs_file.close()
        return True
    except Exception as e:
        xbmc.log(f"LazyMaintenance: VFS copy failed: {e}", xbmc.LOGERROR)
        return False

def vfs_download_file(source_vfs_path, dest_local_path):
    """Download a VFS file (SMB/FTP/etc) to a local path in chunks."""
    try:
        vfs_file = xbmcvfs.File(source_vfs_path, 'r')
        with open(str(dest_local_path), 'wb') as dst:
            while True:
                chunk = vfs_file.readBytes(CHUNK_SIZE)
                if not chunk:
                    break
                dst.write(chunk)
        vfs_file.close()
        return True
    except Exception as e:
        xbmc.log(f"LazyMaintenance: VFS download failed: {e}", xbmc.LOGERROR)
        return False

def force_close_kodi():
    """
    Aggressively kills Kodi to prevent it from saving current RAM settings
    over the files we just restored (crucial for guisettings.xml).
    os._exit(1) is the universal fallback on all platforms - calling it from
    inside Kodi's embedded Python crashes the runtime and takes Kodi down with it.
    """
    import signal

    xbmc.log("LazyMaintenance: Initiating Force Close sequence...", xbmc.LOGINFO)

    try:
        if xbmc.getCondVisibility('system.platform.windows'):
            # Windows needs explicit taskkill - os._exit alone is less reliable here
            os.system('taskkill /F /IM kodi.exe /T')

        elif xbmc.getCondVisibility('system.platform.android'):
            # Android: try am force-stop as best effort, os._exit handles the rest
            os.system('am force-stop org.xbmc.kodi 2>/dev/null; '
                      'am force-stop tv.kodi.kodi 2>/dev/null; '
                      'am force-stop tv.kodi.app 2>/dev/null')

        else:
            # Linux / macOS / LibreELEC / Flatpak
            # os.getpid() returns the Kodi process PID because Python runs
            # embedded inside Kodi. Killing ourselves = killing Kodi cleanly.
            # (getppid() was wrong — that kills Kodi's parent, e.g. systemd)
            os.kill(os.getpid(), signal.SIGKILL)

    except Exception as e:
        xbmc.log(f"LazyMaintenance: System kill failed: {e}", xbmc.LOGDEBUG)

    # Universal fallback - crashes the embedded Python runtime which takes Kodi
    # down with it on all platforms including Android and Flatpak
    os._exit(1)

def safe_delete_item(item_path):
    """
    Tries to delete a file or folder. 
    If locked (Windows/Kodi in use), it skips it without crashing.
    """
    try:
        if item_path.is_dir():
            shutil.rmtree(str(item_path), ignore_errors=True)
        else:
            item_path.unlink()
    except Exception:
        # File is likely locked by the OS, skip it
        xbmc.log(f"LazyMaintenance: Skipped locked file {item_path.name}", xbmc.LOGDEBUG)
        pass

def safe_wipe_folder(folder_path, exclude_list=None):
    """
    Iterates through a folder and deletes items one by one.
    This ensures that one locked file doesn't stop the whole process.
    """
    if exclude_list is None:
        exclude_list = []
    if not folder_path.exists(): return
    
    for item in folder_path.iterdir():
        if item.name in exclude_list: continue
        safe_delete_item(item)

# --- Core Logic ---

def trim_folder(path_obj, max_size_mb):
    """Trims folder to target size in MB."""
    if not path_obj.exists():
        return

    max_size_bytes = max_size_mb * 1024 * 1024
    current_size = get_folder_size(path_obj)
    
    if current_size <= max_size_bytes:
        return

    file_list = []
    for root, dirs, found_files in os.walk(str(path_obj)):
        for f in found_files:
            if f == 'kodi.log': continue
            fp = Path(root) / f
            try:
                stat = fp.stat()
                file_list.append((stat.st_mtime, stat.st_size, fp))
            except Exception as e:
                xbmc.log(f"Error reading file stats {fp}: {e}", xbmc.LOGDEBUG)

    file_list.sort(key=lambda x: x[0])

    for mtime, size, fp in file_list:
        try:
            fp.unlink()
            current_size -= size
            if current_size <= max_size_bytes:
                break
        except Exception:
            pass

    for root, dirs, files in os.walk(str(path_obj), topdown=False):
        for d in dirs:
            dp = Path(root) / d
            try:
                if not any(dp.iterdir()):
                    dp.rmdir()
            except Exception:
                pass

def clear_folder(path_obj):
    if not path_obj.exists(): return
    # Use the robust safe wipe function
    safe_wipe_folder(path_obj, exclude_list=['kodi.log'])

# --- Actions ---

def hard_clean():
    show_description('Hard Clean', DESCRIPTIONS['Hard Clean'])
    
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
            # Wrapped in try-except so Windows doesn't crash if locked
            try:
                textures_db.unlink()
            except Exception:
                xbmc.log("LazyMaintenance: Textures13.db is locked. Skipping.", xbmc.LOGINFO)

        progress.update(100, 'Complete!')
        progress.close()

        xbmcgui.Dialog().ok('Hard Clean Complete', 
                            'Hard Clean completed.\n\n'
                            'Press OK to force close Kodi.')
        force_close_kodi()

    except Exception as e:
        if 'progress' in locals(): progress.close()
        log_error('Hard Clean', e)

def clean(silent=False):
    """Auto clean on startup"""
    try:
        try:
            auto_limit = int(ADDON.getSetting('auto_clean_size'))
        except (ValueError, TypeError):
            auto_limit = 50

        clear_folder(TEMP)
        clear_folder(PACKAGES)
        if auto_limit > 0:
            trim_folder(THUMBNAILS, auto_limit)

        if silent:
            msg = 'Auto clean done.'
        else:
            msg = 'Cleaning completed.'
        notify('Lazy Maintenance', msg)

    except Exception as e:
        log_error('Auto Cleaning', e)

def backup():
    show_description('Backup', DESCRIPTIONS['Backup'])
    
    while True:
        kb = xbmc.Keyboard('', 'Enter backup name (leave empty for timestamp)')
        kb.doModal()
        if not kb.isConfirmed(): return 
        
        zip_name = kb.getText().strip()
        if not zip_name:
            zip_name = f"kodi_backup_{time.strftime('%Y-%m-%d_%H-%M-%S')}"
        if not zip_name.endswith('.zip'):
            zip_name += '.zip'
        
        dest_dir_str = xbmcgui.Dialog().browse(0, 'Select backup location', 'files')
        if not dest_dir_str:
            notify('Lazy Maintenance', 'Backup cancelled.')
            return
        
        dest_path = dest_dir_str + zip_name if dest_dir_str.endswith('/') or dest_dir_str.endswith('\\') else dest_dir_str + '/' + zip_name

        if xbmcvfs.exists(dest_path):
            if not confirm_action('File Exists', 
                                  f'[B]{zip_name}[/B] already exists.\n\n'
                                  'Do you want to overwrite it?'):
                continue 
        
        break

    try:
        progress = xbmcgui.DialogProgress()
        progress.create('Backup', 'Calculating files...')
        
        def _count_backup_files(folder_path, exclude_db=False):
            """Count files respecting the same exclusions as add_folder_to_zip."""
            count = 0
            for root, dirs, files_list in os.walk(str(folder_path)):
                if folder_path == USERDATA and 'Thumbnails' in dirs: dirs.remove('Thumbnails')
                if folder_path == ADDONS and 'packages' in dirs: dirs.remove('packages')
                if folder_path == ADDONS and 'temp' in dirs: dirs.remove('temp')
                if '.git' in dirs: dirs.remove('.git')
                if '__pycache__' in dirs: dirs.remove('__pycache__')
                for f in files_list:
                    if exclude_db and f.lower().startswith('textures') and f.lower().endswith('.db'):
                        continue
                    count += 1
            return count

        total_items = _count_backup_files(ADDONS) + \
                      _count_backup_files(USERDATA, exclude_db=True) + \
                      _count_backup_files(MEDIA)
        
        if total_items == 0: total_items = 1 
        current = 0

        # Write zip to a local temp file first, then copy to destination (supports FTP/SMB)
        temp_zip = str(TEMP / zip_name)
        TEMP.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            
            def add_folder_to_zip(folder_path, exclude_db=False):
                nonlocal current
                for root, dirs, files in os.walk(str(folder_path)):
                    if folder_path == USERDATA and 'Thumbnails' in dirs: dirs.remove('Thumbnails')
                    if folder_path == ADDONS and 'packages' in dirs: dirs.remove('packages')
                    if folder_path == ADDONS and 'temp' in dirs: dirs.remove('temp')
                    if '.git' in dirs: dirs.remove('.git')
                    if '__pycache__' in dirs: dirs.remove('__pycache__')
                    
                    for file in files:
                        if exclude_db and file.lower().startswith('textures') and file.lower().endswith('.db'):
                            continue

                        full_path = Path(root) / file
                        arcname = get_zip_arcname(full_path, HOME)
                        try:
                            zipf.write(str(full_path), arcname)
                        except Exception: pass
                        current += 1
                        pct = int(current * 100 / total_items)
                        progress.update(pct, f'Backing up: {file}')
                        if progress.iscanceled(): raise KeyboardInterrupt("Cancelled")

            add_folder_to_zip(ADDONS)
            add_folder_to_zip(USERDATA, exclude_db=True)
            
            zi_thumbnails = zipfile.ZipInfo('userdata/Thumbnails/')
            zi_thumbnails.external_attr = 0o40775 << 16 | 0x10
            zipf.writestr(zi_thumbnails, '')
            zi_media = zipfile.ZipInfo('media/') 
            zi_media.external_attr = 0o40775 << 16 | 0x10
            zipf.writestr(zi_media, '')
            add_folder_to_zip(MEDIA)

        progress.update(99, 'Copying to destination...')
        success = vfs_copy_file(temp_zip, dest_path)
        
        # Clean up temp file
        try:
            os.remove(temp_zip)
        except Exception:
            pass

        progress.close()
        
        if success:
            xbmcgui.Dialog().ok('Backup Complete', f'Backup created:\n{dest_path}')
        else:
            xbmcgui.Dialog().ok('Backup Failed', 'Could not copy backup to destination.\nCheck path and permissions.')

    except KeyboardInterrupt:
        progress.close()
        try:
            os.remove(temp_zip)
        except Exception:
            pass
        notify('Backup', 'Cancelled by user.')
    except Exception as e:
        if 'progress' in locals(): progress.close()
        try:
            os.remove(temp_zip)
        except Exception:
            pass
        log_error('Backup', e)

def restore():
    show_description('Restore', DESCRIPTIONS['Restore'])
    
    while True:
        zip_path_str = xbmcgui.Dialog().browse(1, 'Select backup ZIP', 'files', '.zip')
        if not zip_path_str: return

        if not confirm_action('Confirm Restore', 
                              '[COLOR red][B]DANGER: This will overwrite everything![/B][/COLOR]\n\n'
                              'Your current addons, settings, and data will be deleted.\n'
                              '[B]Proceed?[/B]'):
            continue
        break

    try:
        progress = xbmcgui.DialogProgress()
        progress.create('Restore', 'Preparing...')

        #Download remote ZIP to local temp via VFS (handles SMB/NFS/FTP)
        local_zip = str(TEMP / 'restore_temp.zip')
        TEMP.mkdir(parents=True, exist_ok=True)

        progress.update(5, 'Downloading backup to temp...')
        if not vfs_download_file(zip_path_str, local_zip):
            progress.close()
            xbmcgui.Dialog().ok('Restore Failed', 'Could not read the backup file.\nCheck the path and try again.')
            return

        #Extract to staging directory first so cancel is safe
        staging_dir = TEMP / 'restore_staging'
        if staging_dir.exists():
            shutil.rmtree(str(staging_dir), ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        progress.update(10, 'Extracting backup (please wait)...')

        with zipfile.ZipFile(local_zip, 'r') as zipf:
            progress.update(10, 'Verifying backup integrity...')
            bad_file = zipf.testzip()
            if bad_file is not None:
                progress.close()
                shutil.rmtree(str(staging_dir), ignore_errors=True)
                try: os.remove(local_zip)
                except Exception: pass
                xbmcgui.Dialog().ok(
                    'Restore Cancelled',
                    '[COLOR red][B]Backup is corrupted![/B][/COLOR]\n\n'
                    f'Failed integrity check on:\n[B]{bad_file}[/B]\n\n'
                    'Restore has been cancelled. No changes were made.')
                return

            members = zipf.namelist()
            total = len(members)
            for idx, member in enumerate(members):
                if progress.iscanceled():
                    progress.close()
                    shutil.rmtree(str(staging_dir), ignore_errors=True)
                    try: os.remove(local_zip)
                    except Exception: pass
                    notify('Restore', 'Cancelled. No changes were made.')
                    return

                if member.startswith('media/'):
                    target_path = staging_dir / 'media' / member[6:]
                else:
                    target_path = staging_dir / member

                try:
                    if member.endswith('/'):
                        target_path.mkdir(parents=True, exist_ok=True)
                    else:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        with zipf.open(member) as s, open(str(target_path), 'wb') as d:
                            shutil.copyfileobj(s, d)
                except Exception: pass
                progress.update(10 + int((idx / total) * 60), f'Extracting: {member}')

        # Extraction complete — now wipe and move
        progress.update(75, 'Applying restore (do NOT interrupt)...')

        folders_to_wipe = [ADDONS, USERDATA, MEDIA]
        for i, folder in enumerate(folders_to_wipe):
            progress.update(75 + int(i * 5), f'Wiping: {folder.name}')
            safe_wipe_folder(folder)

        progress.update(90, 'Moving restored files into place...')

        # Map staging folder names to their real destinations
        staging_map = {
            'addons':   ADDONS,
            'userdata': USERDATA,
            'media':    MEDIA,
        }

        move_errors = []

        def _safe_move(src, dst):
            """Move src to dst, removing any existing dst first to avoid
            shutil.move's 'move-into' behaviour when dst already exists."""
            try:
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(str(dst))
                    else:
                        dst.unlink()
                shutil.move(str(src), str(dst))
            except Exception as ex:
                err = f'{src.name}: {ex}'
                move_errors.append(err)
                xbmc.log(f'LazyMaintenance: Move failed {src} -> {dst}: {ex}', xbmc.LOGERROR)

        for item in staging_dir.iterdir():
            target_root = staging_map.get(item.name)
            if target_root is None:
                # Unknown top-level item — move it directly under HOME
                target_root = HOME
                _safe_move(item, HOME / item.name)
                continue

            if item.is_dir():
                target_root.mkdir(parents=True, exist_ok=True)
                for sub in item.iterdir():
                    _safe_move(sub, target_root / sub.name)
            else:
                _safe_move(item, target_root / item.name)

        shutil.rmtree(str(staging_dir), ignore_errors=True)
        try: os.remove(local_zip)
        except Exception: pass

        progress.close()

        if move_errors:
            error_summary = '\n'.join(move_errors[:8])
            if len(move_errors) > 8:
                error_summary += f'\n...and {len(move_errors) - 8} more (see kodi.log)'
            xbmcgui.Dialog().ok(
                'Restore — Partial Failure',
                f'[COLOR orange]Some files could not be moved:[/COLOR]\n\n'
                f'{error_summary}\n\n'
                'Check kodi.log for details. Press OK to force close.'
            )
        else:
            xbmcgui.Dialog().ok('Restore Complete', 'Restore completed.\nPress OK to force close Kodi.')

        force_close_kodi()

    except Exception as e:
        staging_dir = TEMP / 'restore_staging'
        if staging_dir.exists():
            shutil.rmtree(str(staging_dir), ignore_errors=True)
        try: os.remove(str(TEMP / 'restore_temp.zip'))
        except Exception: pass
        if 'progress' in locals(): progress.close()
        log_error('Restore', e)

def reset_kodi():
    show_description('Fresh Start', DESCRIPTIONS['Fresh Start'])
    if not confirm_action('Confirm Fresh Start',
                          '[COLOR red][B]Are you absolutely sure?[/B][/COLOR]\n\n'
                          'This will delete all userdata and remove all addons.\n'
                          'Kodi will be reset to a fresh state.'):
        return
    try:
        progress = xbmcgui.DialogProgress()
        progress.create('Fresh Start', 'Wiping data...')

        progress.update(10, "Scanning Userdata...")
        if USERDATA.exists():
            safe_wipe_folder(USERDATA)

        progress.update(50, "Scanning Addons...")
        if ADDONS.exists():
            safe_wipe_folder(ADDONS, exclude_list=[ADDON_ID])

        progress.update(100, "Complete!")
        xbmc.sleep(500)      # Give Skin Time to render
        progress.close()
        xbmc.sleep(300)      # Safety first

        xbmcgui.Dialog().ok(
            'Fresh Start Complete',
            'Fresh Start done – everything has been deleted.\n'
            'Press OK to force close Kodi.'
        )

        force_close_kodi()

    except Exception as e:
        xbmcgui.Dialog().ok('Error', f'Fresh Start failed:\n{e}')

def upload_log():
    log_file = LOGPATH / 'kodi.log'
    if not log_file.exists():
        notify('Error', 'No log file found.')
        return

    if not confirm_action('Upload Log', 'Upload kodi.log to public paste service?'):
        return

    try:
        addon_version = ADDON.getAddonInfo('version')
        user_agent_string = f'Kodi-LazyMaintenance/{addon_version}'
        with open(str(log_file), 'rb') as f: log_data = f.read()

        req = urllib.request.Request(
            'https://paste.kodi.tv/documents', 
            data=log_data,
            headers={'User-Agent': user_agent_string}
        )
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        if 'key' in result:
            url = f"https://paste.kodi.tv/{result['key']}"
            xbmcgui.Dialog().textviewer('Log Uploaded', f"URL: {url}")
        else:
            notify('Upload Failed', 'Could not parse response.')
    except Exception as e:
        log_error('Log Upload', e)

def read_log():
    log_file = LOGPATH / 'kodi.log'
    if not log_file.exists():
        notify('Error', 'No log file found.')
        return
    try:
        with open(str(log_file), 'r', encoding='utf-8', errors='ignore') as f:
            xbmcgui.Dialog().textviewer('Kodi Log', f.read())
    except Exception as e:
        log_error('Read Log', e)

def export_log():
    log_file = LOGPATH / 'kodi.log'
    if not log_file.exists():
        notify('Error', 'No log file found.')
        return
    dest = xbmcgui.Dialog().browse(0, 'Select Export Location', 'files')
    if dest:
        try:
            dest_path = dest + 'kodi.log' if dest.endswith('/') or dest.endswith('\\') else dest + '/kodi.log'
            if vfs_copy_file(str(log_file), dest_path):
                notify('Success', 'Log exported.')
            else:
                notify('Error', 'Failed to export log.')
        except Exception as e: 
            log_error('Export Log', e)

def clear_log():
    log_file = LOGPATH / 'kodi.log'
    if not log_file.exists(): return
    try:
        open(str(log_file), 'w').close()
        notify('Success', 'Log cleared.')
        reload_ui(silent=True)
    except Exception as e: 
        log_error('Clear Log', e)

def reload_ui(silent=False):
    xbmc.executebuiltin('ReloadSkin()')
    if not silent:
        notify('Lazy Maintenance', 'UI Refreshed')

def refresh_repos():
    notify('Lazy Maintenance', 'Scanning repositories...')
    xbmc.executebuiltin('UpdateAddonRepos')
    xbmc.sleep(3000)
    reload_ui(silent=True)
    notify('Lazy Maintenance', 'Repository scan complete.')

def open_settings():
    xbmc.executebuiltin(f'Addon.OpenSettings({ADDON_ID})')

# --- Plugin Routing ---

def build_url(query):
    return sys.argv[0] + '?' + urllib.parse.urlencode(query)

def add_menu_item(label, method, folder=False, icon='DefaultAddonProgram.png', description=""):
    url = build_url({'mode': method})
    item = xbmcgui.ListItem(label)
    item.setArt({'icon': icon, 'thumb': icon})
    item.setInfo('video', {'plot': description})
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=item, isFolder=folder)

def main_menu():
    add_menu_item('Hard Clean', 'hard_clean', description=DESCRIPTIONS['Hard Clean'])
    add_menu_item('Backup / Restore', 'backup_menu', folder=True, description=DESCRIPTIONS['Backup/Restore'])
    add_menu_item('Log Options', 'log_menu', folder=True, description=DESCRIPTIONS['Log Options'])
    add_menu_item('Refresh Options', 'refresh_menu', folder=True, description=DESCRIPTIONS['Refresh Options'])
    add_menu_item('Fresh Start', 'fresh_start', description=DESCRIPTIONS['Fresh Start'])
    add_menu_item('Settings', 'settings', description="Configure addon settings")
    handle = int(sys.argv[1])
    xbmcplugin.setContent(handle, 'files')
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle)

def backup_menu():
    add_menu_item('Backup', 'backup', description=DESCRIPTIONS['Backup'])
    add_menu_item('Restore', 'restore', description=DESCRIPTIONS['Restore'])
    handle = int(sys.argv[1])
    xbmcplugin.setContent(handle, 'files')
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle)

def log_menu():
    add_menu_item('Read Log', 'read_log', description="View current Kodi log")
    add_menu_item('Export Log', 'export_log', description="Save log to file")
    add_menu_item('Upload Log', 'upload_log', description="Upload to paste.kodi.tv")
    add_menu_item('Clear Log', 'clear_log', description="Wipe current log")
    handle = int(sys.argv[1])
    xbmcplugin.setContent(handle, 'files')
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle)

def refresh_menu():
    add_menu_item('Refresh Repos', 'refresh_repos', description="Update all repositories")
    add_menu_item('Refresh UI', 'refresh_ui', description="Reload Skin")
    handle = int(sys.argv[1])
    xbmcplugin.setContent(handle, 'files')
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle)

def router():
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
    mode = params.get('mode')

    if mode is None:
        main_menu()
    elif mode == 'backup_menu':
        backup_menu()
    elif mode == 'log_menu':
        log_menu()
    elif mode == 'refresh_menu':
        refresh_menu()
    
    # Actions
    elif mode == 'hard_clean':
        hard_clean()
    elif mode == 'fresh_start':
        reset_kodi()
    elif mode == 'backup':
        backup()
    elif mode == 'restore':
        restore()
    elif mode == 'settings':
        open_settings()
    
    # Log Actions (Plugin logic automatically keeps you in the menu after these run)
    elif mode == 'read_log':
        read_log()
    elif mode == 'export_log':
        export_log()
    elif mode == 'upload_log':
        upload_log()
    elif mode == 'clear_log':
        clear_log()
        
    # Refresh Actions
    elif mode == 'refresh_repos':
        refresh_repos()
    elif mode == 'refresh_ui':
        reload_ui()

if __name__ == '__main__':
    router()
