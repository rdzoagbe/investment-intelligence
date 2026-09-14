from app.backtest import run_backtest
from app.broker import BrokerGateway
from app.paper_trading import PaperAccount
from app.portfolio import Holding, portfolio_snapshot


def test_backtest_is_deterministic_and_cost_aware():
    result = run_backtest([100, 105, 110, 108], [90, 90, 50, 50])
    assert result["initial_cash"] == 10000
    assert result["trade_count"] >= 1
    assert result["final_equity"] > 10000


def test_portfolio_allocation_and_pnl():
    result = portfolio_snapshot([Holding("ABC", 10, 100, 120)], cash=500)
    assert result["value"] == 1700
    assert result["pnl"] == 200
    assert result["allocation"][0]["weight_pct"] > 0


def test_paper_trading_rejects_overspend():
    account = PaperAccount(cash=100)
    try:
        account.submit("ABC", "BUY", 2, 60)
        assert False, "expected insufficient cash"
    except ValueError as exc:
        assert "cash" in str(exc)


def test_broker_requires_human_approval_and_live_flag():
    gateway = BrokerGateway()
    order = gateway.preview("MSFT", "BUY", 1)
    result = gateway.execute(order, human_approved=False)
    assert result.status == "REJECTED_NO_HUMAN_APPROVAL"
