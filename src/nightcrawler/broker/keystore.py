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

Never replaced
    An existing key file that is not a regular file, cannot be read or does not hold a valid keypair stops the
    bot (:class:`KeystoreError`) instead of being replaced: money may sit in that wallet.

Never created where it could be lost (:func:`resolve_wallet`)
    * not in live mode (a live bot never starts on a brand-new empty wallet: the volume may be missing);
    * not when the ledger already recorded a generated wallet (kv ``keystore.pubkey``) whose file is gone;
    * not on Railway unless ``DATA_DIR`` is on the attached volume (``RAILWAY_VOLUME_MOUNT_PATH``): a container's
      own disk is wiped on every deploy, and the money with the key.

Ambiguity is refused by the settings: ``BOT_WALLET_MODE=generated`` together with ``BOT_WALLET_SECRET``.

Signing (:func:`sign_transfer`) builds the one transaction this module signs itself: a SystemProgram transfer
of SOL from the bot wallet, for :mod:`nightcrawler.withdraw`. Swaps are signed by
:meth:`~nightcrawler.broker.wallet.Wallet.sign_transaction_b64` as before.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import secrets as _random
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

from nightcrawler.base58 import b58encode, is_pubkey
from nightcrawler.broker.base import require_solders
from nightcrawler.broker.wallet import Wallet, WalletError, load_keypair
from nightcrawler.config import Secret, Settings
from nightcrawler.logging_setup import get_logger

__all__ = [
    "KEY_FILE",
    "KV_GENERATED",
    "KV_PUBKEY",
    "RECEIPT_KIND",
    "WALLET_DIR",
    "KeystoreError",
    "KeystoreExists",
    "SignedTransfer",
    "create",
    "key_path",
    "load",
    "load_or_create",
    "record",
    "resolve_wallet",
    "sign_transfer",
    "storage_problem",
    "transfer_message_b64",
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


class KeystoreError(WalletError):
    """The bot's own wallet cannot be used or made. The message never contains the key."""


class KeystoreExists(KeystoreError):
    """:func:`create` found a key file already there (it is never replaced)."""


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


def _register(redaction_filter: Any | None, secret: bytes) -> None:
    """Every encoding of the key (and of its seed half) is redacted from the logs."""
    if redaction_filter is None:
        return
    for part in (secret, secret[:32]):
        for text in (b58encode(part), part.hex(), base64.b64encode(part).decode("ascii"),
                     json.dumps(list(part)), json.dumps(list(part), separators=(",", ":"))):
            redaction_filter.add_secret(text)


# --------------------------------------------------------------------------- load / create


def load(data_dir: str | os.PathLike[str], redaction_filter: Any | None = None) -> Wallet | None:
    """The bot's own wallet from its key file, or None when there is no file. Raises :class:`KeystoreError`
    (never replacing the file) when it is not a regular file, unreadable or not a valid keypair."""
    path = key_path(data_dir)
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
        text = raw.decode("ascii")
        wallet = load_keypair(Secret(text), redaction_filter)  # validates the format and the key halves
        if redaction_filter is not None:
            _register(redaction_filter, bytes(json.loads(text)))
    except (UnicodeDecodeError, WalletError):
        raise KeystoreError(f"{_FILE_NAME_FOR_HUMANS} is damaged (not a valid keypair): refusing to start. The bot "
                            "never replaces its wallet, because money may be in it: restore the file from a backup "
                            "of the volume") from None
    return wallet


def create(data_dir: str | os.PathLike[str], redaction_filter: Any | None = None) -> Wallet:
    """Make a NEW key file (see the module docstring). Raises :class:`KeystoreExists` when one is already there
    (it is left untouched), ``LiveNotAllowed`` without ``solders`` and :class:`KeystoreError` when the file does
    not read back as the same wallet."""
    solders = require_solders()
    folder = wallet_dir(data_dir)
    folder.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    _tighten(folder, DIR_MODE)
    secret = bytes(solders.keypair.Keypair())  # the operating system's CSPRNG
    wallet = Wallet(secret)
    _register(redaction_filter, secret)
    body = (json.dumps(list(secret)) + "\n").encode("ascii")
    final = folder / KEY_FILE
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
    check = load(data_dir, redaction_filter)
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
                "Refusing to make another one: money may be in that wallet. Restore the file (the volume), or "
                "start over with a new DATA_DIR on purpose")
    problem = storage_problem(settings.data_dir, env)
    return f"not making a bot wallet: {problem}" if problem else None


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
        return load_keypair(settings.bot_wallet_secret, redaction_filter) if settings.bot_wallet_secret else None
    wallet = load(settings.data_dir, redaction_filter)
    created = False
    if wallet is None:
        if not create:
            return None
        problem = _creation_problem(settings, ledger, env)
        if problem:
            raise KeystoreError(problem)
        wallet, created = load_or_create(settings.data_dir, redaction_filter)
    if ledger is not None:
        record(ledger, wallet, created)
    return wallet


# --------------------------------------------------------------------------- the transfer it signs


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
