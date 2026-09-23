"""Load compose-owned secret file, then replace this process with the service."""
import os
import sys
from pathlib import Path
os.environ['JWT_SECRET']=Path('/state/jwt').read_text()
os.execvp(sys.argv[1], sys.argv[1:])
