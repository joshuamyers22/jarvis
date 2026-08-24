"""Jupyter Lab server config.

Bound to loopback on purpose. Reach it with an SSH tunnel:

    ssh -N -L 8888:localhost:8888 you@notebook-node

Never expose this port publicly, token or not.
"""

c = get_config()  # type: ignore[name-defined]  # noqa: F821

c.ServerApp.ip = "127.0.0.1"
c.ServerApp.port = 8888
c.ServerApp.open_browser = False
c.ServerApp.root_dir = "/data/notebooks"
c.ServerApp.allow_remote_access = False

# The SSH tunnel is the authentication boundary. A token here adds a copy-paste
# step without adding security: anything that can reach this port already has
# shell on the box.
c.IdentityProvider.token = ""
c.ServerApp.password = ""

c.MappingKernelManager.cull_idle_timeout = 3600
c.MappingKernelManager.cull_interval = 300
c.MappingKernelManager.cull_connected = False
