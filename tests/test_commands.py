import pytest

from app.commands import (
    CommandError,
    parse_chiho_args,
    parse_command,
    parse_expense_args,
    parse_payment_args,
    parse_qr_args,
    split_names,
)


def test_parse_slash_command():
    cmd = parse_command("/chi 300k lẩu")
    assert (cmd.name, cmd.args) == ("chi", "300k lẩu")


def test_parse_command_after_group_mention():
    cmd = parse_command("@Bot Chia Tiền /chi 90k trà sữa")
    assert (cmd.name, cmd.args) == ("chi", "90k trà sữa")


def test_parse_command_with_accents():
    assert parse_command("/chọnsổ 2").name == "chonso"
    assert parse_command("/TATOAN").name == "tatoan"


def test_bare_command_only_when_allowed():
    assert parse_command("chi 300k lẩu") is None
    assert parse_command("chi 300k lẩu", allow_bare=True).name == "chi"
    assert parse_command("xin chào", allow_bare=True) is None


def test_slash_inside_text_is_not_a_command():
    assert parse_command("hẹn 20/10 nhé") is None


def test_unknown_command():
    cmd = parse_command("/abc")
    assert (cmd.name, cmd.raw_name) == ("unknown", "abc")


def test_expense_for_everyone():
    args = parse_expense_args("300k lẩu nướng")
    assert (args.amount, args.description, args.targets, args.excludes) == (
        300_000, "lẩu nướng", None, [],
    )


def test_expense_for_some():
    args = parse_expense_args("1tr2 tiền phòng cho Nam, Linh")
    assert args.amount == 1_200_000
    assert args.description == "tiền phòng"
    assert args.targets == ["Nam", "Linh"]


def test_expense_everyone_except():
    args = parse_expense_args("450k xăng cho tất cả trừ Hòa")
    assert (args.targets, args.excludes) == (None, ["Hòa"])
    args = parse_expense_args("450k xăng cho tat ca ngoai tru Hoa va Nam")
    assert (args.targets, args.excludes) == (None, ["Hoa", "Nam"])


def test_expense_uses_last_cho():
    args = parse_expense_args("200k quà cho mẹ cho Nam và Linh")
    assert args.description == "quà cho mẹ"
    assert args.targets == ["Nam", "Linh"]


def test_expense_amount_with_unit_word():
    args = parse_expense_args("50 nghìn cafe")
    assert (args.amount, args.description) == (50_000, "cafe")


def test_expense_without_description():
    assert parse_expense_args("200k cho Nam").description == ""


@pytest.mark.parametrize("text", ["", "lẩu 300k", "300 lẩu", "450k xăng cho tất cả trừ"])
def test_expense_errors(text):
    with pytest.raises(CommandError):
        parse_expense_args(text)


def test_chiho():
    payer, args = parse_chiho_args("Nguyễn Nam 200k cafe cho Linh")
    assert payer == "Nguyễn Nam"
    assert (args.amount, args.description, args.targets) == (200_000, "cafe", ["Linh"])
    with pytest.raises(CommandError):
        parse_chiho_args("200k cafe")


def test_payment_both_orders():
    assert parse_payment_args("Linh 150k") == ("Linh", 150_000)
    assert parse_payment_args("150k cho Linh") == ("Linh", 150_000)
    with pytest.raises(CommandError):
        parse_payment_args("Linh")
    with pytest.raises(CommandError):
        parse_payment_args("150k")


def test_qr_args():
    assert parse_qr_args("Linh") == ("Linh", None)
    assert parse_qr_args("Linh 50k") == ("Linh", 50_000)
    with pytest.raises(CommandError):
        parse_qr_args("")


def test_split_names():
    assert split_names("Nam, Linh và Hòa") == ["Nam", "Linh", "Hòa"]
    assert split_names("Nam Anh; Linh & Hòa + Tú") == ["Nam Anh", "Linh", "Hòa", "Tú"]
