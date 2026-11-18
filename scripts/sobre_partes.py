"""An envelope's two tars, read by a reader of its own that takes only what RG's sealing writes: tar headers (GNU or
POSIX ustar) of regular files and folders, with at most one GNU long name before a member. Anyone with the public key
can seal one (SECURITY T31): no PAX or global header, link, device, FIFO or sparse member, size outside plain octal or
wrong checksum. Every header is checked before a byte is written beside the destination, renamed onto it when whole.

    python3 -I scripts/sobre_partes.py externo <envelope tar> <dir> <max bytes>        # datos.enc, datos.mac, llave.enc
    python3 -I scripts/sobre_partes.py interno <decrypted tar> <max bytes> [<dir> [<its folder>]]  # sobre.sh open"""
import os
import shutil
import sys
import tempfile

PARTES = ('datos.enc', 'datos.mac', 'llave.enc')
BLOQUE = 512
MAX_CABECERAS = 40_000  # headers in all, long names included: the work folder investigar.yml seals holds a few hundred files
MAX_NOMBRE = 4_096  # bytes of one GNU long name
MAX_NIVELES = 64  # folder levels of one name: makedirs recurses once per level
MAX_PARTE = 255  # bytes of one part of a name (a file system's own limit)
TROZO = 1 << 20  # bytes copied at a time: a file of 4 GB never sits in memory whole
CERO = b'\0' * BLOQUE


class Cota(ValueError):
    """An archive this reader does not take."""


def _octal(campo, que):
    t = campo.rstrip(b'\0 ').lstrip(b' ')
    if any(c not in b'01234567' for c in t):  # base-256 (GNU, negatives included); empty: int() refuses it
        raise Cota(f'{que} is not a plain octal number')
    return int(t, 8)


def _partes(crudo):
    """The name's plain parts; Cota if absolute, with '..', a part over MAX_PARTE bytes or over MAX_NIVELES parts."""
    n = crudo.decode('utf-8')
    ps = tuple(x for x in n.split('/') if x not in ('', '.'))
    if n.startswith('/') or '..' in ps or len(ps) > MAX_NIVELES or any(len(x.encode()) > MAX_PARTE for x in ps):
        raise Cota(f'a name that is not plain, relative and short: {n[:100]!r}')
    return ps


def cabeceras(src):
    """[(name's parts, 'archivo' | 'carpeta', offset, size)] of the tar at src; Cota for what RG's sealing never writes."""
    out, n, largo = [], 0, None
    with open(src, 'rb') as f:
        while True:
            h = f.read(BLOQUE)  # short or empty at the end of the file: its checksum below is not a number
            if h == CERO:
                return out
            n += 1
            if n > MAX_CABECERAS:
                raise Cota(f'more than {MAX_CABECERAS} headers')
            if _octal(h[148:156], 'a checksum') != sum(h[:148]) + 8 * 32 + sum(h[156:]):
                raise Cota('a header with a wrong checksum')
            tipo, size = h[156:157], _octal(h[124:136], 'a size')
            if tipo == b'L':  # GNU long name: its bytes name the next member
                if largo is not None or size > MAX_NOMBRE:
                    raise Cota('a long name after a long name, or over its cap')
                largo = f.read(size + (-size % BLOQUE))[:size].split(b'\0', 1)[0]
                continue
            if tipo not in (b'0', b'\0', b'5'):
                raise Cota(f'a member of type {tipo!r}: only regular files and folders')
            prefijo = h[345:500].split(b'\0', 1)[0] if h[257:265] == b'ustar\x0000' else b''  # POSIX only; GNU puts times there
            nombre = largo if largo is not None else (prefijo + b'/' if prefijo else b'') + h[:100].split(b'\0', 1)[0]
            largo = None
            if tipo == b'5':
                if size:
                    raise Cota('a folder with a size')
                out.append((_partes(nombre), 'carpeta', None, 0))
                continue
            out.append((_partes(nombre), 'archivo', f.tell(), size))
            f.seek(size + (-size % BLOQUE), 1)


def _copiar(src, offset, size, path):
    with open(src, 'rb') as r, open(path, 'xb') as w:  # 'xb': never over something already there
        r.seek(offset)
        for _ in range(-(-size // TROZO)):  # cabeceras read past these bytes: they are all there
            w.write(r.read(min(TROZO, size)))
            size -= TROZO


def _escribir(src, carpetas, archivos, dst, tmp=None):
    """These folders and files into dst (new, or empty and not a link), first into tmp (the caller's own empty folder
    beside dst, or one made here), renamed onto dst only when whole: a failure leaves dst as it was, nothing beside it."""
    dst = os.path.abspath(dst)  # 'link/' is not a link to islink; its absolute form is
    if os.path.islink(dst) or (os.path.exists(dst) and os.listdir(dst)):
        raise ValueError('the folder to open into is a link or not empty')
    if tmp is None:
        tmp = tempfile.mkdtemp(prefix='.sobre-', dir=os.path.dirname(dst))
    elif os.path.islink(tmp) or os.path.dirname(os.path.abspath(tmp)) != os.path.dirname(dst) or os.listdir(tmp):
        raise ValueError('the folder to write in is a link, not beside the destination or not empty')
    try:
        for partes in carpetas:
            os.mkdir(os.path.join(tmp, *partes))
        for partes, (offset, size) in archivos.items():
            _copiar(src, offset, size, os.path.join(tmp, *partes))
        os.rename(tmp, dst)  # onto a missing or empty folder, at once
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def externo(src, dst, cap):
    """The envelope's three files into dst, each at most cap bytes; ValueError and dst as it was otherwise."""
    ms = cabeceras(src)
    if sorted('/'.join(m[0]) for m in ms) != sorted(PARTES) or any(m[1] != 'archivo' or m[3] > cap for m in ms):
        raise ValueError('not an envelope: exactly its three regular files')
    _escribir(src, (), {m[0]: (m[2], m[3]) for m in ms}, dst)


def plan(ms):
    """(folders, files) every member makes, its parents included; Cota for a file with no name or given twice, a path
    both a file and a folder, or more paths than MAX_CABECERAS, counted as they are built (two adversarial reviews)."""
    archivos, carpetas = {}, set()
    for partes, tipo, offset, size in ms:
        if tipo == 'carpeta':
            carpetas.add(partes)
        elif not partes or partes in archivos:
            raise Cota(f'a file with no name, or given twice: {"/".join(partes)[:100]!r}')
        else:
            archivos[partes] = (offset, size)
        carpetas.update(partes[:k] for k in range(1, len(partes)))
        if len(carpetas) + len(archivos) > MAX_CABECERAS:
            raise Cota(f'more than {MAX_CABECERAS} paths')
    if carpetas & archivos.keys():
        raise Cota('a path that is both a file and a folder')
    return sorted(carpetas - {()}, key=len), archivos


def interno(src, cap, dst=None, tmp=None):
    """ValueError unless this reader takes the tar, its files at most cap bytes in all; then, with dst, _escribir."""
    ms = cabeceras(src)
    if sum(m[3] for m in ms) > cap:
        raise ValueError(f'the envelope opens to more than {cap} bytes')
    carpetas, archivos = plan(ms)
    if dst is not None:
        _escribir(src, carpetas, archivos, dst, tmp)


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'externo':
            externo(sys.argv[2], sys.argv[3], int(sys.argv[4]))
        else:
            interno(sys.argv[2], int(sys.argv[3]), *sys.argv[4:6])
    except (ValueError, OSError) as e:
        sys.exit(f'sobre_partes: {e}')
