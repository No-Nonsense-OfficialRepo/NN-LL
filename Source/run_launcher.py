# Development entry point: the role comes from --host / --client, else the exe name, else Client.
# Releases use run_host.py and run_client.py, which pin the role explicitly.
# The UI, downloads and games run with the user's normal permissions.
# Individual VLA operations use the allow-listed --lan-admin-action child.
if __name__ == "__main__":
    from lantool.entry import run
    run()
