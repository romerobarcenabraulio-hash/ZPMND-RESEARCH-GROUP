"""The extractor as another OS user: what a hostile raw can take over is a process that owns nothing RG trusts.

    sudo -n -u <user> -- timeout -s KILL <s> <python> -m rg.text.isolated <copy of the raw> <max bytes> <max memory>

rg.text.run.extract_all launches it for each raw when RG_EXTRACT_AS names a user (the workflows that read hostile raws
create that user and set it). The parent copies the raw into a scratch folder the user can read and not write, runs
this module from a read-only copy of rg/ in that folder, and reads the one JSON object it prints as data: only the
extraction fields, each of its type, and the raw's sha256 and size from the parent's own hashing, never from here.
The user owns nothing in the workspace, work/, out/, the packet folder or the gate's result and gets no secret (sudo
resets the environment), so a parser exploit cannot write any file RG trusts. It is not a sandbox: while the call lasts
it can read the other raws, signal the other workers, misreport text and use the network (SECURITY T12; GPT REVISEs of
#56 and #60).
"""
import json
import sys

from .run import _limit_memory, read_and_extract


def main(argv=None):
    path, max_bytes, max_memory = argv if argv is not None else sys.argv[1:]
    _limit_memory(int(max_memory))  # before the first byte of the raw is read
    sys.stdout.write(json.dumps(read_and_extract(path, int(max_bytes)), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
