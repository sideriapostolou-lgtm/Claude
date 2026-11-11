"""The bot's own wallet: made by the bot, kept by the bot, seen by nobody (``BOT_WALLET_MODE=generated``) (owner: O5).

The owner never handles a private key: they fund the bot from Phantom with Send (the page shows the address) and
take the money back with ``WITHDRAW_TO`` (:mod:`nightcrawler.withdraw`). HARD RULE: no human or AI ever sees,
handles, logs or transmits this key. Only the PUBLIC address leaves this module (logs, one ``wallet_created``
receipt, kv ``wallet.pubkey`` and ``keystore.pubkey``, the page); the secret stays in the key file and in a
:class:`~nightcrawler.broker.wallet.Wallet` (a :class:`~nightcrawler.config.Secret` that prints as ``***``,
refuses to be pickled), is never put into an environment variable (so no child process - the Coach's learner
above all - can inherit it), and every encoding of it is registered with the log redaction filter on load.

The key file
    ``DATA_DIR/wallet/bot-keypair.json``: the 64 secret bytes as a JSON array (the ``solana-keygen`` format;
    seed then public key). The folder is 0700 and the file 0600 (looser permissions are tightened on load).

Created once (:func:`create`), on the first start in PAPER mode
    A fresh ed25519 keypair from ``solders.keypair.Keypair()`` (the operating system's CSPRNG). The bytes are
    written to a temporary file in the same folder (``O_EXCL``, mode 0600, fsync), which is then HARD-LINKED to
    the final name - a link fails when the name exists, so an existing key is never overwritten, not even by a
    second process racing this one - and the folder is fsynced. The file is read back before it is used.

    A ``.creating`` marker in the folder is written before and removed after, and a start killed in the middle
    leaves only ``.bot-keypair.json.*.tmp`` copies that the next start removes (:func:`load`): one that is a
    second link to the key, or one older than :data:`TEMP_STALE_S` (its address was never shown).

Never replaced
    An existing key file that is not a regular file, cannot be read or does not hold a valid keypair stops the
    bot (:class:`KeystoreError`) instead of being replaced: money may sit in that wallet. The one exception is
    a file :func:`create` was still writing when the process died (the ``.creating`` marker is there) and that
    this ledger never recorded: its address was never shown, so nothing can have been sent to it.

Never created where it could be lost (:func:`resolve_wallet`)
    * not in live mode (a live bot never starts on a brand-new empty wallet: the volume may be missing);
    * not when the ledger already recorded a generated wallet (kv ``keystore.pubkey``) whose file is gone;
    * not on Railway unless ``DATA_DIR`` is on the attached volume (``RAILWAY_VOLUME_MOUNT_PATH``): a container's
      own disk is wiped on every deploy, and the money with the key;
    * not on a Railway volume that already holds another bot wallet: a key file anywhere in the top
      :data:`SCAN_DEPTH` folders of the volume, or one listed in the volume's own ``.nightcrawler-wallets.json``
      (every wallet made on it, by address and folder; public data only). A changed ``DATA_DIR`` would
      otherwise hide a funded wallet behind a new empty one.

With ``BOT_WALLET_MODE=env`` a wallet the bot made itself is never used, so :func:`unused_wallet` names it: the
start logs an error and the page shows a banner (its SOL can only be taken back in generated mode).

The key in memory: every encoding is registered with the log redaction filter AND with the settings
(:meth:`~nightcrawler.config.Settings.add_runtime_secret`), so the page, ``/api/*`` and team-room scrubbers
(``settings.secret_values()``) redact it exactly like ``BOT_WALLET_SECRET``; and :func:`harden_process` turns
off core dumps and (Linux) marks the process non-dumpable, so no core file and no same-user ``ptrace`` or
``/proc/<pid>/mem`` read can carry it out.

Ambiguity is refused by the settings: ``BOT_WALLET_MODE=generated`` together with ``BOT_WALLET_SECRET``.

Signing: the two transactions this module signs itself, both for :mod:`nightcrawler.withdraw` -
:func:`sign_transfer` (a SystemProgram transfer of SOL from the bot wallet) and :func:`sign_close_accounts`
(CloseAccount of the bot's own EMPTY token accounts, their deposits returned to the bot wallet). Swaps are signed by
:meth:`~nightcrawler.broker.wallet.Wallet.sign_transaction_b64` as before.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import secrets as _random
import stat
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

from nightcrawler.base58 import b58encode, is_pubkey
from nightcrawler.broker.base import require_solders
from nightcrawler.broker.wallet import (
    Wallet,
    WalletError,
    _parse_base58_secret,
    _parse_json_secret,
    load_keypair,
)
from nightcrawler.config import Settings
from nightcrawler.logging_setup import get_logger

__all__ = [
    "CREATING_MARKER",
    "KEY_FILE",
    "KV_GENERATED",
    "KV_PUBKEY",
    "RECEIPT_KIND",
    "VOLUME_MARKER",
    "WALLET_DIR",
    "KeystoreError",
    "KeystoreExists",
    "KeystoreHalfMade",
    "SignedTransfer",
    "create",
    "harden_process",
    "key_path",
    "load",
    "load_or_create",
    "record",
    "resolve_wallet",
    "sign_close_accounts",
    "sign_transfer",
    "storage_problem",
    "transfer_message_b64",
    "unused_wallet",
]

log = get_logger(__name__)

WALLET_DIR = "wallet"
KEY_FILE = "bot-keypair.json"
#: The bot wallet's public address (also written by the live boot); the page shows it.
KV_PUBKEY = "wallet.pubkey"
#: The generated wallet this ledger has receipted (``wallet_created`` exactly once per wallet and ledger).
KV_GENERATED = "keystore.pubkey"
RECEIPT_KIND = "wallet_created"
DIR_MODE = 0o700
FILE_MODE = 0o600
#: Railway sets these in every deployment; RAILWAY_VOLUME_MOUNT_PATH only when a volume is attached.
_RAILWAY_MARKERS = ("RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_ENVIRONMENT_ID")
_FILE_NAME_FOR_HUMANS = f"DATA_DIR/{WALLET_DIR}/{KEY_FILE}"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_MAX_FILE_BYTES = 4096
#: Written in the wallet folder before a key is made and removed once it reads back (see :func:`create`).
CREATING_MARKER = ".creating"
#: At the Railway volume's root: every wallet made on this volume ``{"wallets": [{"pubkey", "key_file"}]}``.
VOLUME_MARKER = ".nightcrawler-wallets.json"
#: How many folder levels below the volume root are searched for another bot wallet before a new one is made.
SCAN_DEPTH = 3
#: A leftover ``.bot-keypair.json.*.tmp`` older than this is from a start that died (a racing one is younger).
TEMP_STALE_S = 60.0
_TEMP_GLOB = f".{KEY_FILE}.*.tmp"
_PR_SET_DUMPABLE = 4
#: Said wherever the key file is damaged or gone: the volume is the only copy (docs/GOING_LIVE.md, backups).
_RESTORE_HINT = ("If you turned on Railway's volume backups, restore the latest one (Railway: the volume, "
                 "Backups); if you have none, the bot cannot recover this wallet")


class KeystoreError(WalletError):
    """The bot's own wallet cannot be used or made. The message never contains the key."""


