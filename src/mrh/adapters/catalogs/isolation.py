"""Shared macOS isolation policy for public catalog acquisition."""
import json
from pathlib import Path


def isolation_profile(root, executable):
    """Accepted E12R restrictions, scoped to this fresh lifecycle/executable."""
    quote=lambda p:json.dumps(str(p))
    reads=[root,'/System/Library','/System/Applications','/System/DriverKit','/usr','/bin','/sbin',
           '/opt/homebrew/Cellar','/opt/homebrew/opt',Path(executable).parent,'/dev/null','/dev/urandom']
    ancestors=sorted({str(parent) for path in reads for parent in Path(path).parents})
    return '\n'.join(['(version 1)','(deny default)','(allow process*)','(allow sysctl-read)',
        '(allow signal)','(allow file-read-data (literal "/"))',
        '(allow file-read-metadata '+' '.join('(literal '+quote(p)+')' for p in ancestors)+')',
        '(allow file-read* '+' '.join('(subpath '+quote(p)+')' for p in reads)+')',
        '(allow file-write* (subpath '+quote(root)+') (literal "/dev/null"))',
        '(deny file-read* (subpath "/Users") (subpath "/System/Volumes/Data/Users"))',
        '(deny file-read* (subpath '+quote(root/'private-canary')+'))',
        '(deny process-exec (literal "/usr/bin/security"))','(deny mach-lookup)','(deny network*)'])+'\n'
