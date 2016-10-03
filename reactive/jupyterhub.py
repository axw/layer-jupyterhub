import subprocess
import os.path

from charms.reactive import when, when_not, set_state
from charmhelpers.core import hookenv, templating

runtime_dir = '/srv/jupyterhub'
config_dir = '/etc/jupyterhub'

@when_not('jupyterhub.installed')
def install_jupyterhub():
    subprocess.check_call(['npm', 'install', '-g', 'configurable-http-proxy'])
    templating.render('jupyterhub.service', '/etc/systemd/system/jupyterhub.service', {})

    # Generate the cookie secret.
    # TODO(axw) chown to jupyterhub user, when we start running
    # jupyterhub as non-root user.
    if not os.path.exists(runtime_dir):
        os.makedirs(runtime_dir, 0o755)
    with open(os.path.join(runtime_dir, 'cookie_secret'), 'w', 0o600) as f:
        subprocess.check_call(['openssl', 'rand', '-base64', '2048'], stdout=f)

    # TODO(axw) generate proxy auth token. We'll want to expose
    # this as relation data, so applications can connect to the
    # proxy. For now, the hub generates the token itself.

    set_state('jupyterhub.installed')


@when_not('spawner.available')
@when('jupyterhub.installed')
def awaiting_spawner():
    hookenv.status_set('waiting', 'Waiting for a JupyterHub spawner')


@when('config.changed')
@when('spawner.available')
def config_changed(spawner):
    config = hookenv.config()
    port = config['port']
    spawner_class, spawner_config = spawner.config()
    context = {
      'port':           port,
      'spawner_class':  spawner_class,
      'spawner_config': spawner_config,
    }
    templating.render(
        'jupyterhub_config.py',
        os.path.join(config_dir, 'jupyterhub_config.py'),
        context,
    )
    subprocess.check_call(['systemctl', 'restart', 'jupyterhub'])
    hookenv.status_set('active', 'Ready: http://{public_ip}:{port}'.format(
        public_ip=hookenv.unit_public_ip(), **context))


@when('config.changed.port')
def port_changed():
    config = hookenv.config()
    current_port = config['port']
    previous_port = config.previous('port')
    if previous_port is not None:
        hookenv.close_port(previous_port)
    hookenv.open_port(current_port)