class KeystoreExists(KeystoreError):
    """:func:`create` found a key file already there (it is never replaced)."""


class KeystoreHalfMade(KeystoreError):
    """The key file is damaged AND :func:`create` was still writing it when the process stopped (its
    ``.creating`` marker is there): unless a ledger recorded that wallet, its address was never shown."""


class SignedTransfer(NamedTuple):
    """A signed SystemProgram transfer: the wire transaction, its id and the message whose fee it pays."""

    tx_b64: str
    signature: str
    message_b64: str


# --------------------------------------------------------------------------- paths and storage


def wallet_dir(data_dir: str | os.PathLike[str]) -> Path:
    return Path(data_dir) / WALLET_DIR


def key_path(data_dir: str | os.PathLike[str]) -> Path:
    return wallet_dir(data_dir) / KEY_FILE


def storage_problem(data_dir: str | os.PathLike[str], env: Mapping[str, str] | None = None) -> str | None:
    """Why a key made in ``data_dir`` could be LOST (with the money in it), or None. On Railway that is a
    ``DATA_DIR`` outside the attached volume; elsewhere the operator owns the disk."""
    env = os.environ if env is None else env
    if not any(env.get(name) for name in _RAILWAY_MARKERS):
        return None
    mount = str(env.get("RAILWAY_VOLUME_MOUNT_PATH") or "").strip()
    if not mount:
        return ("no volume is attached on Railway, so a wallet made now would be wiped (with its money) on the next "
                "deploy: attach a volume at /data and set DATA_DIR=/data (docs/RAILWAY.md, step 3)")
    data, volume = Path(data_dir).resolve(), Path(mount).resolve()
    if data != volume and volume not in data.parents:
        return (f"DATA_DIR is not on the Railway volume (mounted at {mount}), so a wallet made now would be wiped "
                "(with its money) on the next deploy: set DATA_DIR to the volume's path")
    return None


