import os
from pyteal import *


gov_key = Bytes("gov")
pool_key = Bytes("p")
ratio_key = Bytes("rab")

action_deposit = Bytes("deposit")
action_withdraw = Bytes("withdraw")
action_swap = Bytes("swap")

action_admin_init = Bytes("admin_init")
action_admin_update = Bytes("admin_update")


#TODO: is this enough?
scale = Int(10000)

@Subroutine(TealType.uint64)
def scaleup(n: TealType.uint64) -> Expr:
    return n * scale

@Subroutine(TealType.uint64)
def scaledown(n: TealType.uint64) -> Expr:
    return n / scale


def approval(asset_a: int, asset_b: int):
    # Don't allow this contract to be created if a > b
    assert asset_a < asset_b

    asset_a = Int(asset_a)
    asset_b = Int(asset_b)

    is_correct_assets = And(Txn.assets[0] == asset_a, Txn.assets[1] == asset_b)

    @Subroutine(TealType.uint64)
    def update_ratio():
        abal = AssetHolding.balance(Global.current_application_address(), asset_a)
        bbal = AssetHolding.balance(Global.current_application_address(), asset_b)
        return Seq(
            abal,
            bbal,
            Assert(And(abal.hasValue(), bbal.hasValue())),
            App.globalPut(ratio_key, scaleup(abal.value()) / bbal.value()), # Scale up the numerator 
            scaleup(abal.value()) / bbal.value()
        )

    @Subroutine(TealType.uint64)
    def deposit():
        ratio = ScratchVar()

        # Use globalGetEx with 0 as current app, since we dont know if this is set yet
        ratio_state = App.globalGetEx(Int(0), ratio_key)

        well_formed_deposit = And(
            Global.group_size() == Int(3),  # App call, Asset A, Asset B
            is_correct_assets,
            Gtxn[0].type_enum() == TxnType.ApplicationCall,
            Gtxn[0].assets[0] == Gtxn[1].xfer_asset(),
            Gtxn[0].assets[1] == Gtxn[2].xfer_asset(),
            Gtxn[1].type_enum() == TxnType.AssetTransfer,
            Gtxn[1].asset_receiver() == Global.current_application_address(),
            Gtxn[1].xfer_asset() == asset_a,
            Gtxn[2].type_enum() == TxnType.AssetTransfer,
            Gtxn[2].asset_receiver() == Global.current_application_address(),
            Gtxn[2].xfer_asset() == asset_b,
            Gtxn[0].sender() == Gtxn[1].sender(),
            Gtxn[1].sender() == Gtxn[2].sender(),
        )

        pool_token = App.globalGet(pool_key)

        return Seq(
            # Check that the transaction is constructed correctly
            Assert(well_formed_deposit),
            # Init the MaybeValue of global state
            ratio_state,

            # If we already have a ratio for this, use it. Otherwise, set the ratio based on the deposit
            ratio.store(
                If(ratio_state.hasValue(), ratio_state.value(), update_ratio())
            ),

            # TODO allow for margin of error?
            #Assert(Gtxn[2].asset_amount() * ratio.load() == Gtxn[1].asset_amount()),

            # Return some number of pool tokens
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: pool_token,
                    TxnField.asset_amount: (Gtxn[1].asset_amount() / ratio.load()) + Gtxn[2].asset_amount(),
                    TxnField.asset_receiver: Txn.accounts[0],
                }
            ),
            InnerTxnBuilder.Submit(),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def withdraw():
        pool_token = App.globalGet(pool_key)

        well_formed_withdrawl = And(
            Global.group_size() == Int(2),  # App call, Pool Token xfer
            is_correct_assets,  # Must have the tokens
            Gtxn[0].type_enum() == TxnType.ApplicationCall,
            Gtxn[1].type_enum() == TxnType.AssetTransfer,
            Gtxn[1].asset_receiver() == Global.current_application_address(),
            Gtxn[1].xfer_asset() == pool_token,
        )

        # Return N*ratioA A tokens and N*ratiob B tokens
        return Seq(
            Assert(well_formed_withdrawl),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: asset_a,
                    TxnField.asset_amount: Gtxn[1].asset_amount()
                    / App.globalGet(ratio_key),
                    TxnField.asset_receiver: Txn.sender(),
                }
            ),
            InnerTxnBuilder.Submit(),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: asset_b,
                    TxnField.asset_amount: Gtxn[1].asset_amount()
                    / App.globalGet(ratio_key),
                    TxnField.asset_receiver: Txn.sender(),
                }
            ),
            InnerTxnBuilder.Submit(),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def swap():
        # A index is strictly < B index
        return If(Gtxn[1].xfer_asset() == asset_a, swapAB(), swapBA())

    @Subroutine(TealType.uint64)
    def swapAB():
        well_formed_swap = And(
            Global.group_size() == Int(2),
            is_correct_assets,
            Gtxn[0].type_enum() == TxnType.ApplicationCall,
            Gtxn[1].type_enum() == TxnType.AssetTransfer,
            Gtxn[1].xfer_asset() == asset_a,
            Gtxn[1].asset_amount() > Int(0),
        )

        return Seq(
            Assert(well_formed_swap),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: asset_b,
                    TxnField.asset_amount: Gtxn[1].asset_amount() / App.globalGet(ratio_key),
                }
            ),
            InnerTxnBuilder.Submit(),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def swapBA():
        well_formed_swap = And(
            Global.group_size() == Int(2),
            is_correct_assets,
            Gtxn[0].type_enum() == TxnType.ApplicationCall,
            Gtxn[1].type_enum() == TxnType.AssetTransfer,
            Gtxn[1].xfer_asset() == asset_b,
            Gtxn[1].asset_amount() > Int(0),
        )

        return Seq(
            Assert(well_formed_swap),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: asset_a,
                    TxnField.asset_amount: scaledown(Gtxn[1].asset_amount() * App.globalGet(ratio_key)),
                    TxnField.asset_receiver: Gtxn[1].sender()
                }
            ),
            InnerTxnBuilder.Submit(),
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
    def init_pool():
        return If(
            is_governor(), 
            Seq(
                create_pool_token(asset_a, asset_b), 
                opt_in(asset_a),
                opt_in(asset_b),
                Int(1)
            ),
            Int(0)
        )

    @Subroutine(TealType.none)
    def opt_in(aid: TealType.uint64):
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: aid,
                TxnField.asset_amount: Int(0),
                TxnField.asset_receiver: Global.current_application_address(),
            }),
            InnerTxnBuilder.Submit(),
        )

    @Subroutine(TealType.none)
    def create_pool_token(a: TealType.uint64, b: TealType.uint64):
        una = AssetParam.unitName(a) # TODO: use asset id instead?
        unb = AssetParam.unitName(b) # TODO: use asset id instead?

        return Seq(
            una, unb,
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetConfig,
                    TxnField.config_asset_name: Concat(Bytes("DPT-"), una.value(), Bytes("-"), unb.value()),
                    TxnField.config_asset_unit_name: Bytes("dpt"),
                    TxnField.config_asset_total: Int(int(1e9)),
                    TxnField.config_asset_decimals: Int(0),
                    TxnField.config_asset_manager: Global.current_application_address(),
                    TxnField.config_asset_reserve: Global.current_application_address(),
                }
            ),
            InnerTxnBuilder.Submit(),
            App.globalPut(pool_key, InnerTxn.created_asset_id()),
        )

    router = Cond(
        # Users
        [Txn.application_args[0] == action_deposit, deposit()],
        [Txn.application_args[0] == action_withdraw, withdraw()],
        [Txn.application_args[0] == action_swap, swap()],
        # Admin
        [Txn.application_args[0] == action_admin_init, init_pool()],
        [Txn.application_args[0] == action_admin_update, set_governor(Txn.accounts[1])],
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
        f.write(
            compileTeal(approval(10, 100), mode=Mode.Application, version=5)
        )

    with open(os.path.join(path, "clear.teal"), "w") as f:
        f.write(compileTeal(clear(), mode=Mode.Application, version=5))
