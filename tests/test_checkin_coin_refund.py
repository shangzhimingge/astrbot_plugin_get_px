import pytest

from checkin.store import CheckinStore


@pytest.mark.asyncio
async def test_add_coins_refunds_spent_coins(tmp_path):
    store = CheckinStore(str(tmp_path))
    await store.checkin(user_id="10001", username="测试用户", bot_name="neko")
    before = (await store.get_profile("10001")).coins
    spent = await store.spend_coins(user_id="10001", cost=10)
    assert spent.success
    refunded = await store.add_coins(user_id="10001", amount=10)
    assert refunded.success
    assert refunded.message == "金币已退回"
    assert refunded.cost == 10
    assert (await store.get_profile("10001")).coins == before


@pytest.mark.asyncio
async def test_add_coins_rejects_invalid_amount(tmp_path):
    store = CheckinStore(str(tmp_path))
    with pytest.raises(ValueError):
        await store.add_coins(user_id="10001", amount=0)
    with pytest.raises(ValueError):
        await store.add_coins(user_id="10001", amount=True)
