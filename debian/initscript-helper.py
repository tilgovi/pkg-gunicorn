import os
import re
import imp
import sys
import glob
import subprocess

re_ignore = re.compile(r'(^_|\.(dpkg-(old|dist|new|tmp)|example)$)')

def main(conf_dir, pid_dir, log_dir, action):
    files = glob.glob(os.path.join(conf_dir, '*'))

    if not os.path.exists(pid_dir):
        os.makedirs(pid_dir)

    for filename in sorted(files):
        if re_ignore.search(filename):
            continue

        if sys.version_info > (2, 6):
            # We are using a version that understands PYTHONDONTWRITEBYTECODE
            # so it is safe to use imp.load_source here - otherwise we create
            # "pyc"-like files in /etc/gunicorn.d which we then try and parse.
            CONFIG = imp.load_source(filename, filename).CONFIG
        else:
            # Update Python path so configurations can extend each other.
            sys.path.append(conf_dir)
            exec open(filename).read()

        config = Config(filename, pid_dir, log_dir, CONFIG)

        if action in ('start', 'stop', 'reload'):
            config.print_name()
            getattr(config, action)()
        else:
            raise ValueError("Invalid action: %s" % action)

    # Kill any renaming pidfiles to prevent the case where we remove or
    # renaming a configuration and it doesn't get stopped or restarted.
    if action == 'stop':
        for pidfile in glob.glob(os.path.join(pid_dir, '*.pid')):
            if subprocess.call((
                'start-stop-daemon',
                '--stop',
                '--oknodo',
                '--retry', '1',
                '--quiet',
                '--pidfile', pidfile,
            )):
                # We killed the process
                os.unlink(pidfile)

    return 0

class Config(dict):
    def __init__(self, filename, pid_dir, log_dir, data):
        self.pid_dir = pid_dir
        self.log_dir = log_dir
        self.filename = filename

        data['args'] = list(data.get('args', []))
        data.setdefault('mode', 'wsgi')
        data.setdefault('user', 'www-data')
        data.setdefault('group', 'www-data')
        data.setdefault('environment', {})
        data.setdefault('working_dir', '/')
        data.setdefault('python', '/usr/bin/python')

        self.update(data)

        assert self['mode'] in ('wsgi', 'django', 'paster')

    def print_name(self):
        sys.stdout.write(" [%s]" % self.basename())
        sys.stdout.flush()

    def basename(self):
        return os.path.basename(self.filename)

    def pidfile(self):
        return os.path.join(self.pid_dir, '%s.pid' % self.basename())

    def logfile(self):
        return os.path.join(self.log_dir, '%s.log' % self.basename())

    def start(self):
        daemon = {
            'wsgi': '/usr/bin/gunicorn',
            'django': '/usr/bin/gunicorn_django',
            'paster': '/usr/bin/gunicorn_paster',
        }[self['mode']]

        args = [
            'start-stop-daemon',
            '--start',
            '--oknodo',
            '--quiet',
            '--chdir', self['working_dir'],
            '--pidfile', self.pidfile(),
            '--exec', self['python'], '--', daemon,
        ]

        gunicorn_args = [
            '--pid', self.pidfile(),
            '--name', self.basename(),
            '--user', self['user'],
            '--group', self['group'],
            '--daemon',
            '--log-file', self.logfile(),
        ]

        env = os.environ.copy()
        env.update(self['environment'])

        subprocess.check_call(args + gunicorn_args + self['args'], env=env)

    def stop(self):
        subprocess.check_call((
            'start-stop-daemon',
            '--stop',
            '--oknodo',
            '--quiet',
            '--retry', '10',
            '--pidfile', self.pidfile(),
        ))

    def reload(self):
        subprocess.check_call((
            'start-stop-daemon',
            '--stop',
            '--signal', 'HUP',
            '--oknodo',
            '--quiet',
            '--retry', '10',
            '--pidfile', self.pidfile(),
        ))

if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
