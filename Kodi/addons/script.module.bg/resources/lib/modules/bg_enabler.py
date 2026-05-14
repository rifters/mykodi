import xbmc, xbmcaddon


def background():
	fedit = xbmc.translatePath('special://skin/xml/home.xml')
	f = open(fedit,'r')
	filedata = f.read()
	f.close()
	skinbackground = "<include>DefaultBackgroundPattern</include>"
	newdata = filedata.replace("<include>DefaultBackground</include>",skinbackground)
	f = open(fedit,'w')
	f.write(newdata)
	f.close()

def bg_enable():
        background()
        xbmc.executebuiltin('dialog.close(all)')
        xbmc.executebuiltin('ActivateWindow(home)')
        xbmc.executebuiltin('ReloadSkin')

exit