def _tighten(path: Path, mode: int) -> None:
    """Remove any permission beyond ``mode`` (group/other access to the key or its folder)."""
    current = stat.S_IMODE(os.lstat(path).st_mode)
    if current & ~mode:
        os.chmod(path, mode)
        log.warning("keystore_permissions_tightened path=%s from=%o to=%o", path.name, current, mode)


def _fsync_dir(folder: Path) -> None:
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:  # pragma: no cover - platforms without directory handles
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover - filesystems that cannot sync a directory
        pass
    finally:
        os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def _encodings(secret: bytes) -> list[str]:
    """Every text encoding of the key and of its seed half someone could print by mistake."""
    out = []
    for part in (secret, secret[:32]):
        out += [b58encode(part), part.hex(), part.hex().upper(), base64.b64encode(part).decode("ascii"),
                base64.urlsafe_b64encode(part).decode("ascii"), json.dumps(list(part)),
                json.dumps(list(part), separators=(",", ":"))]
    return out


def _register(redaction_filter: Any | None, secret: bytes, raw: str = "") -> None:
    """Every encoding of the key (and of its seed half) - and the file's own text - is redacted. ``redaction_filter``
    is anything with ``add_secret`` (the log filter, or :class:`_Sinks`)."""
    if redaction_filter is None:
        return
    for text in dict.fromkeys([*([raw] if raw else []), *_encodings(secret)]):
        redaction_filter.add_secret(text)


class _Sinks:
    """Hands every encoding to the log filter AND to the settings' scrub list (``secret_values()``)."""

    def __init__(self, redaction_filter: Any | None, settings: Settings | None) -> None:
        self.redaction_filter, self.settings = redaction_filter, settings

    def add_secret(self, value: str) -> None:
        if self.redaction_filter is not None:
            self.redaction_filter.add_secret(value)
        add = getattr(self.settings, "add_runtime_secret", None)
        if add is not None:
            add(value)


