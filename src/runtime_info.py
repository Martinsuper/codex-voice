import json
import sqlite3
import sys
print(json.dumps({"pythonVersion":sys.version.split()[0], "executable":sys.executable, "prefix":sys.prefix, "path":sys.path, "sqliteVersion":sqlite3.sqlite_version}))
