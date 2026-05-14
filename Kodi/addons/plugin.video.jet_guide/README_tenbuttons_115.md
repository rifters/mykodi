# Jet Guide  Options

This document explains the available options for managing folders and links in Jet Guide, focusing on the following buttons:

- **111: [COLORblue]Search Kodi Addons[/COLOR]**
- **112: [COLORblue]Import Kodi Favourites[/COLOR]**
- **115: [COLORblue]Folders and Links[/COLOR]**

[COLORblue]------------------------------------------------------[/COLOR]

## [COLORblue]Usage Notes[/COLOR]

- Use **[COLORblue]Search Kodi Addons[/COLOR] (111)** to find and add new links from supported addons.
- Use **[COLORblue]Import Kodi Favourites[/COLOR] (112)** to bring your existing Kodi favourites into Jet Guide.
- Manage, organize, and play your links using **[COLORblue]Folders and Links[/COLOR] (115)**.
- The imported links are stored in `[COLORblue]jet_guide_imported.json[/COLOR]` in your addon's profile directory.
- Custom folders are stored in the `[COLORblue]jet_guide_folders[/COLOR]` directory under your addon's data.
- When moving a link to a folder, you can select from existing folders.
- If no folders exist, you will be prompted to create one when saving links elsewhere in the addon.

## Control ID 111: [COLORblue]Search Kodi Addons[/COLOR]

- Allows you to search for channels or streams from supported Kodi addons.
- After searching, you can add found links to your Jet Guide imported list or save them into custom folders for easy access later.

## Control ID 112: [COLORblue]Import Kodi Favourites[/COLOR]

- Imports your existing Kodi favourites (from your Kodi favourites menu) into Jet Guide.
- Imported favourites are added to your Jet Guide imported list, making them available for playback and organization.

## Control ID 115: [COLORblue]Folders and Links[/COLOR]

When you press this button, you can:

1. **[COLORblue]Browse Jet Guide Imported[/COLOR]**  
   - View channels or links that have been imported via Search (111) or Import Favourites (112).
   - For each imported link, you can:
     - **[COLORblue]Play[/COLOR]**: Start playback of the selected link.
     - **[COLORblue]Delete[/COLOR]**: Remove the link from your imported list.
     - **[COLORblue]Move to Folder[/COLOR]**: Move the link into a custom folder for better organization.

2. **[COLORblue]Browse Saved Folders[/COLOR]**  
   - Organize your links into custom folders.
   - Each folder contains a `[COLORblue]links.json[/COLOR]` file with your saved links.
   - You can browse, play, or manage links within these folders.

---


