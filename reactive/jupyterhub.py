import os
import os.path
import subprocess

from charms.reactive import (
    only_once,
    remove_state,
    set_state,
    when,
    when_file_changed,
    when_not,
)
from charmhelpers.core import (
    hookenv,
    unitdata,
    templating
)

runtime_dir = '/srv/jupyterhub'
config_dir = '/etc/jupyterhub'
config_file = os.path.join(config_dir, 'jupyterhub_config.py')
unitdata_kv = unitdata.kv()

@when_not('jupyterhub.installed')
def install_jupyterhub():
    subprocess.check_call(['npm', 'install', '-g', 'configurable-http-proxy'])
    templating.render('jupyterhub.service', '/etc/systemd/system/jupyterhub.service', {})

    # Generate the cookie secret. This file must be readable only by the
    # user running jupyterhub.
    #
    # TODO(axw) chown to jupyterhub user, when we start running jupyterhub
    # as a non-root user.
    if not os.path.exists(runtime_dir):
        os.makedirs(runtime_dir, 0o755)
    cookie_secret_path = os.path.join(runtime_dir, 'cookie_secret')
    fd = os.open(cookie_secret_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd) as f:
        subprocess.check_call(['openssl', 'rand', '-base64', '2048'], stdout=f)

    # Generate a proxy auth token. We'll expose this as relation data, so
    # applications can connect to the proxy.
    proxy_auth_token = subprocess.Popen(
        ['openssl', 'rand', '-hex', '32'],
        stdout=subprocess.PIPE,
    ).communicate()[0].decode('utf-8').rstrip()
    unitdata_kv.set('proxy_auth_token', proxy_auth_token)

    set_state('jupyterhub.installed')


@when('jupyterhub.installed')
@when_not('authenticator.available')
def awaiting_authenticator():
    hookenv.status_set('waiting', 'Waiting for a JupyterHub authenticator')


@when('jupyterhub.installed')
@when('authenticator.available')
@when_not('spawner.available')
def awaiting_spawner(authenticator):
    hookenv.status_set('waiting', 'Waiting for a JupyterHub spawner')


@when('config.changed')
def set_config_changed():
    """
    When config changes, we just record the fact in state. This is needed
    because the config.changed state is cleared when the hook completes,
    and we don't want to react to the config change until we have all of
    the required relations.
    """
    set_state('jupyterhub.config.changed')


@when('spawner.available')
@when('authenticator.available')
@when('jupyterhub.config.changed')
def config_changed(authenticator, spawner):
    """
    When config changes, and we have all of the
    required relations, (re)write the config file.
    """
    config = hookenv.config()
    port = config['port']
    authenticator_class, authenticator_config = authenticator.config()
    spawner_class, spawner_config = spawner.config()
    context = {
      'port':                 port,
      'proxy_auth_token':     unitdata_kv.get('proxy_auth_token'),
      'authenticator_class':  authenticator_class,
      'authenticator_config': authenticator_config,
      'spawner_class':        spawner_class,
      'spawner_config':       spawner_config,
    }
    templating.render('jupyterhub_config.py', config_file, context)
    remove_state('jupyterhub.config.changed')


@when_file_changed(config_file)
def config_file_changed():
    """
    When /etc/jupyterhub/jupyterhub_config.py changes, restart jupyterhub.
    """
    subprocess.check_call(['systemctl', 'restart', 'jupyterhub'])
    hookenv.status_set('active', 'Ready: http://{public_ip}:{port}'.format(
        public_ip=hookenv.unit_public_ip(), port=hookenv.config('port')))


@when('config.changed.port')
def port_changed():
    """
    When the port configuration changes,
    close the old port and open the new
    one.
    """
    config = hookenv.config()
    current_port = config['port']
    previous_port = config.previous('port')
    if previous_port is not None:
        hookenv.close_port(previous_port)
    hookenv.open_port(current_port)

