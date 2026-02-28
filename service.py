import xbmc

# Wait for Kodi to fully initialize before running auto clean
monitor = xbmc.Monitor()

if not monitor.waitForAbort(5):
    import addon
    addon.clean(silent=True)
