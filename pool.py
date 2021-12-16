import os
from pyteal import *

gov_key = Bytes("gov")
pool_key = Bytes("p")

action_boot = Bytes("boot")
action_fund = Bytes("fund")
action_mint = Bytes("mint")
action_burn = Bytes("burn")
action_swap = Bytes("swap")
action_update = Bytes("update")

fee = Int(5)
total_supply = Int(int(1e10))
scale = Int(1000)


def approval(asset_a: int, asset_b: int):
    # Don't allow this contract to be created if a > b
    assert asset_a < asset_b

    asset_a = Int(asset_a)
    asset_b = Int(asset_b)

    mine = Global.current_application_address()

    pool_token = App.globalGet(pool_key)

    has_correct_assets = And(Txn.assets[0] == asset_a, Txn.assets[1] == asset_b)

    @Subroutine(TealType.uint64)
    def mint_tokens(issued, asup, bsup, aamt, bamt):
        return If((aamt / asup) < (bamt / bsup), aamt / asup, bamt / bsup) * issued

    @Subroutine(TealType.uint64)
    def burn_tokens(issued, sup, amt):
        return sup * (amt / issued)

    @Subroutine(TealType.uint64)
    def swap_tokens(inamt, insup, outsup):
        factor = scale - fee
        return (inamt * factor * outsup) / ((insup * scale) + (inamt * factor))

    @Subroutine(TealType.uint64)
    def mint():
        well_formed_mint = And(
            Global.group_size() == Int(3),  # App call, Asset A, Asset B
            has_correct_assets,
            Gtxn[0].type_enum() == TxnType.ApplicationCall,
            Gtxn[0].assets[0] == Gtxn[1].xfer_asset(),
            Gtxn[0].assets[1] == Gtxn[2].xfer_asset(),
            Gtxn[1].type_enum() == TxnType.AssetTransfer,
            Gtxn[1].asset_receiver() == mine,
            Gtxn[1].xfer_asset() == asset_a,
            Gtxn[1].asset_amount() > Int(0),
            Gtxn[1].sender() == Gtxn[0].sender(),
            Gtxn[2].type_enum() == TxnType.AssetTransfer,
            Gtxn[2].asset_receiver() == mine,
            Gtxn[2].xfer_asset() == asset_b,
            Gtxn[2].asset_amount() > Int(0),
            Gtxn[2].sender() == Gtxn[0].sender(),
        )

        pool_bal = AssetHolding.balance(mine, pool_token)
        a_bal = AssetHolding.balance(mine, asset_a)
        b_bal = AssetHolding.balance(mine, asset_b)

        return Seq(
            # Init MaybeValues
            pool_bal,
            a_bal,
            b_bal,
            # Check that the transaction is constructed correctly
            Assert(well_formed_mint),
            # Check that we have these things
            Assert(And(pool_bal.hasValue(), a_bal.hasValue(), b_bal.hasValue())),
            # mint tokens
            axfer(
                Gtxn[0].sender(),
                pool_token,
                mint_tokens(
                    total_supply - pool_bal.value(),
                    a_bal.value(),
                    b_bal.value(),
                    Gtxn[1].asset_amount(),
                    Gtxn[2].asset_amount(),
                ),
            ),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def burn():

        well_formed_burn = And(
            Global.group_size() == Int(2),
            has_correct_assets,
            Gtxn[0].type_enum() == TxnType.ApplicationCall,
            Gtxn[1].type_enum() == TxnType.AssetTransfer,
            Gtxn[1].asset_receiver() == mine,
            Gtxn[1].xfer_asset() == pool_token,
        )

        pool_bal = AssetHolding.balance(mine, pool_token)
        a_bal = AssetHolding.balance(mine, asset_a)
        b_bal = AssetHolding.balance(mine, asset_b)

        return Seq(
            pool_bal,
            a_bal,
            b_bal,
            Assert(well_formed_burn),
            Assert(And(pool_bal.hasValue(), a_bal.hasValue(), b_bal.hasValue())),
            # Send back a
            axfer(
                Gtxn[1].sender(),
                asset_a,
                burn_tokens(
                    total_supply - pool_bal.value(),
                    a_bal.value(),
                    Gtxn[1].asset_amount(),
                ),
            ),
            # Send back b
            axfer(
                Gtxn[1].sender(),
                asset_b,
                burn_tokens(
                    total_supply - pool_bal.value(),
                    b_bal.value(),
                    Gtxn[1].asset_amount(),
                ),
            ),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def swap():
        in_id = Gtxn[1].xfer_asset()
        out_id = If(Gtxn[1].xfer_asset() == asset_a, asset_b, asset_a)

        well_formed_swap = And(
            Global.group_size() == Int(2),
            has_correct_assets,
            Gtxn[0].type_enum() == TxnType.ApplicationCall,
            Gtxn[1].type_enum() == TxnType.AssetTransfer,
            Or(in_id == asset_a, in_id == asset_b),
            Gtxn[1].asset_amount() > Int(0),
        )

        in_sup = AssetHolding.balance(mine, in_id)
        out_sup = AssetHolding.balance(mine, out_id)

        return Seq(
            in_sup,
            out_sup,
            Assert(well_formed_swap),
            Assert(And(in_sup.hasValue(), out_sup.hasValue())),
            axfer(
                Gtxn[1].sender(),
                out_id,
                swap_tokens(Gtxn[1].asset_amount(), in_sup.value(), out_sup.value()),
            ),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def is_governor():
        gov = App.globalGetEx(Int(0), gov_key)
        return Seq(
            gov,
            Txn.sender() == If(gov.hasValue(), gov.value(), Global.creator_address()),
        )

    @Subroutine(TealType.uint64)
    def set_governor(new_gov):
        return If(is_governor(), Seq(App.globalPut(gov_key, new_gov), Int(1)), Int(0))

    @Subroutine(TealType.uint64)
    def bootstrap():
        well_formed_bootstrap = And(
            Global.group_size() == Int(1),
            Gtxn[0].type_enum() == TxnType.ApplicationCall,
            has_correct_assets,
        )

        return Seq(
            Assert(well_formed_bootstrap),
            Assert(is_governor()),
            create_pool_token(asset_a, asset_b),
            opt_in(asset_a),
            opt_in(asset_b),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def fund():
        well_formed_fund = And(
            Global.group_size() == Int(3),
            Gtxn[0].type_enum() == TxnType.ApplicationCall,
            has_correct_assets,
            Gtxn[1].type_enum() == TxnType.AssetTransfer,
            Gtxn[1].xfer_asset() == asset_a,
            Gtxn[1].asset_amount() > Int(0),
            Gtxn[1].sender() == Gtxn[0].sender(),
            Gtxn[2].type_enum() == TxnType.AssetTransfer,
            Gtxn[2].xfer_asset() == asset_b,
            Gtxn[2].asset_amount() > Int(0),
            Gtxn[2].sender() == Gtxn[0].sender(),
        )

        return Seq(
            Assert(well_formed_fund),
            axfer(
                Gtxn[0].sender(),
                pool_token,
                Sqrt(Gtxn[1].asset_amount() * Gtxn[2].asset_amount()) - scale,
            ),
            Int(1),
        )

    @Subroutine(TealType.none)
    def axfer(rx: TealType.bytes, aid: TealType.uint64, amt: TealType.uint64):
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: aid,
                    TxnField.asset_amount: amt,
                    TxnField.asset_receiver: rx,
                }
            ),
            InnerTxnBuilder.Submit(),
        )

    @Subroutine(TealType.none)
    def opt_in(aid: TealType.uint64):
        return axfer(mine, aid, Int(0))

    @Subroutine(TealType.none)
    def create_pool_token(a: TealType.uint64, b: TealType.uint64):
        una = AssetParam.unitName(a)  # TODO: use asset id instead?
        unb = AssetParam.unitName(b)  # TODO: use asset id instead?

        return Seq(
            una,
            unb,
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetConfig,
                    TxnField.config_asset_name: Concat(
                        Bytes("DPT-"), una.value(), Bytes("-"), unb.value()
                    ),
                    TxnField.config_asset_unit_name: Bytes("dpt"),
                    TxnField.config_asset_total: total_supply,
                    TxnField.config_asset_decimals: Int(3),
                    TxnField.config_asset_manager: mine,
                    TxnField.config_asset_reserve: mine,
                }
            ),
            InnerTxnBuilder.Submit(),
            App.globalPut(pool_key, InnerTxn.created_asset_id()),
        )

    router = Cond(
        # Users
        [Txn.application_args[0] == action_mint, mint()],
        [Txn.application_args[0] == action_burn, burn()],
        [Txn.application_args[0] == action_swap, swap()],
        # Admin
        [Txn.application_args[0] == action_boot, bootstrap()],
        [Txn.application_args[0] == action_fund, fund()],
        [Txn.application_args[0] == action_update, set_governor(Txn.accounts[1])],
    )

    return Cond(
        [Txn.application_id() == Int(0), Int(1)],
        [Txn.on_completion() == OnComplete.DeleteApplication, is_governor()],
        [Txn.on_completion() == OnComplete.UpdateApplication, is_governor()],
        [Txn.on_completion() == OnComplete.CloseOut, Int(1)],
        [Txn.on_completion() == OnComplete.OptIn, Int(0)],
        [Txn.on_completion() == OnComplete.NoOp, router],
    )


def clear():
    return Return(Int(1))


if __name__ == "__main__":
    path = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(path, "approval.teal"), "w") as f:
        f.write(compileTeal(approval(10, 100), mode=Mode.Application, version=5))

    with open(os.path.join(path, "clear.teal"), "w") as f:
        f.write(compileTeal(clear(), mode=Mode.Application, version=5))
