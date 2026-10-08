"""Event layouts, Python decoders and SQL-template rendering for pump.fun data on CryptoHouse.

The pump.fun programs emit Anchor events through a self-CPI ("emit_cpi"). In
``solana.instructions`` each event is an *inner* instruction (``parent_index >= 0``) of the emitting
program whose base58 ``data`` decodes to::

    e445a52e51cb9a1d  <8-byte event discriminator>  <borsh-encoded event>

Offsets below are 1-indexed byte positions in the decoded bytes, as used by the SQL templates
(``substring(r, pos, len)``). They were verified on 2026-10-08 rows (fixtures in ``tests/fixtures``)
and re-checked by the validation gates. Layouts grew over time (fields appended at the end); the
leading fields used here kept their positions through the U_ext window, but re-check older months.

Curve ``6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P``

* TradeEvent ``bddb7fd34ee661ee``: mint 17, sol_amount u64 49 (lamports moved into / out of the curve,
  fees excluded), token_amount u64 57 (6 decimals), is_buy u8 65, user 66, timestamp i64 98,
  virtual_sol 106, virtual_token 114, real_sol 122, real_token 130 (all *after* the trade),
  fee_recipient 138, fee_bps u64 170, fee u64 178, creator 186, creator_fee_bps u64 218,
  creator_fee u64 226, track_volume u8 234, ... ix_name (u32 length + utf8) at 267.
  User-side SOL: buy = sol + fee + creator_fee, sell = sol - fee - creator_fee.
* CreateEvent ``1b72a94ddeeb6376``: name, symbol, uri as (u32 length, utf8); with ``o4`` the position
  after uri: mint o4, bonding_curve o4+32, user o4+64, creator o4+96, timestamp o4+128,
  virtual_token o4+136, virtual_sol o4+144, real_token o4+152, total_supply o4+160,
  token_program o4+168, is_mayhem_mode u8 o4+200, quote_mint o4+201 (all-zero = native SOL, which
  base58-encodes to ``11111111111111111111111111111111`` as in the census).
* CompleteEvent ``5f72619cd42e9808``: user 17, mint 49, bonding_curve 81, timestamp 113.

PumpSwap ``pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA``

* BuyEvent ``67f4521f2cf57777`` / SellEvent ``3e2f370aa503dc2a``: timestamp i64 17, then 13 u64:
  base_amount 25, (max_in|min_out) 33, user_base_res 41, user_quote_res 49, pool_base_res 57,
  pool_quote_res 65 (reserves *before* the trade, gate V5), quote_amount 73, lp_fee_bps 81,
  lp_fee 89, protocol_fee_bps 97, protocol_fee 105, **pool_quote_delta 113** (the change of the pool's
  quote vault for buy, buy_exact_quote_in and sell alike), user_quote 121; pool 129, user 161,
  user_base_ata 193, user_quote_ata 225, protocol_fee_recipient 257, its ata 289, coin_creator 321,
  coin_creator_fee_bps u64 353, coin_creator_fee u64 361.
  User-side SOL: buy = pool_quote_delta + protocol_fee + coin_creator_fee;
  sell = pool_quote_delta - protocol_fee - coin_creator_fee (equals user_quote at 121).
* CreatePoolEvent ``b1310cd2a076a774``: timestamp 17, index u16 25, creator 27, base_mint 59,
  quote_mint 91, base_decimals u8 123, quote_decimals u8 124, base_amount_in 125,
  quote_amount_in 133, pool_base_amount 141, pool_quote_amount 149, minimum_liquidity 157,
  initial_liquidity 165, lp_token_amount_out 173, pool_bump u8 181, pool 182, lp_mint 214,
  user_base_ata 246, user_quote_ata 278, coin_creator 310.
  A pump.fun migration pool has base = the coin, quote = WSOL, 206.9M tokens and ~85 SOL.

**Failed transactions.** ``solana.instructions`` keeps the inner instructions of *failed*
transactions, so their events look like trades that never happened (2.6-4.4 % of PumpSwap events,
~0.7 % of curve trades and ~4 % of CreateEvents on 2026-10-08). Every template anti-joins
``solana.transactions_non_voting`` rows with ``err != ''``.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Iterable

CURVE_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
NATIVE_SOL_QUOTE = "11111111111111111111111111111111"  # 32 zero bytes

EVENT_PREFIX = bytes.fromhex("e445a52e51cb9a1d")
DISC = {
    "curve_trade": bytes.fromhex("bddb7fd34ee661ee"),
    "curve_create": bytes.fromhex("1b72a94ddeeb6376"),
    "curve_complete": bytes.fromhex("5f72619cd42e9808"),
    "amm_buy": bytes.fromhex("67f4521f2cf57777"),
    "amm_sell": bytes.fromhex("3e2f370aa503dc2a"),
    "amm_create_pool": bytes.fromhex("b1310cd2a076a774"),
}

# base58 string-length windows (cheap prefilter: ClickHouse reads only the size subcolumn).
# Measured on 2026-10-08: TradeEvent 533-720, CreateEvent 436-640, CompleteEvent 208,
# Buy 679-704, Sell 614, CreatePool 481. Ranges are widened for older and newer layouts.
LEN_RANGES = {
    "curve_trade": (380, 900),
    "curve_create": (300, 900),
    "curve_complete": (150, 260),
    "amm_trade": (520, 900),
    "amm_create_pool": (440, 520),
}

SQL_DIR = Path(__file__).resolve().parent / "sql"

# ----------------------------------------------------------------------------------------------
# base58

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_IDX = {c: i for i, c in enumerate(_B58)}
_B58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58_IDX[ch]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = []
    while n:
        n, r = divmod(n, 58)
        out.append(_B58[r])
    pad = len(b) - len(b.lstrip(b"\x00"))
    return "1" * pad + "".join(reversed(out))


def is_base58(s: str) -> bool:
    return bool(_B58_RE.match(s or ""))


# ----------------------------------------------------------------------------------------------
# Python decoders (mirror the SQL offsets; used by tests and spot checks)


def _u64(b: bytes, pos1: int) -> int:
    return struct.unpack_from("<Q", b, pos1 - 1)[0]


def _i64(b: bytes, pos1: int) -> int:
    return struct.unpack_from("<q", b, pos1 - 1)[0]


def _key(b: bytes, pos1: int) -> str:
    return b58encode(b[pos1 - 1: pos1 - 1 + 32])


def event_kind(raw: bytes) -> str | None:
    if raw[:8] != EVENT_PREFIX:
        return None
    d = raw[8:16]
    for k, v in DISC.items():
        if v == d:
            return k
    return None


@dataclass
class CurveTrade:
    mint: str
    sol: int          # lamports into/out of the curve, fees excluded
    tok: int          # raw token units (6 decimals)
    is_buy: bool
    user: str
    ts: int
    vsol: int
    vtok: int
    rsol: int
    rtok: int
    fee: int
    creator: str
    creator_fee: int
    ix_name: str

    @property
    def user_sol(self) -> int:
        return self.sol + self.fee + self.creator_fee if self.is_buy else self.sol - self.fee - self.creator_fee


def decode_curve_trade(raw: bytes) -> CurveTrade:
    ix_name = ""
    if len(raw) >= 271:
        n = struct.unpack_from("<I", raw, 266)[0]
        if 0 < n < 64 and len(raw) >= 270 + n:
            ix_name = raw[270:270 + n].decode("utf-8", "replace")
    return CurveTrade(
        mint=_key(raw, 17), sol=_u64(raw, 49), tok=_u64(raw, 57), is_buy=raw[64] == 1,
        user=_key(raw, 66), ts=_i64(raw, 98), vsol=_u64(raw, 106), vtok=_u64(raw, 114),
        rsol=_u64(raw, 122), rtok=_u64(raw, 130),
        fee=_u64(raw, 178) if len(raw) >= 185 else 0,
        creator=_key(raw, 186) if len(raw) >= 217 else "",
        creator_fee=_u64(raw, 226) if len(raw) >= 233 else 0,
        ix_name=ix_name,
    )


@dataclass
class CurveCreate:
    name: str
    symbol: str
    uri: str
    mint: str
    bonding_curve: str
    user: str
    creator: str
    ts: int
    vtok: int
    vsol: int
    rtok: int
    supply: int
    token_program: str
    is_mayhem: bool | None
    quote_mint: str | None


def decode_curve_create(raw: bytes) -> CurveCreate:
    o = 16
    strs = []
    for _ in range(3):
        n = struct.unpack_from("<I", raw, o)[0]
        o += 4
        strs.append(raw[o:o + n].decode("utf-8", "replace"))
        o += n
    p = o + 1  # 1-indexed position of mint (o4 in SQL)
    has_tp = len(raw) >= p + 199
    return CurveCreate(
        name=strs[0], symbol=strs[1], uri=strs[2], mint=_key(raw, p), bonding_curve=_key(raw, p + 32),
        user=_key(raw, p + 64), creator=_key(raw, p + 96), ts=_i64(raw, p + 128),
        vtok=_u64(raw, p + 136), vsol=_u64(raw, p + 144), rtok=_u64(raw, p + 152), supply=_u64(raw, p + 160),
        token_program=_key(raw, p + 168) if has_tp else "",
        is_mayhem=(raw[p + 199] == 1) if len(raw) >= p + 200 else None,
        quote_mint=_key(raw, p + 201) if len(raw) >= p + 232 else None,
    )


@dataclass
class CurveComplete:
    user: str
    mint: str
    bonding_curve: str
    ts: int


def decode_curve_complete(raw: bytes) -> CurveComplete:
    return CurveComplete(user=_key(raw, 17), mint=_key(raw, 49), bonding_curve=_key(raw, 81), ts=_i64(raw, 113))


@dataclass
class AmmTrade:
    is_buy: bool
    ts: int
    base_amount: int
    pool_base_before: int
    pool_quote_before: int
    quote_amount: int
    lp_fee: int
    protocol_fee: int
    pool_quote_delta: int
    user_quote: int
    pool: str
    user: str
    coin_creator: str
    coin_creator_fee: int

    @property
    def user_sol(self) -> int:
        extra = self.protocol_fee + self.coin_creator_fee
        return self.pool_quote_delta + extra if self.is_buy else self.pool_quote_delta - extra

    @property
    def pool_base_after(self) -> int:
        return self.pool_base_before - self.base_amount if self.is_buy else self.pool_base_before + self.base_amount

    @property
    def pool_quote_after(self) -> int:
        return (self.pool_quote_before + self.pool_quote_delta if self.is_buy
                else self.pool_quote_before - self.pool_quote_delta)


def decode_amm_trade(raw: bytes) -> AmmTrade:
    kind = event_kind(raw)
    if kind not in ("amm_buy", "amm_sell"):
        raise ValueError(f"not a PumpSwap trade event: {kind}")
    return AmmTrade(
        is_buy=kind == "amm_buy", ts=_i64(raw, 17), base_amount=_u64(raw, 25),
        pool_base_before=_u64(raw, 57), pool_quote_before=_u64(raw, 65), quote_amount=_u64(raw, 73),
        lp_fee=_u64(raw, 89), protocol_fee=_u64(raw, 105), pool_quote_delta=_u64(raw, 113),
        user_quote=_u64(raw, 121), pool=_key(raw, 129), user=_key(raw, 161),
        coin_creator=_key(raw, 321) if len(raw) >= 352 else "",
        coin_creator_fee=_u64(raw, 361) if len(raw) >= 368 else 0,
    )


@dataclass
class AmmCreatePool:
    ts: int
    index: int
    creator: str
    base_mint: str
    quote_mint: str
    base_decimals: int
    quote_decimals: int
    base_in: int
    quote_in: int
    pool_base: int
    pool_quote: int
    lp_out: int
    pool: str
    lp_mint: str
    coin_creator: str


def decode_amm_create_pool(raw: bytes) -> AmmCreatePool:
    return AmmCreatePool(
        ts=_i64(raw, 17), index=struct.unpack_from("<H", raw, 24)[0], creator=_key(raw, 27),
        base_mint=_key(raw, 59), quote_mint=_key(raw, 91), base_decimals=raw[122], quote_decimals=raw[123],
        base_in=_u64(raw, 125), quote_in=_u64(raw, 133), pool_base=_u64(raw, 141), pool_quote=_u64(raw, 149),
        lp_out=_u64(raw, 173), pool=_key(raw, 182), lp_mint=_key(raw, 214),
        coin_creator=_key(raw, 310) if len(raw) >= 341 else "",
    )


def decode_event(data_b58: str):
    raw = b58decode(data_b58)
    kind = event_kind(raw)
    fn = {
        "curve_trade": decode_curve_trade, "curve_create": decode_curve_create,
        "curve_complete": decode_curve_complete, "amm_buy": decode_amm_trade,
        "amm_sell": decode_amm_trade, "amm_create_pool": decode_amm_create_pool,
    }.get(kind or "")
    return kind, (fn(raw) if fn else None)


# ----------------------------------------------------------------------------------------------
# SQL templates


def sql_list(values: Iterable[str]) -> str:
    """A ClickHouse array literal of base58 keys; rejects anything that is not base58."""
    vals = list(values)
    for v in vals:
        if not is_base58(v):
            raise ValueError(f"not a base58 key: {v!r}")
    return "[" + ",".join(f"'{v}'" for v in vals) + "]"


def sql_in(values: Iterable[str]) -> str:
    """A tuple literal ('a','b',...) of base58 keys for ``x IN (...)``; rejects non-base58."""
    vals = list(values)
    for v in vals:
        if not is_base58(v):
            raise ValueError(f"not a base58 key: {v!r}")
    if not vals:
        return "('')"
    return "(" + ",".join(f"'{v}'" for v in vals) + ")"


def sql_tuples(rows: Iterable[tuple]) -> str:
    """Array literal of tuples of base58 strings and integers, e.g. [('pool',123),...]."""
    parts = []
    for row in rows:
        items = []
        for v in row:
            if isinstance(v, bool):
                items.append("1" if v else "0")
            elif isinstance(v, int):
                items.append(str(int(v)))
            elif isinstance(v, str):
                if not is_base58(v):
                    raise ValueError(f"not a base58 key: {v!r}")
                items.append(f"'{v}'")
            else:
                raise TypeError(type(v))
        parts.append("(" + ",".join(items) + ")")
    return "[" + ",".join(parts) + "]"


def render_sql(name: str, **params) -> str:
    """Load sql/<name>.sql and substitute $params (string.Template, so ClickHouse braces are safe)."""
    text = (SQL_DIR / f"{name}.sql").read_text()
    common = {
        "CURVE": CURVE_PROGRAM, "AMM": AMM_PROGRAM, "PREFIX": EVENT_PREFIX.hex().upper(),
        **{f"D_{k.upper()}": v.hex().upper() for k, v in DISC.items()},
        **{f"L_{k.upper()}_LO": lo for k, (lo, hi) in LEN_RANGES.items()},
        **{f"L_{k.upper()}_HI": hi for k, (lo, hi) in LEN_RANGES.items()},
    }
    common.update(params)
    return Template(text).substitute(common)


def lamports(x) -> float:
    return float(x) / 1e9
