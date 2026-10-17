"""Which sport a game belongs to, for the Polymarket desk: a VERBATIM copy of ``research/lab4/P6/sports.py``
(lab 4 P6, PLAN.md Amendment 5), so the desk labels a game's sport exactly as the history test did. ``src`` never
imports ``research``; ``tests/test_polydesk_safety.py`` checks that the two maps agree code for code. Change
neither without the other. The lab's own docstring follows.

Lab 4 P6 (PLAN.md Amendment 5): which sport a game belongs to, from its event slug.

Fixed before any P6 return was read. A Polymarket event slug starts with a league code (``atp-tiafoe-bublik-2026-07-04``,
``epl-ars-che-2026-09-06``, ``cs2-g2a-navij1-2026-10-09``); :func:`league_of` takes that code and :func:`sport_of`
maps it to one of :data:`SPORTS`. The codes are the ones polymarket.com uses (the history in this lab) plus the ones
the Polymarket US gateway used for in-play events on 2026-10-10 (``setkameua``, ``ebfsa``, ``snhl`` ...), so the same
map can later be read by the desk. On the US venue an event also carries ``tags`` (``tennis``, ``table-tennis``,
``ice-hockey``, ``efootball`` ...); when tags are given they decide first, because a three-letter code can mean two
things (``pdc`` is Chilean football on the US venue, ``pdcdarts`` is darts; ``lec`` is the Leagues Cup on
polymarket.com, not the League of Legends EMEA league).

Pure functions, no network.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

SPORTS: tuple[str, ...] = (
    "tennis",
    "table tennis",
    "e-soccer",
    "esports",
    "soccer",
    "basketball",
    "baseball",
    "hockey",
    "american football",
    "mma/boxing",
    "cricket",
    "other",
)

# Exact league codes. Anything not listed (and not caught by a pattern below) is "other".
_EXACT: dict[str, str] = {}


def _add(sport: str, codes: str) -> None:
    for c in codes.split():
        _EXACT[c] = sport


_add(
    "tennis",
    "atp wta itf daviscup bjk utr challenger atpdb wtadb itfwo itfme itfm itfw atpch wtach",
)
_add(
    "table tennis",
    "setkameua setkamecz setkamemd setkam setka wtt wttwom wttmen ttstar ttcup ttelite tt",
)
_add("e-soccer", "ebfsa ebattles esoccer efootball gtleague ebfpl ebfll")
_add(
    "esports",
    "cs2 csgo lol dota2 val valorant codmw cod r6siege r6 hok mlbb sc2 ow rl esl starladder msi fissure "
    "lck lpl lcs pubg apex",
)
_add(
    "soccer",
    # polymarket.com codes seen in lab 4's cache
    "fifwc unl ucl lal mls epl arg bra col uel mex sea chi lec bun clf fl1 fif swe elc nor kor ere por bra2 spl "
    "sud jap col1 efl es2 bl2 tur conl den lib brco uwcl rou1 scop itc per1 dfb bel1 chi1 fin1 acle sui egy1 afcq "
    "ecu1 fr2 pol ja2 el1 bol1 asean aut argpn rus usc cze1 chi2 ned2 itsb argcopa auc tur2 nwsl uzb1 irl1 col2 "
    "efa ukr1 ecs wsl grc bra3 chfa skc gsc hr1 uae1 u20wwc swe2 isr uru1 hun enl lva1 frtc canpl bul kor2 fpd "
    "qat1 nor2 gre1 uslc mar1 svk1 srb gtm ccup el2 ptsc ptc slo kaz1 aze1 idn1 ven1 tha1 usl1 bel2 atc chl2 "
    "sclc aze2 est1 idn2 ltu1 saf1 usoc world "
    # Polymarket US codes seen on 2026-10-10
    "ncaaws ncaams ch1cl isl1 swsl caru20 be1acff be1vv gaub pvl vkl tff1 grsl svn3e ligpor sercb den1 fnl hnl "
    "engnl cyp1 atbl nb1 btla els nls rpl lal2 pl1 pdc lig2 ilaln minw peu20",
)
_add(
    "basketball",
    "nba wnba nbasl euroleague cbb ncaab ncaawb cznbl lnb hunbl svkbl vtb lkl gbl aba autbl acb bsl slb slnbl "
    "lba fra2 bbl",
)
_add("baseball", "mlb kbo npb cpbl")
_add("hockey", "nhl khl shl snhl del del2 liiga ahl iihf czhl nhlpo")
_add("american football", "nfl cfb cfl ufl xfl ncaaf")
_add("mma/boxing", "ufc zuffa boxing pfl bellator floyd")
_add("cricket", "crint ipl psl")

# Prefix patterns, tried in order after the exact table.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(atp|wta|itf|utr|challenger)"), "tennis"),
    (re.compile(r"^(setka|wtt|ttstar|ttcup|ttelite)"), "table tennis"),
    (re.compile(r"^(ebf|ebattle|esoccer|efootball)"), "e-soccer"),
    (re.compile(r"^cric"), "cricket"),
    (re.compile(r"^(bk|bskt)"), "basketball"),
)

# Venue tags (Polymarket US events), most specific first: "e-soccer" before "soccer", "table-tennis" before "tennis".
_TAGS: tuple[tuple[str, str], ...] = (
    ("efootball", "e-soccer"),
    ("ebattles", "e-soccer"),
    ("esoccer", "e-soccer"),
    ("table-tennis", "table tennis"),
    ("tennis", "tennis"),
    ("esports", "esports"),
    ("ice-hockey", "hockey"),
    ("hockey", "hockey"),
    ("basketball", "basketball"),
    ("baseball", "baseball"),
    ("football", "american football"),
    ("soccer", "soccer"),
    ("ufc", "mma/boxing"),
    ("mma", "mma/boxing"),
    ("boxing", "mma/boxing"),
    ("cricket", "cricket"),
)


def league_of(event_slug: str | None) -> str:
    """The league code: the first dash-separated word of the event slug, lower case ('' when missing)."""
    if not event_slug:
        return ""
    return str(event_slug).split("-", 1)[0].lower()


def sport_of(event_slug: str | None, tags: Iterable[str] | None = None) -> str:
    """One of :data:`SPORTS` for an event: the venue's tags when given, else the league code; 'other' otherwise."""
    if tags:
        low = {str(t).lower() for t in tags}
        for tag, sport in _TAGS:
            if tag in low:
                return sport
    code = league_of(event_slug)
    if code in _EXACT:
        return _EXACT[code]
    for pat, sport in _PATTERNS:
        if pat.match(code):
            return sport
    return "other"
