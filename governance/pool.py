import os

from pyteal import *
from pytealutils.storage import global_get_else
from pytealutils.string import itoa


gov_key = Bytes("gov")
pool_token_key = Bytes("p")

action_update = Bytes("update")
action_boot = Bytes("boot")

action_join = Bytes("join")
action_vote = Bytes("vote")
action_exit = Bytes("exit")

total_supply = int(1e17)
seed_amount = int(1e9)

# Takes unix timestamp for locked windows
def approval(lock_start: int = 0, lock_stop: int = 0):
    assert lock_start < lock_stop

    # Alias commonly used things
    me = Global.current_application_address()
    pool_token = App.globalGet(pool_token_key)
    pool_balance = AssetHolding.balance(me, pool_token)
    governor = global_get_else(gov_key, Global.creator_address())

    # Checks for if we're in the window for this action
    before_lock_start = Global.latest_timestamp() < Int(lock_start)
    after_lock_stop = Global.latest_timestamp() > Int(lock_stop)

    @Subroutine(TealType.uint64)
    def mint_tokens(algos_in):
        # Mint in 1:1 with algos passed in
        return algos_in

    @Subroutine(TealType.uint64)
    def burn_tokens(
        amt,
        balance_algos,
        tokens_minted,
    ):
        # Return the number of tokens * (algos per token)
        return amt * ((balance_algos - Int(seed_amount)) / tokens_minted)

    @Subroutine(TealType.uint64)
    def join():
        # Alias for specific txn indicies
        app_call, payment = Gtxn[0], Gtxn[1]
        well_formed_join = And(
            Global.group_size() == Int(2),  # App call, Payment to join
            app_call.type_enum() == TxnType.ApplicationCall,
            app_call.assets[0] == pool_token,
            payment.type_enum() == TxnType.Payment,
            payment.receiver() == me,
            payment.amount() > Int(0),
            payment.sender() == app_call.sender(),
        )

        return Seq(
            # Init MaybeValues
            pool_balance,
            # TODO: uncomment when done testing on dev
            # Assert(before_lock_start),
            Assert(well_formed_join),
            axfer(app_call.sender(), pool_token, mint_tokens(payment.amount())),
            Int(1),
        )

    # Action to allow caller to exit the contract, burning pool tokens in exchange for algos
    @Subroutine(TealType.uint64)
    def exit():
        # Alias for specific txn indicies
        app_call, pool_xfer = Gtxn[0], Gtxn[1]
        well_formed_exit = And(
            Global.group_size() == Int(2),
            app_call.type_enum() == TxnType.ApplicationCall,
            app_call.assets[0] == pool_token,
            pool_xfer.type_enum() == TxnType.AssetTransfer,
            pool_xfer.asset_receiver() == me,
            pool_xfer.xfer_asset() == pool_token,
            app_call.sender() == pool_xfer.sender(),
        )

        return Seq(
            pool_balance,
            # TODO: uncomment when done testing on dev
            # Assert(after_lock_stop),
            Assert(well_formed_exit),
            # Looks good, pay 'em
            pay(
                pool_xfer.sender(),
                burn_tokens(pool_xfer.asset_amount(), Balance(me), get_minted()),
            ),
            Int(1),
        )

    # Action to allow admin to commit algos or vote
    @Subroutine(TealType.uint64)
    def vote():
        app_call = Gtxn[0]
        well_formed_vote = And(
            Global.group_size() == Int(1),
            app_call.type_enum() == TxnType.ApplicationCall,
            app_call.sender() == governor,
        )
        return Seq(
            # TODO: assert we're in the voting window
            Assert(well_formed_vote),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: Txn.accounts[1],
                    TxnField.amount: Int(0),  # not strictly necessary
                    TxnField.note: Txn.application_args[
                        1
                    ],  # expecting a valid note as the 2nd element in app args array
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
            Int(1),
        )

    # Action to Bootstrap this application, creates pool token
    @Subroutine(TealType.uint64)
    def bootstrap():
        seed, app_call = Gtxn[0], Gtxn[1]
        well_formed_bootstrap = And(
            Global.group_size() == Int(2),
            # Seed amount so it can send transactions
            seed.type_enum() == TxnType.Payment,
            seed.amount() == Int(seed_amount),
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

    # Return the number of tokens minted
    @Subroutine(TealType.uint64)
    def get_minted():
        return Seq(pool_balance, Int(total_supply) - pool_balance.value())

    # Overwrite the current governor
    @Subroutine(TealType.uint64)
    def set_governor(new_gov):
        return Seq(
            Assert(Txn.sender() == governor), App.globalPut(gov_key, new_gov), Int(1)
        )

    # Util function to transfer an asset
    @Subroutine(TealType.none)
    def axfer(reciever, aid, amt):
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: aid,
                    TxnField.asset_amount: amt,
                    TxnField.asset_receiver: reciever,
                    TxnField.fee: Int(0),  # force caller to pay
                }
            ),
            InnerTxnBuilder.Submit(),
        )

    # Util function to make payment transaction
    @Subroutine(TealType.none)
    def pay(receiver, amt):
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.amount: amt,
                    TxnField.receiver: receiver,
                    TxnField.fee: Int(0),  # force caller to pay
                }
            ),
            InnerTxnBuilder.Submit(),
        )

    router = Cond(
        # Users
        [Txn.application_args[0] == action_join, join()],
        [Txn.application_args[0] == action_exit, exit()],
        # Admin
        [Txn.application_args[0] == action_boot, bootstrap()],
        [Txn.application_args[0] == action_update, set_governor(Txn.accounts[1])],
        [Txn.application_args[0] == action_vote, vote()],
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
    return compileTeal(approval(**kwargs), mode=Mode.Application, version=6)


def get_clear_src(**kwargs):
    return compileTeal(clear(**kwargs), mode=Mode.Application, version=6)


if __name__ == "__main__":
    path = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(path, "approval.teal"), "w") as f:
        f.write(get_approval_src(lock_start=1, lock_stop=10))

    with open(os.path.join(path, "clear.teal"), "w") as f:
        f.write(get_clear_src())
