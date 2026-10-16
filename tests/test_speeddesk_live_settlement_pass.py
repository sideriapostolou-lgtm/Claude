"""One synchronous settlement pass reuses active membership without changing real reconciliation."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from test_speeddesk_live import TICKER, make_desk
from test_speeddesk_live_history import add_history

from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live import ORDER_LIST_LAG_S, Intent
from nightcrawler.speeddesk_live_model import ActualFill, LiveIntent, LiveRejected


def closed_fill(desk, account, clock, index=0, *, up_wins=True):
    """Confirmed historical one-contract fill, including actual fee; venue has finalized and is flat."""
    slug = f'KXBTC15M-PASS{index:03d}-00'
    window = replace(desk.book.windows[TICKER], slug=slug, start=clock.now()-1000, end=clock.now()-100)
    desk.book.add_window(window)
    key, order_id = f'nc-speed-pass-{index}', f'pass-order-{index}'
    desk.intents[key] = Intent(key, slug, 'up', 'rest', .4, 1, .5, window.start+1,
                               order_id=order_id, terminal=True)
    desk.book.intents[key] = LiveIntent(key, slug, 'up', 'rest', .4, 1, window.start+1, .41,
                                       order_id=order_id)
    fill = ActualFill(f'pass-fill-{index}', order_id, key, slug, 'up', .4, 1, .001, window.start+2)
    assert desk.book.record_fill(fill)
    account.orders.append({'order_id':order_id, 'client_order_id':key, 'ticker':slug, 'status':'executed',
                           'fill_count_fp':'1.00', 'remaining_count_fp':'0.00', 'initial_count_fp':'1.00',
                           'outcome_side':'yes', 'book_side':'bid', 'yes_price_dollars':'.40'})
    account.executions.append({'fill_id':fill.fill_id, 'order_id':order_id, 'ticker':slug,
                               'outcome_side':'yes', 'book_side':'bid', 'count_fp':'1.00',
                               'yes_price_dollars':'.40', 'fee_cost':'.001', 'ts':fill.at})
    account.resolutions.append({'ticker':slug, 'market_result':'yes' if up_wins else 'no',
                                'revenue':100 if up_wins else 0, 'settled_time':window.end+5})
    return slug


def pending(desk, account, clock, slug, mode):
    key = f'nc-speed-pending-{mode}'
    order_id = f'pending-{mode}' if mode in {'resting', 'unlisted_ack'} else None
    window = desk.book.windows[slug]
    desk.intents[key] = Intent(key, slug, 'down', 'rest', .4, 1, .5, window.start+3,
                               order_id=order_id or '', uncertain=mode=='uncertain')
    desk.book.intents[key] = LiveIntent(key, slug, 'down', 'rest', .4, 1, window.start+3, .41,
                                       order_id=order_id, uncertainty='create_ambiguous' if mode=='uncertain' else None)
    if mode == 'resting':
        account.orders.append({'order_id':order_id, 'client_order_id':key, 'ticker':slug, 'status':'resting',
                               'fill_count_fp':'0.00', 'remaining_count_fp':'1.00', 'initial_count_fp':'1.00',
                               'outcome_side':'no', 'book_side':'ask', 'no_price_dollars':'.40'})
    return key


def reconcile(desk):
    desk.full_scan_at = -float('inf')
    asyncio.run(desk._reconcile())
    assert desk.last_sync_report['full']


@pytest.mark.parametrize('integrity', [False, True])
def test_finalized_history_has_bounded_active_queries_even_during_integrity_fallback(tmp_path: Path, integrity):
    desk, account, _clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        add_history(desk, account, 7)
        desk.final_outcomes.update({key: row.up_wins for key,row in desk.book.settled.items()})
        if integrity:
            # Existing history fallback fixture: a settled record has reopened under an integrity stop.
            old = next(key for key in desk.intents if key.startswith('nc-speed-old'))
            desk.intents[old].terminal = False
            desk.book.integrity_error = 'fill_after_terminal_confirmation'
        original, calls = desk._active, []
        def counted():
            calls.append(1)
            return original()
        desk._active = counted
        before = (desk.book.realized_pnl, dict(desk.book.day_pnl), dict(desk.book.fills),
                  desk.book.integrity_error, list(account.creates))
        reconcile(desk)
        assert not desk.last_sync_report['checks']
        assert len(calls) <= 16  # baseline rebuilt membership once for each of672 finalized windows
        assert before == (desk.book.realized_pnl, dict(desk.book.day_pnl), dict(desk.book.fills),
                          desk.book.integrity_error, account.creates)
        # Existing responsive cleanup still cancels the current and reopened old Intent under integrity stop.
        assert account.cancels == (['order-1', 'old-order-1'] if integrity else [])
        assert len(desk.book.settled) == 672
    finally:
        desk.close()


def test_multiple_actual_settlements_preserve_costs_fees_inventory_and_practice(tmp_path: Path):
    desk, account, clock = make_desk(tmp_path)
    try:
        desk.client = account
        slugs = [closed_fill(desk, account, clock, i, up_wins=i!=1) for i in range(3)]
        fills = dict(desk.book.fills)
        inventories = {slug:asdict(desk.book.inventory[slug]) for slug in slugs}
        practice = desk.twin.to_state()
        reconcile(desk)
        assert set(desk.book.settled) == set(slugs)
        assert [desk.book.settled[slug].pnl_usd for slug in slugs] == pytest.approx([.599,-.401,.599])
        assert desk.book.realized_pnl == pytest.approx(.797)
        assert all(row.cost_usd == .4 and row.fee_usd == .001 for row in desk.book.settled.values())
        assert desk.book.fills == fills
        assert {slug:asdict(desk.book.inventory[slug]) for slug in slugs} == inventories
        assert desk.twin.to_state() == practice and not account.creates and not account.cancels
        receipts = [row.payload for row in desk.ledger.iter_receipts() if row.kind=='speeddesk_live_settlement']
        assert len(receipts) == 3 and {row['window'] for row in receipts} == set(slugs)
    finally:
        desk.close()


@pytest.mark.parametrize('mode', ['resting', 'uncertain', 'unsent', 'unlisted_ack'])
def test_active_uncertain_and_unlisted_liabilities_still_defer_settlement(tmp_path: Path, mode):
    desk, account, clock = make_desk(tmp_path)
    try:
        desk.client = account
        slug = closed_fill(desk, account, clock)
        identity = pending(desk, account, clock, slug, mode)
        def cancel_unknown(*args, **kwargs):
            raise KalshiClientError('cancel', 'transport failure', uncertain=True, timed_out=True)
        account.cancel = cancel_unknown
        reconcile(desk)
        assert slug not in desk.book.settled
        assert desk.book.intents[identity].reservation_active and not desk.intents[identity].terminal
        assert desk.book.realized_pnl == 0 and not account.creates
    finally:
        desk.close()


def test_same_full_read_that_releases_an_unsent_intent_also_settles_its_window(tmp_path: Path):
    desk, account, clock = make_desk(tmp_path)
    try:
        desk.client = account
        slug = closed_fill(desk, account, clock)
        identity = pending(desk, account, clock, slug, 'unsent')
        reconcile(desk)
        assert slug not in desk.book.settled and desk.book.intents[identity].reservation_active
        clock.advance(ORDER_LIST_LAG_S)
        reconcile(desk)
        assert desk.intents[identity].terminal and not desk.book.intents[identity].reservation_active
        assert desk.book.intents[identity].uncertainty == 'never_reached_venue'
        assert desk.book.settled[slug].pnl_usd == pytest.approx(.599)
        assert not desk.book.integrity_error and not account.creates
    finally:
        desk.close()


def test_changed_fill_fee_of_already_settled_order_still_aborts_full_reconciliation(tmp_path: Path):
    desk, account, clock = make_desk(tmp_path)
    try:
        desk.client = account
        slug = closed_fill(desk, account, clock)
        reconcile(desk)
        settled = desk.book.settled[slug]
        account.executions[0]['fee_cost'] = '.002'
        with pytest.raises(LiveRejected, match='fill_changed'):
            reconcile(desk)
        assert desk.book.settled[slug] == settled and desk.book.integrity_error == 'fill_changed'
        assert desk.last_sync_report['full'] and desk.last_sync_report['failed']
    finally:
        desk.close()


def test_payout_error_still_aborts_before_balance_or_settlement_receipt(tmp_path: Path):
    desk, account, clock = make_desk(tmp_path)
    try:
        desk.client = account
        slug = closed_fill(desk, account, clock)
        account.resolutions[0]['revenue'] = 99
        def unexpected_balance():
            pytest.fail('settlement payout failure must abort before the balance read')
        account.balance = unexpected_balance
        with pytest.raises(LiveRejected, match='settlement_net_payout_mismatch'):
            reconcile(desk)
        assert slug not in desk.book.settled and desk.book.integrity_error == 'settlement_net_payout_mismatch'
        assert not any(row.kind=='speeddesk_live_settlement' for row in desk.ledger.iter_receipts())
    finally:
        desk.close()
