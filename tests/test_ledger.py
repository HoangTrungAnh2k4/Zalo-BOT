from datetime import datetime, timezone

import pytest

from app.models import Transaction
from app.services.ledger import LedgerError


@pytest.fixture
def setup(service):
    nam = service.get_or_create_user("u1", "Nam")
    ledger, me = service.create_ledger(nam, "Đà Lạt")
    service.add_members(ledger, ["Linh", "Hòa"])
    return nam, ledger, me


def names(members):
    return [m.name for m in members]


def test_create_ledger_sets_active(service, setup):
    nam, ledger, me = setup
    assert service.active_ledger(nam).id == ledger.id
    assert len(ledger.invite_code) == 6
    assert names(service.members(ledger)) == ["Nam", "Linh", "Hòa"]
    assert me.user_id == "u1"


def test_add_members_skips_duplicates(service, setup):
    _, ledger, _ = setup
    added, skipped = service.add_members(ledger, ["linh", "Tú"])
    assert (added, skipped) == (["Tú"], ["Linh"])


@pytest.mark.parametrize("bad", ["tất cả", "mình", "123"])
def test_add_members_rejects_reserved_names(service, setup, bad):
    _, ledger, _ = setup
    with pytest.raises(LedgerError):
        service.add_members(ledger, [bad])


def test_find_member_accent_insensitive_and_partial(service, setup):
    _, ledger, me = setup
    assert service.find_member(ledger, "hoa").name == "Hòa"
    assert service.find_member(ledger, "tôi", me) is me
    service.add_members(ledger, ["Trần Thị Mai"])
    assert service.find_member(ledger, "Mai").name == "Trần Thị Mai"


def test_find_member_suggests_close_name(service, setup):
    _, ledger, _ = setup
    with pytest.raises(LedgerError, match="Linh"):
        service.find_member(ledger, "Lihn")


def test_expense_balances_sum_to_zero(service, setup):
    nam, ledger, me = setup
    everyone = service.resolve_participants(ledger, me, None, [])
    service.add_expense(ledger, me, 100_000, "cafe", everyone, nam)
    balances = service.balances(ledger)
    assert sum(balances.values()) == 0
    assert sorted(balances.values()) == [-33_333, -33_333, 66_666]


def test_expense_with_targets_and_excludes(service, setup):
    nam, ledger, me = setup
    some = service.resolve_participants(ledger, me, ["Linh", "Hòa"], [])
    assert names(some) == ["Linh", "Hòa"]
    others = service.resolve_participants(ledger, me, None, ["hoa"])
    assert names(others) == ["Nam", "Linh"]
    spaced = service.resolve_participants(ledger, me, ["Linh Hòa"], [])
    assert names(spaced) == ["Linh", "Hòa"]
    with pytest.raises(LedgerError):
        service.resolve_participants(ledger, me, ["Linh"], ["Linh"])


def test_payment_settles_debt(service, setup):
    nam, ledger, me = setup
    linh = service.find_member(ledger, "Linh")
    everyone = service.resolve_participants(ledger, me, None, [])
    service.add_expense(ledger, me, 300_000, "lẩu", everyone, nam)
    service.add_payment(ledger, linh, me, 100_000, nam)
    balances = service.balances(ledger)
    assert balances[linh.id] == 0
    assert balances[me.id] == 100_000
    transfers = service.settlement(ledger)
    assert [(t.creditor, t.amount) for t in transfers] == [(me.id, 100_000)]


def test_join_and_link(service, setup):
    _, ledger, _ = setup
    linh_user = service.get_or_create_user("u2", "Linh Trần")
    joined, member, already = service.join_ledger(linh_user, ledger.invite_code.lower())
    assert (joined.id, member.name, already) == (ledger.id, "Linh Trần", False)
    linked = service.link_member(ledger, linh_user, "Linh")
    assert linked.user_id == "u2"
    # Tên tạm "Linh Trần" chưa có lịch sử nên bị xóa, không còn bị tính vào "tất cả".
    assert names(service.members(ledger)) == ["Nam", "Linh", "Hòa"]
    assert service.join_ledger(linh_user, ledger.invite_code)[2] is True


