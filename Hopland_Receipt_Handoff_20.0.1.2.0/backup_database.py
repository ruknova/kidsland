"""Database backup before touching add-on files. Credentials stay in process memory."""
import configparser
import glob
import os
from pathlib import Path
import shutil
import subprocess
import sys

config_path, database, destination = sys.argv[1:4]
config = configparser.ConfigParser(interpolation=None)
with open(config_path, encoding='utf-8-sig') as stream:
    config.read_file(stream)
options = config['options']
candidates = []
pg_path = options.get('pg_path', '').strip()
if pg_path and pg_path.lower() != 'false':
    candidates.append(str(Path(pg_path) / 'pg_dump.exe'))
found = shutil.which('pg_dump')
if found:
    candidates.append(found)
candidates += sorted(glob.glob(r'C:\Program Files\PostgreSQL\*\bin\pg_dump.exe'), reverse=True)
executable = next((p for p in candidates if Path(p).is_file()), None)
if not executable:
    raise SystemExit('pg_dump.exe was not found. Set pg_path in hopland.conf to the PostgreSQL bin folder, then retry. No add-on files have been changed.')
command = [executable, '--format=custom', '--no-password', '--file', destination]
for option, flag in [('db_host','--host'), ('db_port','--port'), ('db_user','--username')]:
    value = options.get(option, '').strip()
    if value and value.lower() != 'false':
        command += [flag, value]
command += [database]
backup_env = dict(os.environ)
password = options.get('db_password', '')
if password and password.lower() != 'false':
    backup_env['PGPASSWORD'] = password
result = subprocess.run(command, env=backup_env, capture_output=True, text=True)
if result.returncode:
    Path(destination).unlink(missing_ok=True)
    raise SystemExit('Database backup failed; no add-on files changed.\n' + result.stderr[-2000:])
if not Path(destination).is_file() or Path(destination).stat().st_size == 0:
    raise SystemExit('Database backup was empty; installation stopped.')
print('Database backup completed.')
