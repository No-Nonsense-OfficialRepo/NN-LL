# Host game files

Put each game's host copy in a folder named for its manifest id, such as
`game_files/bfbc2/`. LAN Tool serves these folders for signed, resumable sync.
Clients download the folder contents into the manifest's `install_dir`.

Keep the manifest in `games/`; it is launcher configuration and is not copied
into the game installation.
