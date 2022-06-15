import os
from typing import Tuple
from algosdk import abi as sdk_abi
from pyteal import *

# WARNING: THIS IS NOT PROODUCTION LEVEL CODE

fee = Int(5)
total_supply = Int(int(1e10))
scale = Int(1000)

gov_key = Bytes("gov")
pool_key = Bytes("p")

me = Global.current_application_address()
pool_token = App.globalGet(pool_key)
is_governor = Seq(
    gov := App.globalGetEx(Int(0), gov_key),
    Txn.sender() == If(gov.hasValue(), gov.value(), Global.creator_address()),
)

# Methods that compute number of tokens to return  in different cases
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


# Methods to perform inner transactions


@Subroutine(TealType.none)
def do_axfer(rx, aid, amt):
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
def do_opt_in(aid):
    return do_axfer(me, aid, Int(0))


@Subroutine(TealType.none)
def do_create_pool_token(a, b):
    return Seq(
        una := AssetParam.unitName(a),
        unb := AssetParam.unitName(b),
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
                TxnField.config_asset_manager: me,
                TxnField.config_asset_reserve: me,
            }
        ),
        InnerTxnBuilder.Submit(),
        App.globalPut(pool_key, InnerTxn.created_asset_id()),
    )


def build_program(asset_a: int, asset_b: int) -> Tuple[str, str, sdk_abi.Contract]:
    assert asset_a < asset_b

    asset_a = Int(asset_a)
    asset_b = Int(asset_b)

    router = Router(
        "demo-amm",
        BareCallActions(
            no_op=OnCompleteAction.create_only(Approve()),
            update_application=OnCompleteAction.always(Return(is_governor)),
            delete_application=OnCompleteAction.always(Return(is_governor)),
            close_out=OnCompleteAction.never(),
            opt_in=OnCompleteAction.never(),
            clear_state=OnCompleteAction.call_only(Approve()),
        ),
    )

    @router.method
    def mint(
        a_xfer: abi.AssetTransferTransaction,
        b_xfer: abi.AssetTransferTransaction,
        pool_asset: abi.Asset,
        a_asset: abi.Asset,
        b_asset: abi.Asset,
    ):
        """mint pool tokens given some amount of asset A and asset B"""

        well_formed_mint = And(
            Global.group_size() == Int(3),  # Asset A, Asset B, App call
            a_asset.asset_id() == asset_a,
            b_asset.asset_id() == asset_b,
        )

        valid_asset_a_xfer = And(
            a_xfer.get().type_enum() == TxnType.AssetTransfer,
            a_xfer.get().asset_receiver() == me,
            a_xfer.get().xfer_asset() == asset_a,
            a_xfer.get().asset_amount() > Int(0),
            a_xfer.get().sender() == Txn.sender(),
        )

        valid_asset_b_xfer = And(
            b_xfer.get().type_enum() == TxnType.AssetTransfer,
            b_xfer.get().asset_receiver() == me,
            b_xfer.get().xfer_asset() == asset_b,
            b_xfer.get().asset_amount() > Int(0),
            b_xfer.get().sender() == Txn.sender(),
        )

        return Seq(
            # Check that the transaction is constructed correctly
            Assert(well_formed_mint),
            Assert(valid_asset_a_xfer),
            Assert(valid_asset_b_xfer),
            # Check that we have these things
            pool_bal := pool_asset.holding(me).balance(),
            a_bal := a_asset.holding(me).balance(),
            b_bal := b_asset.holding(me).balance(),
            Assert(And(pool_bal.hasValue(), a_bal.hasValue(), b_bal.hasValue())),
            # mint tokens
            do_axfer(
                Txn.sender(),
                pool_token,
                mint_tokens(
                    total_supply - pool_bal.value(),
                    a_bal.value(),
                    b_bal.value(),
                    a_xfer.get().asset_amount(),
                    b_xfer.get().asset_amount(),
                ),
            ),
        )

    @router.method
    def burn(
        pool_xfer: abi.AssetTransferTransaction,
        pool_asset: abi.Asset,
        a_asset: abi.Asset,
        b_asset: abi.Asset,
    ):
        """burn pool tokens to get back some amount of asset A and asset B"""

        well_formed_burn = And(
            Global.group_size() == Int(2),
            pool_asset.asset_id() == pool_token,
            a_asset.asset_id() == asset_a,
            b_asset.asset_id() == asset_b,
        )

        valid_pool_xfer = And(
            pool_xfer.get().type_enum() == TxnType.AssetTransfer,
            pool_xfer.get().asset_receiver() == me,
            pool_xfer.get().xfer_asset() == pool_token,
        )

        return Seq(
            Assert(well_formed_burn),
            Assert(valid_pool_xfer),
            pool_bal := pool_asset.holding(me).balance(),
            a_bal := a_asset.holding(me).balance(),
            b_bal := b_asset.holding(me).balance(),
            Assert(And(pool_bal.hasValue(), a_bal.hasValue(), b_bal.hasValue())),
            # Send back commensurate amt of a
            do_axfer(
                Txn.sender(),
                asset_a,
                burn_tokens(
                    total_supply - pool_bal.value(),
                    a_bal.value(),
                    pool_xfer.get().asset_amount(),
                ),
            ),
            # Send back commensurate amt of b
            do_axfer(
                Txn.sender(),
                asset_b,
                burn_tokens(
                    total_supply - pool_bal.value(),
                    b_bal.value(),
                    pool_xfer.get().asset_amount(),
                ),
            ),
        )

    @router.method
    def swap(
        swap_xfer: abi.AssetTransferTransaction, a_asset: abi.Asset, b_asset: abi.Asset
    ):
        """Swap some amount of either asset A or asset B for the other"""
        well_formed_swap = And(
            Global.group_size() == Int(2),
            a_asset.asset_id() == asset_a,
            b_asset.asset_id() == asset_b,
        )

        valid_swap_xfer = And(
            swap_xfer.get().type_enum() == TxnType.AssetTransfer,
            Or(
                swap_xfer.get().xfer_asset() == asset_a,
                swap_xfer.get().xfer_asset() == asset_b,
            ),
            swap_xfer.get().asset_amount() > Int(0),
        )

        out_id = If(swap_xfer.get().xfer_asset() == asset_a, asset_b, asset_a)
        in_id = swap_xfer.get().xfer_asset()

        return Seq(
            Assert(well_formed_swap),
            Assert(valid_swap_xfer),
            in_sup := AssetHolding.balance(me, in_id),
            out_sup := AssetHolding.balance(me, out_id),
            Assert(And(in_sup.hasValue(), out_sup.hasValue())),
            do_axfer(
                Txn.sender(),
                out_id,
                swap_tokens(
                    swap_xfer.get().asset_amount(), in_sup.value(), out_sup.value()
                ),
            ),
        )

    @router.method
    def set_governor(new_governor: abi.Account):
        """sets the governor of the contract, may only be called by the current governor"""
        return Seq(Assert(is_governor), App.globalPut(gov_key, new_governor.address()))

    @router.method
    def bootstrap(a_asset: abi.Asset, b_asset: abi.Asset, *, output: abi.Uint64):
        """bootstraps the contract by opting into the assets and creating the pool token"""
        well_formed_bootstrap = And(
            Global.group_size() == Int(1),
            a_asset.asset_id() == asset_a,
            b_asset.asset_id() == asset_b,
        )

        return Seq(
            Assert(is_governor),
            Assert(well_formed_bootstrap),
            do_create_pool_token(asset_a, asset_b),
            do_opt_in(asset_a),
            do_opt_in(asset_b),
            output.set(pool_token),
        )

    @router.method
    def fund(
        a_xfer: abi.AssetTransferTransaction,
        b_xfer: abi.AssetTransferTransaction,
        pool_asset: abi.Asset,
        a_asset: abi.Asset,
        b_asset: abi.Asset,
    ):
        """fund the contract with some asset A and asset B, separate from normal `mint` since it uses a slightly different initial formula for minting tokens"""
        well_formed_fund = And(
            Global.group_size() == Int(3),
            pool_asset.asset_id() == pool_token,
            a_asset.asset_id() == asset_a,
            b_asset.asset_id() == asset_b,
        )

        valid_a_xfer = And(
            a_xfer.get().type_enum() == TxnType.AssetTransfer,
            a_xfer.get().xfer_asset() == asset_a,
            a_xfer.get().asset_amount() > Int(0),
            a_xfer.get().sender() == Txn.sender(),
        )

        valid_b_xfer = And(
            b_xfer.get().type_enum() == TxnType.AssetTransfer,
            b_xfer.get().xfer_asset() == asset_b,
            b_xfer.get().asset_amount() > Int(0),
            b_xfer.get().sender() == Txn.sender(),
        )

        return Seq(
            Assert(well_formed_fund),
            Assert(valid_a_xfer),
            Assert(valid_b_xfer),
            a_bal := a_asset.holding(me).balance(),
            b_bal := b_asset.holding(me).balance(),
            Assert(
                # Make sure this is the first time we've been called by
                And(
                    a_bal.value() == a_xfer.get().asset_amount(),
                    b_bal.value() == b_xfer.get().asset_amount(),
                )
            ),
            do_axfer(
                Txn.sender(),
                pool_token,
                Sqrt(a_xfer.get().asset_amount() * b_xfer.get().asset_amount()) - scale,
            ),
        )

    return router.compile_program(
        version=6, optimize=OptimizeOptions(scratch_slots=True)
    )


if __name__ == "__main__":
    approval, clear, contract = build_program(10, 100)

    path = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(path, "contract.json"), "w") as f:
        import json

        f.write(json.dumps(contract.dictify(), indent=2))

    with open(os.path.join(path, "approval.teal"), "w") as f:
        f.write(approval)

    with open(os.path.join(path, "clear.teal"), "w") as f:
        f.write(clear)