def test_join_links_unclaimed_member_with_same_name(service, setup):
    _, ledger, _ = setup
    hoa = service.get_or_create_user("u3", "Hoà")  # dấu đặt khác vị trí vẫn khớp
    _, member, _ = service.join_ledger(hoa, ledger.invite_code)
    assert member.name == "Hòa"
    assert member.user_id == "u3"


def test_join_unknown_code(service, setup):
    linh_user = service.get_or_create_user("u2", "Linh")
    with pytest.raises(LedgerError):
        service.join_ledger(linh_user, "ZZZZZZ")


def test_link_member_taken(service, setup):
    _, ledger, _ = setup
    other = service.get_or_create_user("u9", "Ai đó")
    service.join_ledger(other, ledger.invite_code)
    with pytest.raises(LedgerError):
        service.link_member(ledger, other, "Nam")


def test_delete_permissions(service, setup):
    nam, ledger, me = setup
    linh_user = service.get_or_create_user("u2", "Linh")
    service.join_ledger(linh_user, ledger.invite_code)
    linh = service.member_of(ledger, linh_user)
    tx = service.add_expense(ledger, linh, 60_000, "trà", [linh, me], linh_user)
    stranger = service.get_or_create_user("u3", "Hòa")
    service.join_ledger(stranger, ledger.invite_code)
    with pytest.raises(LedgerError):
        service.delete_transaction(ledger, stranger, tx)
    service.delete_transaction(ledger, nam, tx)  # chủ sổ được xóa
    assert service.session.get(Transaction, tx.id) is None
    assert set(service.balances(ledger).values()) == {0}


def test_group_ledger_is_per_chat(service):
    nam = service.get_or_create_user("u1", "Nam")
    first = service.ledger_for_group("g1", nam)
    assert service.ledger_for_group("g1", nam).id == first.id
    assert service.ledger_for_group("g2", nam).id != first.id


def test_ensure_member_avoids_name_clash(service):
    a = service.get_or_create_user("u1", "Nam")
    b = service.get_or_create_user("u2", "Nam")
    ledger = service.ledger_for_group("g1", a)
    assert service.ensure_member(ledger, b).name == "Nam (2)"


def test_payment_qr(service, setup):
    nam, ledger, me = setup
    linh_user = service.get_or_create_user("u2", "Linh")
    service.join_ledger(linh_user, ledger.invite_code)
    linh = service.member_of(ledger, linh_user)
    everyone = service.resolve_participants(ledger, me, None, [])
    service.add_expense(ledger, me, 300_000, "lẩu", everyone, nam)

    with pytest.raises(LedgerError, match="tài khoản"):
        service.payment_qr(ledger, linh, me)
    service.set_bank_account(nam, "vcb", "0123 456 789", "Nguyễn Văn Nam")
    amount, url = service.payment_qr(ledger, linh, me)
    assert amount == 100_000
    assert url.startswith("https://img.vietqr.io/image/VCB-0123456789-compact2.png?amount=100000")
    assert "accountName=NGUYEN%20VAN%20NAM" in url
    with pytest.raises(LedgerError):
        service.payment_qr(ledger, me, linh)  # Nam không nợ Linh


def test_monthly_stats(service, setup):
    nam, ledger, me = setup
    everyone = service.resolve_participants(ledger, me, None, [])
    service.add_expense(ledger, me, 300_000, "lẩu", everyone, nam)
    service.add_expense(ledger, me, 90_000, "trà sữa", everyone, nam)
    linh = service.find_member(ledger, "Linh")
    service.add_payment(ledger, linh, me, 50_000, nam)  # không tính vào thống kê chi tiêu

    stats = service.monthly_stats(ledger)
    assert (stats.count, stats.total) == (2, 390_000)
    assert stats.paid_by == [("Nam", 390_000)]
    assert dict(stats.consumed_by) == {"Nam": 130_000, "Linh": 130_000, "Hòa": 130_000}
    assert [tx.description for tx in stats.top] == ["lẩu", "trà sữa"]

    later = service.monthly_stats(ledger, now=datetime(2099, 1, 15, tzinfo=timezone.utc))
    assert later.count == 0