def harden_process() -> None:
    """While the key is in memory: no core dump (RLIMIT_CORE 0) and, on Linux, not dumpable (no same-user
    ``ptrace`` or ``/proc/<pid>/mem`` read). Best effort: a platform without either keeps working."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError, OSError) as exc:  # pragma: no cover - platforms without rlimits
        log.info("keystore_core_dumps_unchanged error=%s", type(exc).__name__)
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes

        if ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:  # pragma: no cover
            log.info("keystore_dumpable_unchanged errno=%d", ctypes.get_errno())
    except (OSError, AttributeError) as exc:  # pragma: no cover - no libc prctl
        log.info("keystore_dumpable_unchanged error=%s", type(exc).__name__)


def _write_marker(folder: Path) -> None:
    fd = os.open(folder / CREATING_MARKER, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _NOFOLLOW, FILE_MODE)
    try:
        _write_all(fd, b"a bot wallet is being made here\n")
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(folder)


def _clear_marker(folder: Path) -> None:
    try:
        (folder / CREATING_MARKER).unlink()
    except FileNotFoundError:
        return
    except OSError as exc:  # pragma: no cover - a read-only folder: harmless, it is only a marker
        log.warning("keystore_marker_not_removed error=%s", type(exc).__name__)
        return
    _fsync_dir(folder)


def _sweep_temps(folder: Path, final: Path) -> None:
    """Remove ``.bot-keypair.json.*.tmp`` left by a start that died inside :func:`create`: a second link to the
    key file (always), or a copy of a key that was never used, older than :data:`TEMP_STALE_S` (a younger one
    may belong to a start racing this one). Never raises."""
    try:
        temps = sorted(folder.glob(_TEMP_GLOB))
    except OSError:  # pragma: no cover - an unreadable folder: load() reports it
        return
    if not temps:
        return
    try:
        final_info: os.stat_result | None = os.lstat(final)
    except OSError:
        final_info = None
    now = time.time()
    for tmp in temps:
        try:
            info = os.lstat(tmp)
            if not stat.S_ISREG(info.st_mode):
                continue
            linked = final_info is not None and (info.st_dev, info.st_ino) == (final_info.st_dev, final_info.st_ino)
            if linked or now - info.st_mtime >= TEMP_STALE_S:
                os.unlink(tmp)
                log.warning("keystore_temp_removed file=%s reason=%s", tmp.name,
                            "second_link_to_the_key" if linked else "key_never_used")
        except OSError:  # pragma: no cover - gone already, or not ours to remove
            continue


# --------------------------------------------------------------------------- load / create


def load(data_dir: str | os.PathLike[str], redaction_filter: Any | None = None) -> Wallet | None:
    """The bot's own wallet from its key file, or None when there is no file. Raises :class:`KeystoreError`
    (never replacing the file) when it is not a regular file, unreadable or not a valid keypair -
    :class:`KeystoreHalfMade` when :func:`create` was still writing it. Leftover temporary copies are removed
    first. The file may hold the key as a JSON byte array (``solana-keygen``) or in base58 (Phantom)."""
    path = key_path(data_dir)
    _sweep_temps(path.parent, path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise KeystoreError(f"{_FILE_NAME_FOR_HUMANS} is not a regular file: refusing to start (the bot never "
                            "replaces its wallet; money may be in it)")
    try:
        _tighten(path.parent, DIR_MODE)
        _tighten(path, FILE_MODE)
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
        with os.fdopen(fd, "rb") as fh:
            raw = fh.read(_MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise KeystoreError(f"cannot read {_FILE_NAME_FOR_HUMANS} ({type(exc).__name__}): refusing to start (the bot "
                            "never replaces its wallet; money may be in it)") from None
    try:
        if len(raw) > _MAX_FILE_BYTES:
            raise WalletError("too large")
        text = raw.decode("ascii").strip()
        # the bytes are parsed ONCE, here (JSON array or base58), and registered from these bytes
        secret = _parse_json_secret(text) if text.startswith("[") else _parse_base58_secret(text)
        wallet = Wallet(secret)  # validates the key halves
    except (UnicodeDecodeError, WalletError, ValueError):
        if os.path.lexists(path.parent / CREATING_MARKER):
            raise KeystoreHalfMade(f"{_FILE_NAME_FOR_HUMANS} is damaged: the bot was still writing it when it "
                                   "stopped") from None
        raise KeystoreError(f"{_FILE_NAME_FOR_HUMANS} is damaged (not a valid keypair): refusing to start, because "
                            "money may be in that wallet and the bot never replaces it. " + _RESTORE_HINT) from None
    _register(redaction_filter, secret, text)
    _clear_marker(path.parent)  # a finished key: a marker left by a start that died after linking it is stale
    harden_process()
    return wallet


def create(data_dir: str | os.PathLike[str], redaction_filter: Any | None = None) -> Wallet:
    """Make a NEW key file (see the module docstring). Raises :class:`KeystoreExists` when one is already there
    (it is left untouched), ``LiveNotAllowed`` without ``solders`` and :class:`KeystoreError` when the file does
    not read back as the same wallet."""
    solders = require_solders()
    folder = wallet_dir(data_dir)
    folder.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    _tighten(folder, DIR_MODE)
    final = folder / KEY_FILE
    if os.path.lexists(final):
        raise KeystoreExists(f"{_FILE_NAME_FOR_HUMANS} already exists; it is never replaced")
    harden_process()
    secret = bytes(solders.keypair.Keypair())  # the operating system's CSPRNG
    wallet = Wallet(secret)
    _register(redaction_filter, secret)
    _write_marker(folder)  # until the key reads back: a file damaged mid-write is known to be half made
    body = (json.dumps(list(secret)) + "\n").encode("ascii")
    tmp = folder / f".{KEY_FILE}.{_random.token_hex(8)}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, FILE_MODE)
        try:
            os.fchmod(fd, FILE_MODE)  # whatever the umask
            _write_all(fd, body)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(tmp, final)  # fails when the name exists: an existing key is never overwritten
        except FileExistsError:
            raise KeystoreExists(f"{_FILE_NAME_FOR_HUMANS} already exists; it is never replaced") from None
        except OSError:  # a filesystem without hard links: an exclusive create of the final name instead
            _exclusive_write(final, body)
    finally:
        tmp.unlink(missing_ok=True)
    _fsync_dir(folder)
    check = load(data_dir, redaction_filter)  # also removes the marker
    if check is None or check.pubkey() != wallet.pubkey():
        raise KeystoreError(f"{_FILE_NAME_FOR_HUMANS} did not read back as the wallet just made: refusing to use it")
    log.info("wallet_created address=%s file=%s (the key never leaves this file)", wallet.pubkey(),
             _FILE_NAME_FOR_HUMANS)
    return wallet


def _exclusive_write(final: Path, body: bytes) -> None:
    try:
        fd = os.open(final, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, FILE_MODE)
    except FileExistsError:
        raise KeystoreExists(f"{_FILE_NAME_FOR_HUMANS} already exists; it is never replaced") from None
    try:
        os.fchmod(fd, FILE_MODE)
        _write_all(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)


def load_or_create(data_dir: str | os.PathLike[str], redaction_filter: Any | None = None) -> tuple[Wallet, bool]:
    """``(wallet, created)``: the existing key, else a new one (a racing process's key wins and is loaded)."""
    wallet = load(data_dir, redaction_filter)
    if wallet is not None:
        return wallet, False
    try:
        return create(data_dir, redaction_filter), True
    except KeystoreExists:
        wallet = load(data_dir, redaction_filter)
        if wallet is None:  # pragma: no cover - deleted between the link and this read
            raise KeystoreError(f"{_FILE_NAME_FOR_HUMANS} vanished while it was being made") from None
        return wallet, False


def _creation_problem(settings: Settings, ledger: Any | None, env: Mapping[str, str] | None) -> str | None:
    """Why a NEW wallet must not be made now (see the module docstring), or None."""
    if settings.is_live:
        return (f"TRADING_MODE=live with BOT_WALLET_MODE=generated needs the bot's wallet, but {_FILE_NAME_FOR_HUMANS} "
                "is missing. The bot makes it on the first start in PAPER mode, where you fund it; a live bot never "
                "starts on a brand-new empty wallet. Had it made one before? Then check the volume is attached at "
                "/data with DATA_DIR=/data")
    known = ledger.get_kv(KV_GENERATED) if ledger is not None else None
    if isinstance(known, str) and known:
        return (f"the bot made wallet {known} before (this ledger recorded it), but {_FILE_NAME_FOR_HUMANS} is gone. "
                f"Refusing to make another one: money may be in that wallet. {_RESTORE_HINT}")
    problem = storage_problem(settings.data_dir, env)
    if problem:
        return f"not making a bot wallet: {problem}"
    root = _volume_root(settings.data_dir, env)
    return _other_wallet_problem(root, key_path(settings.data_dir)) if root is not None else None


def _volume_root(data_dir: str | os.PathLike[str], env: Mapping[str, str] | None) -> Path | None:
    """The Railway volume ``data_dir`` is on (resolved), or None (not on Railway, or not on its volume)."""
    env = os.environ if env is None else env
    if not any(env.get(name) for name in _RAILWAY_MARKERS):
        return None
    mount = str(env.get("RAILWAY_VOLUME_MOUNT_PATH") or "").strip()
    if not mount:
        return None
    data, volume = Path(data_dir).resolve(), Path(mount).resolve()
    return volume if data == volume or volume in data.parents else None


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - outside the volume
        return str(path)


def _volume_wallets(root: Path) -> list[dict[str, str]]:
    """The wallets the volume marker lists (public addresses and key-file paths). Unreadable = none."""
    try:
        data = json.loads((root / VOLUME_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    wallets = data.get("wallets") if isinstance(data, dict) else None
    return [w for w in wallets if isinstance(w, dict) and isinstance(w.get("pubkey"), str)
            and isinstance(w.get("key_file"), str)] if isinstance(wallets, list) else []


def _other_wallet_problem(root: Path, own: Path) -> str | None:
    """Another bot wallet on this volume (listed in its marker, or a key file in its top folders), or None."""
    mine = _relative(root, own)
    for entry in _volume_wallets(root):
        if entry["key_file"] != mine:
            return _other_wallet_text(entry["key_file"], entry["pubkey"])
    for depth in range(SCAN_DEPTH + 1):
        pattern = "/".join(["*"] * depth + [WALLET_DIR, KEY_FILE])
        for found in sorted(root.glob(pattern)):
            if _relative(root, found) != mine:
                return _other_wallet_text(_relative(root, found), None)
    return None


def _other_wallet_text(key_file: str, pubkey: str | None) -> str:
    folder = key_file.rsplit(f"/{WALLET_DIR}/", 1)[0] if f"/{WALLET_DIR}/" in key_file else ""
    where = f"the volume's folder {folder}" if folder else "the top of the volume"
    return (f"another bot wallet{f' ({pubkey})' if pubkey else ''} already exists on this volume, in {where} "
            f"({key_file}). Refusing to make a second one: money may be in it, and a new wallet would hide it. Set "
            "DATA_DIR back to the folder that holds that wallet (the folder above its 'wallet' folder), then take "
            "the money back with WITHDRAW_TO before changing anything")


def _remember_on_volume(root: Path, wallet: Wallet, path: Path) -> None:
    """Add the wallet just made to the volume marker (public address and key-file path; atomic replace)."""
    entry = {"pubkey": wallet.pubkey(), "key_file": _relative(root, path)}
    wallets = [w for w in _volume_wallets(root) if w != entry] + [entry]
    tmp = root / f"{VOLUME_MARKER}.{_random.token_hex(4)}.tmp"
    try:
        tmp.write_text(json.dumps({"wallets": wallets}, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, root / VOLUME_MARKER)
        _fsync_dir(root)
    except OSError as exc:  # the key file itself is safe; the scan still finds it
        tmp.unlink(missing_ok=True)
        log.warning("keystore_volume_marker_not_written error=%s", type(exc).__name__)


def unused_wallet(settings: Settings, ledger: Any | None) -> str | None:
    """``BOT_WALLET_MODE=env`` while a wallet the bot made itself exists: its address (this ledger recorded it),
    ``""`` when only its key file is there, else None. Nobody else can move SOL out of it, so the start logs
    an error and the page says so."""
    if settings.bot_wallet_mode == "generated":
        return None
    known = ledger.get_kv(KV_GENERATED) if ledger is not None else None
    if isinstance(known, str) and known:
        return known
    try:
        return "" if os.path.lexists(key_path(settings.data_dir)) else None
    except OSError:  # pragma: no cover
        return None


def record(ledger: Any, wallet: Wallet, created: bool = False) -> None:
    """Note the generated wallet in the ledger: kv ``wallet.pubkey`` and ``keystore.pubkey`` and, the first time
    this ledger sees it, ONE ``wallet_created`` receipt with its public address (also after a crash between
    making the file and this receipt). A DIFFERENT generated wallet than the one recorded is a ``note``
    (``wallet_changed``): someone replaced the file."""
    pubkey = wallet.pubkey()
    known = ledger.get_kv(KV_GENERATED)
    with ledger.transaction():
        if known != pubkey:
            if isinstance(known, str) and known:
                ledger.append_receipt("note", {"event": "wallet_changed", "from": known, "to": pubkey})
                log.error("wallet_changed from=%s to=%s: the bot's key file was replaced", known, pubkey)
            else:
                ledger.append_receipt(RECEIPT_KIND, {"pubkey": pubkey, "mode": "generated",
                                                     "made_this_start": bool(created)})
            ledger.set_kv(KV_GENERATED, pubkey)
        ledger.set_kv(KV_PUBKEY, pubkey)


def resolve_wallet(settings: Settings, ledger: Any | None = None, redaction_filter: Any | None = None, *,
                   create: bool = True, env: Mapping[str, str] | None = None) -> Wallet | None:
    """The bot wallet for these settings, or None when there is none.

    * ``BOT_WALLET_MODE=env``: ``BOT_WALLET_SECRET`` (unchanged behaviour; None when it is not set).
    * ``BOT_WALLET_MODE=generated``: the key file; when missing and ``create``, a new one - unless that is unsafe
      (see the module docstring: :class:`KeystoreError`). With ``ledger`` the wallet is :func:`record`-ed.
    ``env`` (default ``os.environ``) is only read to tell whether ``DATA_DIR`` is on a Railway volume.
    """
    if settings.bot_wallet_mode != "generated":
        unused = unused_wallet(settings, ledger)
        if unused is not None:
            log.error("unused_bot_wallet address=%s: the bot made its own wallet earlier, but BOT_WALLET_MODE=%s does "
                      "not use it. If it holds SOL, set BOT_WALLET_MODE=generated (and delete BOT_WALLET_SECRET), "
                      "then take it back with WITHDRAW_TO", unused or "unknown", settings.bot_wallet_mode)
        return load_keypair(settings.bot_wallet_secret, redaction_filter) if settings.bot_wallet_secret else None
    sinks = _Sinks(redaction_filter, settings)
    try:
        wallet = load(settings.data_dir, sinks)
    except KeystoreHalfMade:
        known = ledger.get_kv(KV_GENERATED) if ledger is not None else None
        if not create or (isinstance(known, str) and known):
            raise KeystoreError(f"{_FILE_NAME_FOR_HUMANS} is damaged (not a valid keypair): refusing to start, "
                                "because money may be in that wallet and the bot never replaces it. "
                                + _RESTORE_HINT) from None
        # its address was never shown (create() logs it only after the read-back, then removes the marker)
        key_path(settings.data_dir).unlink()
        log.warning("keystore_half_made_removed file=%s: the bot stopped while writing a new key; its address was "
                    "never shown, so nothing was ever sent to it. Making the wallet again", _FILE_NAME_FOR_HUMANS)
        wallet = None
    created = False
    if wallet is None:
        if not create:
            return None
        problem = _creation_problem(settings, ledger, env)
        if problem:
            raise KeystoreError(problem)
        wallet, created = load_or_create(settings.data_dir, sinks)
        root = _volume_root(settings.data_dir, env)
        if created and root is not None:
            _remember_on_volume(root, wallet, key_path(settings.data_dir))
    if ledger is not None:
        record(ledger, wallet, created)
    return wallet


# --------------------------------------------------------------------------- the transfer it signs


#: The only programs whose accounts :func:`sign_close_accounts` closes: SPL Token and Token-2022.
TOKEN_PROGRAMS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
_CLOSE_ACCOUNT = bytes([9])  # TokenInstruction::CloseAccount (the same in both programs)


def _solders_parts() -> tuple[Any, Any, Any, Any, Any]:
    solders = require_solders()
    return (solders.message, solders.transaction, importlib.import_module("solders.system_program"),
            importlib.import_module("solders.pubkey"), importlib.import_module("solders.hash"))


def _transfer_message(source: str, to: str, lamports: int, blockhash: str) -> Any:
    if isinstance(lamports, bool) or not isinstance(lamports, int) or lamports <= 0:
        raise ValueError(f"a transfer needs a positive whole number of lamports, got {lamports!r}")
    if not is_pubkey(source) or not is_pubkey(to):
        raise ValueError("a transfer needs two Solana addresses")
    if source == to:
        raise ValueError("a transfer to the bot's own address moves nothing")
    message, _tx, system_program, pubkey, hash_ = _solders_parts()
    src, dst = pubkey.Pubkey.from_string(source), pubkey.Pubkey.from_string(to)
    ix = system_program.transfer(system_program.TransferParams(from_pubkey=src, to_pubkey=dst, lamports=lamports))
    return message.Message.new_with_blockhash([ix], src, hash_.Hash.from_string(blockhash))


def transfer_message_b64(source: str, to: str, lamports: int, blockhash: str) -> str:
    """The UNSIGNED message of a ``lamports`` transfer ``source`` -> ``to`` (base64, for ``getFeeForMessage``).
    Needs no key: paper mode prices a withdrawal with it and never signs anything."""
    return base64.b64encode(bytes(_transfer_message(source, to, lamports, blockhash))).decode("ascii")


def sign_transfer(wallet: Wallet, to: str, lamports: int, blockhash: str) -> SignedTransfer:
    """A legacy transaction with ONE SystemProgram transfer of ``lamports`` from ``wallet`` (also the fee payer)
    to ``to``, signed with the bot's key. The keypair object lives only inside this call and is never printed:
    ``str()`` of a solders ``Keypair`` IS its secret."""
    message = _transfer_message(wallet.pubkey(), to, lamports, blockhash)
    _message, transaction, _sp, _pk, hash_ = _solders_parts()
    keypair = wallet.keypair()
    try:
        if keypair.pubkey() != message.account_keys[0]:  # pragma: no cover - Wallet verifies its key halves
            raise KeystoreError("the bot's key does not match its address")
        tx = transaction.Transaction([keypair], message, hash_.Hash.from_string(blockhash))
    finally:
        del keypair
    return SignedTransfer(tx_b64=base64.b64encode(bytes(tx)).decode("ascii"), signature=str(tx.signatures[0]),
                          message_b64=base64.b64encode(bytes(message)).decode("ascii"))


def sign_close_accounts(wallet: Wallet, accounts: list[tuple[str, str]], blockhash: str) -> SignedTransfer:
    """A legacy transaction, paid and signed by ``wallet``, with one CloseAccount per ``(token account, token
    program)``: each (empty) account's lamports go back to ``wallet`` itself, never anywhere else. Only the SPL
    Token and Token-2022 programs are accepted."""
    if not accounts:
        raise ValueError("nothing to close")
    message, transaction, _sp, pubkey, hash_ = _solders_parts()
    instruction = importlib.import_module("solders.instruction")
    owner = pubkey.Pubkey.from_string(wallet.pubkey())
    ixs = []
    for account, program in accounts:
        if program not in TOKEN_PROGRAMS or not is_pubkey(account) or account == wallet.pubkey():
            raise ValueError("only the bot's own token accounts are closed")
        metas = [instruction.AccountMeta(pubkey.Pubkey.from_string(account), False, True),
                 instruction.AccountMeta(owner, False, True), instruction.AccountMeta(owner, True, False)]
        ixs.append(instruction.Instruction(pubkey.Pubkey.from_string(program), _CLOSE_ACCOUNT, metas))
    msg = message.Message.new_with_blockhash(ixs, owner, hash_.Hash.from_string(blockhash))
    keypair = wallet.keypair()
    try:
        tx = transaction.Transaction([keypair], msg, hash_.Hash.from_string(blockhash))
    finally:
        del keypair
    return SignedTransfer(tx_b64=base64.b64encode(bytes(tx)).decode("ascii"), signature=str(tx.signatures[0]),
                          message_b64=base64.b64encode(bytes(msg)).decode("ascii"))
