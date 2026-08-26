"""Jupyter Lab server config.

The server listens on the container interface so Docker port forwarding works.
The host-side Compose/Docker port must remain bound to loopback. Reach a remote
host with an SSH tunnel:

    ssh -N -L 8888:localhost:8888 you@notebook-node

Never expose this port publicly, token or not.
"""

c = get_config()  # type: ignore[name-defined]  # noqa: F821

c.ServerApp.ip = "0.0.0.0"
c.ServerApp.port = 8888
c.ServerApp.open_browser = False
c.ServerApp.root_dir = "/data/notebooks"
c.ServerApp.allow_remote_access = False

# The Docker host's loopback bind (and SSH tunnel when deployed) is the
# authentication boundary. Never publish this container port on 0.0.0.0.
c.IdentityProvider.token = ""
c.ServerApp.password = ""

c.MappingKernelManager.cull_idle_timeout = 3600
c.MappingKernelManager.cull_interval = 300
c.MappingKernelManager.cull_connected = False
