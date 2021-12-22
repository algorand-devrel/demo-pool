import os

from pyteal import *
from pytealutils.storage import global_get_else
from pytealutils.string import itoa


gov_key = Bytes("gov")
pool_token_key = Bytes("p")

action_boot = Bytes("boot")

action_join = Bytes("join")
action_exit = Bytes("exit")

action_update = Bytes("update")

total_supply = int(1e17)
seed_amount = int(1e9)

# Takes unix timestamp for locked windows
def approval(lock_start: int = 0, lock_stop: int = 0):
    assert lock_start < lock_stop

    me = Global.current_application_address()

    pool_token = App.globalGet(pool_token_key)
    governor = global_get_else(gov_key, Global.creator_address())

    before_lock_start = And(Global.latest_timestamp() < Int(lock_start))
    after_lock_stop = And(Global.latest_timestamp() > Int(lock_stop))

    @Subroutine(TealType.uint64)
    def mint_tokens(algos_in: TealType.uint64):
        # Mint in 1:1 with algos passed in
        return algos_in

    @Subroutine(TealType.uint64)
    def burn_tokens(
        amt: TealType.uint64,
        balance_algos: TealType.uint64,
        tokens_minted: TealType.uint64,
    ):
        # Return the number of tokens * (algos per token)
        return amt * ((balance_algos - Int(seed_amount)) / tokens_minted)

    @Subroutine(TealType.uint64)
    def join():
        app_call = Gtxn[0]
        payment = Gtxn[1]
        well_formed_join = And(
            Global.group_size() == Int(2),  # App call, Payment to join
            app_call.type_enum() == TxnType.ApplicationCall,
            app_call.assets[0] == pool_token,
            payment.type_enum() == TxnType.Payment,
            payment.receiver() == me,
            payment.amount() > Int(0),
            payment.sender() == app_call.sender(),
        )

        pool_bal = AssetHolding.balance(me, pool_token)

        return Seq(
            # Init MaybeValues
            pool_bal,
            # TODO: uncomment when done testing on dev
            #Assert(before_lock_start),
            Assert(well_formed_join),
            axfer(app_call.sender(), pool_token, mint_tokens(payment.amount())),
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def exit():
        app_call = Gtxn[0]
        pool_xfer = Gtxn[1]
        well_formed_exit = And(
            Global.group_size() == Int(2),
            app_call.type_enum() == TxnType.ApplicationCall,
            app_call.assets[0] == pool_token,
            pool_xfer.type_enum() == TxnType.AssetTransfer,
            pool_xfer.asset_receiver() == me,
            pool_xfer.xfer_asset() == pool_token,
            app_call.sender() == pool_xfer.sender(),
        )

        pool_bal = AssetHolding.balance(me, pool_token)

        return Seq(
            pool_bal,
            # TODO: uncomment when done testing on dev
            #Assert(after_lock_stop),
            Assert(well_formed_exit),
            pay(
                pool_xfer.sender(),
                burn_tokens(
                    pool_xfer.asset_amount(),
                    Balance(me),
                    Int(total_supply) - pool_bal.value(),
                ),
            ),
            Int(1),
        )

    @Subroutine(TealType.none)
    def axfer(reciever: TealType.bytes, aid: TealType.uint64, amt: TealType.uint64):
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: aid,
                    TxnField.asset_amount: amt,
                    TxnField.asset_receiver: reciever,
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
        )

    @Subroutine(TealType.none)
    def pay(reciever: TealType.bytes, amt: TealType.uint64):
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.amount: amt,
                    TxnField.receiver: reciever,
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
        )
        
    @Subroutine(TealType.uint64)
    def set_governor(new_gov: TealType.bytes):
        return Seq(
            Assert(Txn.sender() == governor), App.globalPut(gov_key, new_gov), Int(1)
        )

    @Subroutine(TealType.uint64)
    def bootstrap():
        seed = Gtxn[0]
        app_call = Gtxn[1]
        well_formed_bootstrap = And(
            Global.group_size() == Int(2),
            # Seed amount so it can send transactions
            seed.type_enum() == TxnType.Payment,
            seed.amount() == Int(seed_amount),
            # 
            app_call.type_enum() == TxnType.ApplicationCall,
            app_call.sender() == governor,
            app_call.sender() == seed.sender(),
        )

        pool_token_check = App.globalGetEx(Int(0), pool_token_key)

        return Seq(
            pool_token_check,
            # Make sure we've not already set this
            Assert(Not(pool_token_check.hasValue())),
            Assert(well_formed_bootstrap),
            # Create the pool token
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetConfig,
                    TxnField.config_asset_name: Concat(
                        Bytes("GovernanceToken-"), itoa(Global.current_application_id())
                    ),
                    TxnField.config_asset_unit_name: Bytes("algo-gov"),
                    TxnField.config_asset_total: Int(total_supply),
                    TxnField.config_asset_manager: me,
                    TxnField.config_asset_reserve: me,
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
            # Write it to global state
            App.globalPut(pool_token_key, InnerTxn.created_asset_id()),
            Int(1),
        )

    router = Cond(
        # Users
        [Txn.application_args[0] == action_join, join()],
        [Txn.application_args[0] == action_exit, exit()],
        # Admin
        [Txn.application_args[0] == action_boot, bootstrap()],
        [Txn.application_args[0] == action_update, set_governor(Txn.accounts[1])],
    )

    return Cond(
        [Txn.application_id() == Int(0), Int(1)],
        [Txn.on_completion() == OnComplete.DeleteApplication, Txn.sender() == governor],
        [Txn.on_completion() == OnComplete.UpdateApplication, Txn.sender() == governor],
        [Txn.on_completion() == OnComplete.CloseOut, Int(1)],
        [Txn.on_completion() == OnComplete.OptIn, Int(0)],
        [Txn.on_completion() == OnComplete.NoOp, router],
    )


def clear():
    return Return(Int(1))


def get_approval_src(**kwargs):
    return compileTeal(approval(**kwargs), mode=Mode.Application, version=5)


def get_clear_src(**kwargs):
    return compileTeal(clear(**kwargs), mode=Mode.Application, version=5)


if __name__ == "__main__":
    path = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(path, "approval.teal"), "w") as f:
        f.write(get_approval_src(lock_start=1, lock_stop=10))

    with open(os.path.join(path, "clear.teal"), "w") as f:
        f.write(get_clear_src())
